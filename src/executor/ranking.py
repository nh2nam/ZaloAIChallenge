from __future__ import annotations

from typing import Any, Iterable, Sequence

from .aggregation import aggregate
from .duckdb_engine import DuckDBEngine
from .query_builder import FilterCondition, QueryBuilder


def rank_rows(
    engine: DuckDBEngine,
    table: str,
    metric_column: str,
    k: int,
    *,
    direction: str = "top",
    columns: Sequence[str] | None = None,
    filters: Iterable[FilterCondition | tuple[str, str, Any]] | None = None,
    tie_breakers: Sequence[tuple[str, str]] | None = None,
):
    """Return top-k or bottom-k raw rows using deterministic ordering."""
    if not isinstance(k, int) or k < 0:
        raise ValueError("k must be a non-negative integer")
    direction_key = direction.lower()
    if direction_key not in {"top", "bottom"}:
        raise ValueError("direction must be 'top' or 'bottom'")

    order = [(metric_column, "DESC" if direction_key == "top" else "ASC")]
    order.extend(list(tie_breakers or []))
    return QueryBuilder(engine).select(
        table,
        columns,
        filters=filters,
        order_by=order,
        limit=k,
    )


def rank_groups(
    engine: DuckDBEngine,
    table: str,
    *,
    group_by: Sequence[str],
    metric_column: str,
    aggregate_function: str = "SUM",
    k: int = 10,
    direction: str = "top",
):
    """Rank groups by an aggregate metric, e.g. top 5 products by revenue."""
    if not group_by:
        raise ValueError("group_by must contain at least one column")
    if not isinstance(k, int) or k < 0:
        raise ValueError("k must be a non-negative integer")
    direction_key = direction.lower()
    if direction_key not in {"top", "bottom"}:
        raise ValueError("direction must be 'top' or 'bottom'")

    result = aggregate(
        engine,
        table,
        {"metric_value": (aggregate_function, metric_column)},
        group_by=group_by,
        order_by=[("metric_value", "DESC" if direction_key == "top" else "ASC")]
                 + [(column, "ASC") for column in group_by],
        limit=k,
    )
    return result


def top_k(engine: DuckDBEngine, table: str, metric_column: str, k: int, **kwargs: Any):
    return rank_rows(engine, table, metric_column, k, direction="top", **kwargs)


def bottom_k(engine: DuckDBEngine, table: str, metric_column: str, k: int, **kwargs: Any):
    return rank_rows(engine, table, metric_column, k, direction="bottom", **kwargs)
