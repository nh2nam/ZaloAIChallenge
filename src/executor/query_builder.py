from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .duckdb_engine import DuckDBEngine, quote_identifier


@dataclass(frozen=True)
class FilterCondition:
    column: str
    operator: str
    value: Any = None


_ALLOWED_OPERATORS = {
    "=": "=", "==": "=", "!=": "!=", "<>": "!=",
    ">": ">", ">=": ">=", "<": "<", "<=": "<=",
    "LIKE": "LIKE", "ILIKE": "ILIKE",
    "IN": "IN", "NOT IN": "NOT IN",
    "BETWEEN": "BETWEEN",
    "IS NULL": "IS NULL", "IS NOT NULL": "IS NOT NULL",
}


def normalize_filter(item: FilterCondition | tuple[str, str, Any]) -> FilterCondition:
    if isinstance(item, FilterCondition):
        return item
    if len(item) != 3:
        raise ValueError("Each filter tuple must be (column, operator, value)")
    return FilterCondition(item[0], item[1], item[2])


def build_filter_sql(
    engine: DuckDBEngine,
    table: str,
    filters: Iterable[FilterCondition | tuple[str, str, Any]] | None,
    *,
    table_alias: str | None = None,
) -> tuple[str, list[Any]]:
    """Build a WHERE clause using validated identifiers and bound values."""
    if not filters:
        return "", []

    clauses: list[str] = []
    parameters: list[Any] = []

    for raw_filter in filters:
        condition = normalize_filter(raw_filter)
        operator_key = condition.operator.strip().upper()
        if operator_key not in _ALLOWED_OPERATORS:
            raise ValueError(
                f"Unsupported filter operator {condition.operator!r}. "
                f"Allowed operators: {sorted(_ALLOWED_OPERATORS)}"
            )
        operator = _ALLOWED_OPERATORS[operator_key]
        column_sql = engine.quote_column(table, condition.column)
        if table_alias:
            column_sql = f"{quote_identifier(table_alias)}.{column_sql}"

        if operator in {"IS NULL", "IS NOT NULL"}:
            clauses.append(f"{column_sql} {operator}")
        elif operator in {"IN", "NOT IN"}:
            if isinstance(condition.value, (str, bytes)):
                raise TypeError("IN/NOT IN value must be a non-string sequence")
            values = list(condition.value)
            if not values:
                clauses.append("FALSE" if operator == "IN" else "TRUE")
            else:
                placeholders = ", ".join("?" for _ in values)
                clauses.append(f"{column_sql} {operator} ({placeholders})")
                parameters.extend(values)
        elif operator == "BETWEEN":
            if not isinstance(condition.value, (tuple, list)) or len(condition.value) != 2:
                raise ValueError("BETWEEN requires a two-item tuple/list")
            clauses.append(f"{column_sql} BETWEEN ? AND ?")
            parameters.extend(condition.value)
        else:
            clauses.append(f"{column_sql} {operator} ?")
            parameters.append(condition.value)

    return " WHERE " + " AND ".join(clauses), parameters


class QueryBuilder:
    """Build common SELECT queries without accepting arbitrary SQL fragments."""

    def __init__(self, engine: DuckDBEngine) -> None:
        self.engine = engine

    def build_select(
        self,
        table: str,
        columns: Sequence[str] | None = None,
        *,
        filters: Iterable[FilterCondition | tuple[str, str, Any]] | None = None,
        order_by: Sequence[tuple[str, str]] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> tuple[str, list[Any]]:
        registration = self.engine.resolve_table(table)
        selected = list(columns or ["*"])

        if selected == ["*"]:
            columns_sql = "*"
        else:
            if not selected:
                raise ValueError("columns cannot be empty; use ['*'] for all columns")
            columns_sql = ", ".join(
                self.engine.quote_column(table, column)
                for column in selected
            )

        where_sql, parameters = build_filter_sql(self.engine, table, filters)
        sql = f"SELECT {columns_sql} FROM {registration.sql_name}{where_sql}"

        if order_by:
            order_parts = []
            for column, direction in order_by:
                direction = direction.upper()
                if direction not in {"ASC", "DESC"}:
                    raise ValueError("ORDER BY direction must be ASC or DESC")
                order_parts.append(
                    f"{self.engine.quote_column(table, column)} {direction}"
                )
            sql += " ORDER BY " + ", ".join(order_parts)

        if limit is not None:
            if not isinstance(limit, int) or limit < 0:
                raise ValueError("limit must be a non-negative integer")
            sql += " LIMIT ?"
            parameters.append(limit)

        if offset is not None:
            if not isinstance(offset, int) or offset < 0:
                raise ValueError("offset must be a non-negative integer")
            if limit is None:
                sql += " LIMIT ALL"
            sql += " OFFSET ?"
            parameters.append(offset)

        return sql, parameters

    def select(self, table: str, columns: Sequence[str] | None = None, **kwargs: Any):
        sql, parameters = self.build_select(table, columns, **kwargs)
        return self.engine.execute_query(sql, parameters)
