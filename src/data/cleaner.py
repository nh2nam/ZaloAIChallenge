from __future__ import annotations

import re
from typing import Any

import pandas as pd


MISSING_TOKENS = {"", "na", "n/a", "null", "none", "nan"}
DATE_NAME_TOKENS = ("date", "time", "ngay", "thang", "created_at", "updated_at")
PROTECTED_NAME_TOKENS = {
    "id", "code", "ma", "phone", "mobile", "tax", "zip", "postal",
    "sku", "barcode", "account", "sdt", "cccd", "cmnd"
}


def _is_identifier_column(column_name: str) -> bool:
    """Bảo vệ cột mã định danh; tránh match nhầm 'id' bên trong 'paid_amount'."""
    name = re.sub(r"([a-z])([A-Z])", r"\1_\2", str(column_name)).lower()
    tokens = {token for token in re.split(r"[^a-z0-9]+", name) if token}
    return bool(tokens & PROTECTED_NAME_TOKENS)


def clean_dataframe(
    dataframe: pd.DataFrame,
    *,
    strip_strings: bool = True,
    normalize_missing: bool = True,
    parse_dates: bool = True,
    convert_numeric: bool = True,
    fill_values: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Làm sạch thận trọng, không tự động điền missing bằng 0.

    Trả về (dataframe_mới, report). DataFrame gốc không bị sửa.
    - Chuẩn hóa khoảng trắng.
    - Đổi một số token rỗng phổ biến thành NA.
    - Parse cột có tên gợi ý ngày/giờ nếu >= 80% giá trị hợp lệ.
    - Chuyển cột số dạng text nếu >= 98% giá trị hợp lệ và tên cột
      không giống mã định danh/điện thoại/mã số.
    - Chỉ fill missing khi người gọi truyền fill_values rõ ràng.
    """
    df = dataframe.copy()
    report: dict[str, Any] = {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "missing_before": int(df.isna().sum().sum()),
        "string_values_stripped": 0,
        "missing_tokens_normalized": 0,
        "date_columns_converted": [],
        "numeric_columns_converted": [],
        "date_values_coerced_to_missing": {},
        "fill_values_applied": {},
    }

    for column in df.columns:
        series = df[column]

        if strip_strings and (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
            before = series.copy()
            stripped = series.map(lambda value: value.strip() if isinstance(value, str) else value)
            report["string_values_stripped"] += int(
                ((before != stripped) & before.notna() & stripped.notna()).sum()
            )
            series = stripped

        if normalize_missing and (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
            before_missing = int(series.isna().sum())
            series = series.map(
                lambda value: pd.NA
                if isinstance(value, str) and value.strip().lower() in MISSING_TOKENS
                else value
            )
            report["missing_tokens_normalized"] += max(
                0, int(series.isna().sum()) - before_missing
            )

        df[column] = series

    if parse_dates:
        for column in df.columns:
            name = str(column).lower()
            if not any(token in name for token in DATE_NAME_TOKENS):
                continue
            if pd.api.types.is_datetime64_any_dtype(df[column]):
                continue

            non_null = df[column].dropna()
            if non_null.empty:
                continue

            parsed = pd.to_datetime(non_null, errors="coerce", dayfirst=True)
            valid_ratio = float(parsed.notna().mean())

            if valid_ratio >= 0.80:
                full_parsed = pd.to_datetime(df[column], errors="coerce", dayfirst=True)
                new_missing = int(full_parsed.isna().sum()) - int(df[column].isna().sum())
                df[column] = full_parsed
                report["date_columns_converted"].append(str(column))
                if new_missing > 0:
                    report["date_values_coerced_to_missing"][str(column)] = new_missing

    if convert_numeric:
        for column in df.columns:
            name = str(column).lower()
            if _is_identifier_column(name):
                continue
            if pd.api.types.is_numeric_dtype(df[column]) or pd.api.types.is_datetime64_any_dtype(df[column]):
                continue
            if not (pd.api.types.is_object_dtype(df[column]) or pd.api.types.is_string_dtype(df[column])):
                continue

            non_null = df[column].dropna()
            if non_null.empty:
                continue

            # Chỉ đổi khi cột gần như hoàn toàn là số; không đoán định dạng tiền tệ
            # có dấu phân cách hàng nghìn kiểu địa phương.
            numeric = pd.to_numeric(non_null, errors="coerce")
            valid_ratio = float(numeric.notna().mean())
            if valid_ratio >= 0.98:
                df[column] = pd.to_numeric(df[column], errors="coerce")
                report["numeric_columns_converted"].append(str(column))

    if fill_values:
        for column, fill_value in fill_values.items():
            if column in df.columns:
                missing_count = int(df[column].isna().sum())
                df[column] = df[column].fillna(fill_value)
                report["fill_values_applied"][str(column)] = {
                    "value": str(fill_value),
                    "count": missing_count,
                }

    report["missing_after"] = int(df.isna().sum().sum())
    return df, report
