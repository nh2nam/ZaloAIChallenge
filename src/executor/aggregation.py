from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .duckdb_engine import DuckDBEngine, quote_identifier
from .query_builder import FilterCondition, build_filter_sql


_ALLOWED_AGGREGATIONS = {
    "SUM": "SUM",
    "AVG": "AVG",
    "AVERAGE": "AVG",
    "COUNT": "COUNT",
    "MIN": "MIN",
    "MAX": "MAX",
    "COUNT_DISTINCT": "COUNT",
}


@dataclass(frozen=True)
class Metric:
    alias: str
    function: str
    column: str = "*"


def aggregate(
    engine: DuckDBEngine,
    table: str,
    metrics: Sequence[Metric] | dict[str, tuple[str, str]],
    *,
    group_by: Sequence[str] | None = None,
    filters: Iterable[FilterCondition | tuple[str, str, Any]] | None = None,
    order_by: Sequence[tuple[str, str]] | None = None,
    limit: int | None = None,
):
    """Run SUM/AVG/COUNT/MIN/MAX/COUNT_DISTINCT on one registered table.

    Example:
        aggregate(engine, "biz_101.orders",
                  {"total_amount": ("SUM", "amount"),
                   "order_count": ("COUNT", "*")},
                  group_by=["customer_id"])
    """
    registration = engine.resolve_table(table)
    if isinstance(metrics, dict):
        metric_items = [Metric(alias, function, column) for alias, (function, column) in metrics.items()]
    else:
        metric_items = list(metrics)

    if not metric_items:
        raise ValueError("At least one aggregation metric is required")

    group_columns = list(group_by or [])
    group_sql = [engine.quote_column(table, column) for column in group_columns]

    select_parts = list(group_sql)
    for metric in metric_items:
        function_key = metric.function.upper()
        if function_key not in _ALLOWED_AGGREGATIONS:
            raise ValueError(
                f"Unsupported aggregation {metric.function!r}. "
                f"Allowed: {sorted(_ALLOWED_AGGREGATIONS)}"
            )
        function = _ALLOWED_AGGREGATIONS[function_key]

        if metric.column == "*":
            if function_key != "COUNT":
                raise ValueError("Only COUNT may aggregate '*'")
            expression = "*"
        else:
            column_sql = engine.quote_column(table, metric.column)
            if function_key == "COUNT_DISTINCT":
                expression = f"DISTINCT {column_sql}"
            else:
                expression = column_sql

        select_parts.append(
            f"{function}({expression}) AS {quote_identifier(metric.alias)}"
        )

    where_sql, parameters = build_filter_sql(engine, table, filters)
    sql = (
        f"SELECT {', '.join(select_parts)} "
        f"FROM {registration.sql_name}{where_sql}"
    )

    if group_sql:
        sql += " GROUP BY " + ", ".join(group_sql)

    if order_by:
        order_parts = []
        output_names = set(group_columns) | {m.alias for m in metric_items}
        for name, direction in order_by:
            direction = direction.upper()
            if direction not in {"ASC", "DESC"}:
                raise ValueError("ORDER BY direction must be ASC or DESC")
            if name not in output_names:
                raise KeyError(f"Unknown aggregation output column: {name}")
            order_parts.append(f"{quote_identifier(name)} {direction}")
        sql += " ORDER BY " + ", ".join(order_parts)

    if limit is not None:
        if not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        sql += " LIMIT ?"
        parameters.append(limit)

    return engine.execute_query(sql, parameters)
