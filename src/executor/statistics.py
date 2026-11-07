from __future__ import annotations

from typing import Any

import pandas as pd

from .duckdb_engine import DuckDBEngine, quote_identifier


_ALLOWED_PERIODS = {"day", "week", "month", "quarter", "year"}
_ALLOWED_AGGREGATES = {"SUM", "AVG", "COUNT", "MIN", "MAX"}


def calculate_change(current: float, previous: float) -> dict[str, float | None]:
    """Calculate absolute difference, ratio and percentage growth.

    When previous is zero, ratio and growth are undefined and are returned as
    None rather than infinity or a misleading zero.
    """
    current_value = float(current)
    previous_value = float(previous)
    difference = current_value - previous_value

    if previous_value == 0:
        ratio = None
        growth_pct = None
    else:
        ratio = current_value / previous_value
        growth_pct = difference / previous_value * 100.0

    return {
        "current": current_value,
        "previous": previous_value,
        "absolute_change": difference,
        "ratio": ratio,
        "growth_pct": growth_pct,
    }


def period_over_period(
    engine: DuckDBEngine,
    table: str,
    *,
    date_column: str,
    value_column: str,
    period: str = "month",
    aggregation: str = "SUM",
) -> pd.DataFrame:
    """Aggregate values by period and compare each period with the previous.

    Returns: period, current_value, previous_value, absolute_change,
    growth_pct. Rows with no prior period have NULL previous/change values.
    LAG compares with the previous period present in the data; if a calendar
    month is missing, it compares with the most recent observed month.
    """
    period_key = period.lower()
    if period_key not in _ALLOWED_PERIODS:
        raise ValueError(f"period must be one of {sorted(_ALLOWED_PERIODS)}")
    agg = aggregation.upper()
    if agg not in _ALLOWED_AGGREGATES:
        raise ValueError(f"aggregation must be one of {sorted(_ALLOWED_AGGREGATES)}")

    registration = engine.resolve_table(table)
    date_sql = engine.quote_column(table, date_column)
    value_sql = engine.quote_column(table, value_column)

    # period_key and agg are selected only from fixed allow-lists above.
    query = f"""
        WITH period_values AS (
            SELECT
                DATE_TRUNC('{period_key}', TRY_CAST({date_sql} AS DATE)) AS period,
                {agg}(TRY_CAST({value_sql} AS DECIMAL(38, 6))) AS current_value
            FROM {registration.sql_name}
            WHERE TRY_CAST({date_sql} AS DATE) IS NOT NULL
            GROUP BY 1
        ),
        with_previous AS (
            SELECT
                period,
                current_value,
                LAG(current_value) OVER (ORDER BY period) AS previous_value
            FROM period_values
        )
        SELECT
            period,
            current_value,
            previous_value,
            current_value - previous_value AS absolute_change,
            CASE
                WHEN previous_value IS NULL OR previous_value = 0 THEN NULL
                ELSE (current_value - previous_value) / previous_value * 100.0
            END AS growth_pct
        FROM with_previous
        ORDER BY period
    """
    return engine.fetch_df(query)


def percentage_of_total(
    engine: DuckDBEngine,
    table: str,
    *,
    group_by: str,
    value_column: str,
) -> pd.DataFrame:
    """Return grouped SUM and its percentage of the grand total."""
    registration = engine.resolve_table(table)
    group_sql = engine.quote_column(table, group_by)
    value_sql = engine.quote_column(table, value_column)

    query = f"""
        WITH grouped AS (
            SELECT
                {group_sql} AS group_value,
                SUM(TRY_CAST({value_sql} AS DOUBLE)) AS total_value
            FROM {registration.sql_name}
            GROUP BY 1
        )
        SELECT
            group_value,
            total_value,
            CASE
                WHEN SUM(total_value) OVER () = 0 THEN NULL
                ELSE CAST(total_value AS DOUBLE)
                     / CAST(SUM(total_value) OVER () AS DOUBLE) * 100.0
            END AS percentage
        FROM grouped
        ORDER BY group_value
    """
    return engine.fetch_df(query)
