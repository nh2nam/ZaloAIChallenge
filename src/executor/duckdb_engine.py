from __future__ import annotations

import re
import warnings
from datetime import date, datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import duckdb
import numpy as np
import pandas as pd


class QueryExecutionError(RuntimeError):
    """Raised when a SQL query fails in the convenience fetch_df method."""


@dataclass(frozen=True)
class TableRegistration:
    """Metadata describing a DataFrame registered as a DuckDB table."""

    qualified_name: str       # Original Phase 1 name, e.g. biz_101.orders
    schema_name: str          # Physical DuckDB schema, e.g. biz_101
    table_name: str
    source_file: str
    source_type: str
    columns: tuple[str, ...]
    row_count: int

    @property
    def sql_name(self) -> str:
        return f'{quote_identifier(self.schema_name)}.{quote_identifier(self.table_name)}'


@dataclass
class QueryResult:
    success: bool
    result: pd.DataFrame | None = None
    error: str | None = None
    row_count: int = 0
    columns: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "row_count": self.row_count,
            "columns": self.columns or [],
        }


def quote_identifier(identifier: str) -> str:
    """Quote one SQL identifier; never use this for a value/literal."""
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("SQL identifier must be a non-empty string")
    return '"' + identifier.replace('"', '""') + '"'


class DuckDBEngine:
    """Small in-process DuckDB engine for DataMate business data.

    Phase 1 continues to load files into pandas DataFrames. This engine copies
    those DataFrames into DuckDB tables and exposes safe table/column lookup,
    parameterized execution, and result conversion back to pandas.

    By convention, each business receives its own DuckDB schema:
      biz_101.orders       -> schema biz_101, table orders
      __global__.calendar  -> schema global_data, table calendar

    Raw SQL is intended for trusted, developer-written SELECT statements in
    this phase. Values should be supplied through `parameters`, not interpolated
    into SQL strings.
    """

    def __init__(self, database: str | Path = ":memory:") -> None:
        self.database = str(database)
        if self.database != ":memory:":
            Path(self.database).expanduser().resolve().parent.mkdir(
                parents=True, exist_ok=True
            )
        self.connection = duckdb.connect(database=self.database)
        self._registrations: dict[str, TableRegistration] = {}
        self._temporary_counter = 0
        self._closed = False

    @staticmethod
    def _physical_schema(business_id: str) -> str:
        return "global_data" if business_id == "__global__" else business_id

    @staticmethod
    def _prepare_dataframe_for_duckdb(
        dataframe: pd.DataFrame,
        *,
        qualified_name: str,
        source_file: str,
    ) -> pd.DataFrame:
        """Normalize mixed Python datetime/string object columns before registration.

        Pandas object columns can contain Python datetime objects alongside text
        values (for example a repeated Excel header row: 'Thời gian tạo').
        DuckDB may infer TIMESTAMP from the datetime values and then fail when it
        encounters the text value. We parse mostly-date columns and coerce invalid
        labels to NaT; otherwise we preserve the mixed values as VARCHAR strings.
        The input DataFrame is never modified.
        """
        prepared = dataframe.copy()
        temporal_types = (pd.Timestamp, datetime, date, np.datetime64)

        for column in prepared.columns:
            series = prepared[column]
            if not pd.api.types.is_object_dtype(series):
                continue

            values = series.dropna()
            if values.empty:
                continue

            has_temporal = values.map(
                lambda value: isinstance(value, temporal_types)
            ).any()
            has_text = values.map(lambda value: isinstance(value, str)).any()

            if not (has_temporal and has_text):
                continue

            parsed = pd.to_datetime(
                series,
                errors="coerce",
                format="mixed",
                dayfirst=True,
            )
            valid_ratio = float(parsed.notna().sum() / len(values))
            invalid_mask = series.notna() & parsed.isna()

            if valid_ratio >= 0.80:
                invalid_examples = (
                    series.loc[invalid_mask]
                    .astype(str)
                    .drop_duplicates()
                    .head(5)
                    .tolist()
                )
                prepared[column] = parsed
                warnings.warn(
                    f"[{qualified_name} | {source_file}] Column {column!r} "
                    f"contained mixed datetime/text values. Parsed as TIMESTAMP; "
                    f"{int(invalid_mask.sum())} invalid value(s) became NULL. "
                    f"Examples: {invalid_examples}",
                    UserWarning,
                    stacklevel=2,
                )
            else:
                # If the majority is not a valid date, do not guess a timestamp.
                # Convert every non-null item consistently to text to avoid DuckDB
                # inferring TIMESTAMP from only the first few Python objects.
                prepared[column] = series.map(
                    lambda value: (
                        value.isoformat()
                        if isinstance(value, (pd.Timestamp, datetime, date))
                        else str(value)
                    ) if pd.notna(value) else pd.NA
                ).astype("string")
                warnings.warn(
                    f"[{qualified_name} | {source_file}] Column {column!r} "
                    f"contains mixed datetime/text values but fewer than 80% "
                    f"are parseable as dates. Preserved as VARCHAR to avoid "
                    f"silently forcing an incorrect TIMESTAMP type.",
                    UserWarning,
                    stacklevel=2,
                )

        return prepared

    def register_dataframe(
        self,
        qualified_name: str,
        dataframe: pd.DataFrame,
        *,
        source_file: str = "<dataframe>",
        source_type: str = "dataframe",
        replace: bool = False,
    ) -> TableRegistration:
        """Register one DataFrame as a physical DuckDB table.

        `qualified_name` should normally be `business_id.table_name`. Use
        `__global__.calendar` for package-wide tables such as calendar.csv.
        """
        if self._closed:
            raise RuntimeError("DuckDBEngine is already closed")
        if not isinstance(dataframe, pd.DataFrame):
            raise TypeError("dataframe must be a pandas.DataFrame")
        if "." not in qualified_name:
            raise ValueError(
                "qualified_name must be 'business_id.table_name', "
                "for example 'biz_101.orders'"
            )

        business_id, table_name = qualified_name.split(".", 1)
        if not business_id or not table_name:
            raise ValueError(f"Invalid qualified table name: {qualified_name!r}")

        if qualified_name in self._registrations and not replace:
            raise ValueError(
                f"Duplicate table registration: {qualified_name}. "
                "Two source files may have the same table name; rename one "
                "or resolve the collision before registering."
            )

        dataframe = self._prepare_dataframe_for_duckdb(
            dataframe,
            qualified_name=qualified_name,
            source_file=source_file,
        )

        schema_name = self._physical_schema(business_id)
        self.connection.execute(
            f"CREATE SCHEMA IF NOT EXISTS {quote_identifier(schema_name)}"
        )

        self._temporary_counter += 1
        temporary_name = f"_dm_dataframe_{self._temporary_counter}"
        target_name = (
            f"{quote_identifier(schema_name)}.{quote_identifier(table_name)}"
        )

        self.connection.register(temporary_name, dataframe)
        try:
            create_mode = "CREATE OR REPLACE TABLE" if replace else "CREATE TABLE"
            self.connection.execute(
                f"{create_mode} {target_name} "
                f"AS SELECT * FROM {quote_identifier(temporary_name)}"
            )
        except Exception as exc:
            dtype_summary = {
                str(column): str(dataframe[column].dtype)
                for column in dataframe.columns
            }
            raise RuntimeError(
                f"DuckDB failed to register table {qualified_name!r} "
                f"from file {source_file!r}. DataFrame shape={dataframe.shape}; "
                f"dtypes={dtype_summary}. Check mixed-type columns and "
                f"repeated header rows. Original error: {exc}"
            ) from exc
        finally:
            self.connection.unregister(temporary_name)

        registration = TableRegistration(
            qualified_name=qualified_name,
            schema_name=schema_name,
            table_name=table_name,
            source_file=source_file,
            source_type=source_type,
            columns=tuple(str(column) for column in dataframe.columns),
            row_count=int(len(dataframe)),
        )
        self._registrations[qualified_name] = registration
        return registration

    def register_package(self, package: Any, *, replace: bool = False) -> list[TableRegistration]:
        """Register all Phase 1 `package.tables` into DuckDB.

        The method intentionally accepts the package by duck typing so the
        executor does not need to import Phase 1 classes at module import time.
        """
        registered: list[TableRegistration] = []
        seen: set[str] = set()
        for table in package.tables:
            qualified_name = table.qualified_name
            if qualified_name in seen:
                raise ValueError(
                    f"Phase 1 package contains duplicate qualified table name "
                    f"{qualified_name!r}. The files may share the same stem."
                )
            seen.add(qualified_name)
            registered.append(
                self.register_dataframe(
                    qualified_name,
                    table.dataframe,
                    source_file=getattr(table, "source_file", ""),
                    source_type=getattr(table, "source_type", "dataframe"),
                    replace=replace,
                )
            )
        return registered

    def resolve_table(self, name: str) -> TableRegistration:
        """Resolve an original qualified name or an unambiguous bare table name."""
        if name in self._registrations:
            return self._registrations[name]

        # Allow physical global_data.calendar as an alternative to
        # __global__.calendar.
        if name.startswith("global_data."):
            candidate = "__global__." + name.split(".", 1)[1]
            if candidate in self._registrations:
                return self._registrations[candidate]

        if "." not in name:
            matches = [
                item for item in self._registrations.values()
                if item.table_name == name
            ]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                choices = ", ".join(sorted(x.qualified_name for x in matches))
                raise ValueError(
                    f"Table name {name!r} is ambiguous. Use one of: {choices}"
                )

        available = ", ".join(sorted(self._registrations)) or "<none>"
        raise KeyError(f"Unknown table {name!r}. Registered tables: {available}")

    def sql_table(self, name: str) -> str:
        """Return a safely quoted physical SQL table reference."""
        return self.resolve_table(name).sql_name

    def quote_column(self, table: str, column: str) -> str:
        """Validate a column against the registered table, then quote it."""
        registration = self.resolve_table(table)
        if column not in registration.columns:
            raise KeyError(
                f"Unknown column {column!r} in {registration.qualified_name}. "
                f"Available columns: {list(registration.columns)}"
            )
        return quote_identifier(column)

    def has_column(self, table: str, column: str) -> bool:
        return column in self.resolve_table(table).columns

    def list_tables(self) -> list[dict[str, Any]]:
        """Return a deterministic inventory of all registered tables."""
        rows = []
        for item in sorted(self._registrations.values(), key=lambda x: x.qualified_name):
            rows.append(
                {
                    "qualified_name": item.qualified_name,
                    "sql_name": item.sql_name,
                    "business_id": (
                        "__global__" if item.schema_name == "global_data"
                        else item.schema_name
                    ),
                    "table_name": item.table_name,
                    "source_file": item.source_file,
                    "source_type": item.source_type,
                    "row_count": item.row_count,
                    "column_count": len(item.columns),
                    "columns": list(item.columns),
                }
            )
        return rows

    @staticmethod
    def _validate_read_query(query: str) -> None:
        """Keep the public executor read-only for this analytics phase."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty SQL string")

        sql = query.strip()
        # Multiple statements are deliberately unsupported. Semicolons inside
        # values should be passed as parameters, not embedded in SQL text.
        without_final_semicolon = sql[:-1] if sql.endswith(";") else sql
        if ";" in without_final_semicolon:
            raise ValueError("Only one SQL statement is allowed per call")

        # Strip leading SQL comments before checking the statement type.
        remaining = sql
        while True:
            remaining = remaining.lstrip()
            if remaining.startswith("--"):
                newline = remaining.find("\n")
                if newline < 0:
                    raise ValueError("SQL comment without a query")
                remaining = remaining[newline + 1:]
                continue
            if remaining.startswith("/*"):
                end = remaining.find("*/", 2)
                if end < 0:
                    raise ValueError("Unterminated SQL block comment")
                remaining = remaining[end + 2:]
                continue
            break

        match = re.match(r"([A-Za-z]+)", remaining)
        keyword = match.group(1).upper() if match else ""
        allowed = {"SELECT", "WITH", "EXPLAIN", "VALUES", "DESCRIBE", "SHOW"}
        if keyword not in allowed:
            raise ValueError(
                "Only read-only SQL statements are allowed in Phase 2 "
                "(SELECT, WITH, EXPLAIN, VALUES, DESCRIBE, SHOW)."
            )

        # A WITH statement can prefix a data-changing statement in some SQL
        # dialects. Reject write/administrative keywords in the SQL text. This
        # is a guardrail, not a replacement for using trusted SQL only.
        # Ignore quoted identifiers, string literals and comments so a legal
        # column name such as "update" or a value like 'delete' is not mistaken
        # for a write statement.
        scan_text = re.sub(
            r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\r\n]*|/\*.*?\*/",
            " ",
            remaining,
            flags=re.DOTALL,
        )
        forbidden = re.compile(
            r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|DROP|ALTER|TRUNCATE|"
            r"COPY|ATTACH|DETACH|INSTALL|LOAD|EXPORT|IMPORT|CALL|PRAGMA)\b",
            re.IGNORECASE,
        )
        if forbidden.search(scan_text):
            raise ValueError("Write or administrative SQL is disabled in Phase 2")

    def execute_query(
        self,
        query: str,
        parameters: Sequence[Any] | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one read-only query and return a result dictionary.

        Values are bound through DuckDB parameters (`?`) to avoid SQL string
        interpolation. Errors are returned instead of terminating the caller.
        """
        try:
            self._validate_read_query(query)
            bound_parameters = [] if parameters is None else parameters
            cursor = self.connection.execute(query, bound_parameters)
            dataframe = cursor.fetchdf()
            return QueryResult(
                success=True,
                result=dataframe,
                row_count=len(dataframe),
                columns=list(dataframe.columns),
            ).as_dict()
        except Exception as exc:
            return QueryResult(
                success=False,
                error=f"{type(exc).__name__}: {exc}",
            ).as_dict()

    def fetch_df(
        self,
        query: str,
        parameters: Sequence[Any] | dict[str, Any] | None = None,
    ) -> pd.DataFrame:
        """Execute a query and raise QueryExecutionError on failure."""
        result = self.execute_query(query, parameters)
        if not result["success"]:
            raise QueryExecutionError(result["error"] or "Unknown DuckDB error")
        return result["result"]

    def close(self) -> None:
        if not self._closed:
            self.connection.close()
            self._closed = True

    def __enter__(self) -> "DuckDBEngine":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()
