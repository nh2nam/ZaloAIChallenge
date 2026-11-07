from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .loader import LoadedTable


def _to_json_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _semantic_dtype(series: pd.Series) -> str:
    dtype = series.dtype

    if pd.api.types.is_bool_dtype(dtype):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "datetime"
    if pd.api.types.is_integer_dtype(dtype):
        return "integer"
    if pd.api.types.is_float_dtype(dtype):
        return "float"
    if pd.api.types.is_numeric_dtype(dtype):
        return "numeric"

    if series.dropna().empty:
        return "empty"

    return "string" if pd.api.types.is_string_dtype(dtype) else "object"


def inspect_table(table: LoadedTable, sample_size: int = 3) -> dict[str, Any]:
    """Tạo metadata cho một bảng; không thay đổi DataFrame."""
    df = table.dataframe
    row_count = int(len(df))
    columns = []

    for column in df.columns:
        series = df[column]
        missing_count = int(series.isna().sum())
        non_null = series.dropna()

        columns.append(
            {
                "name": str(column),
                "dtype": _semantic_dtype(series),
                "pandas_dtype": str(series.dtype),
                "non_null_count": int(non_null.shape[0]),
                "missing_count": missing_count,
                "missing_pct": round(missing_count / row_count * 100, 2) if row_count else 0.0,
                "unique_count": int(non_null.nunique()),
                "sample_values": [_to_json_value(v) for v in non_null.head(sample_size).tolist()],
            }
        )

    return {
        "qualified_name": table.qualified_name,
        "business_id": table.business_id,
        "table_name": table.table_name,
        "source_file": table.source_file,
        "source_type": table.source_type,
        "sheet_name": table.sheet_name,
        "row_count": row_count,
        "column_count": int(len(df.columns)),
        "columns": columns,
        "foreign_keys": table.foreign_keys,
        "cleaning_report": table.cleaning_report,
    }


def inspect_package(tables: list[LoadedTable], sample_size: int = 3) -> list[dict[str, Any]]:
    return [inspect_table(table, sample_size=sample_size) for table in tables]


def show_table_preview(table: LoadedTable, rows: int = 5) -> None:
    print("\n" + "=" * 80)
    print(f"{table.qualified_name} | {table.source_file}")
    print(f"Shape: {table.dataframe.shape}")
    print("=" * 80)
    print(table.dataframe.head(rows).to_string(index=False))
