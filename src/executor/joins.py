from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .duckdb_engine import DuckDBEngine, quote_identifier
from .query_builder import FilterCondition, _ALLOWED_OPERATORS


@dataclass(frozen=True)
class JoinSpec:
    table: str
    alias: str
    left_alias: str
    left_column: str
    right_column: str
    join_type: str = "INNER"


@dataclass(frozen=True)
class Selection:
    table_alias: str
    column: str
    output_alias: str | None = None


@dataclass(frozen=True)
class JoinFilter:
    table_alias: str
    column: str
    operator: str
    value: Any = None


@dataclass(frozen=True)
class JoinMetric:
    output_alias: str
    function: str
    source: Selection | None = None  # None means COUNT(*)


_ALLOWED_JOIN_TYPES = {"INNER", "LEFT", "RIGHT", "FULL OUTER"}
_ALLOWED_AGGREGATES = {"SUM", "AVG", "COUNT", "MIN", "MAX", "COUNT_DISTINCT"}


class JoinHandler:
    """Build and execute safe two-or-more-table joins.

    A JoinSpec joins one new table to an alias already present in the query.
    This makes join order explicit and supports chains such as orders ->
    customers -> order_items -> products.
    """

    def __init__(self, engine: DuckDBEngine) -> None:
        self.engine = engine

    def build_join_query(
        self,
        base_table: str,
        *,
        base_alias: str,
        joins: Sequence[JoinSpec],
        selections: Sequence[Selection] | None = None,
        filters: Iterable[JoinFilter] | None = None,
        group_by: Sequence[Selection] | None = None,
        metrics: Sequence[JoinMetric] | None = None,
        order_by: Sequence[tuple[str, str]] | None = None,
        limit: int | None = None,
    ) -> tuple[str, list[Any]]:
        base_registration = self.engine.resolve_table(base_table)
        aliases: dict[str, str] = {base_alias: base_table}
        if not base_alias:
            raise ValueError("base_alias cannot be empty")

        sql = (
            f"FROM {base_registration.sql_name} "
            f"AS {quote_identifier(base_alias)}"
        )

        for join in joins:
            join_type = join.join_type.upper().strip()
            if join_type not in _ALLOWED_JOIN_TYPES:
                raise ValueError(f"Unsupported join type: {join.join_type}")
            if join.alias in aliases:
                raise ValueError(f"Duplicate SQL alias: {join.alias}")
            if join.left_alias not in aliases:
                raise ValueError(
                    f"Join left alias {join.left_alias!r} has not been introduced"
                )

            left_table_name = aliases[join.left_alias]
            left_column = self.engine.quote_column(left_table_name, join.left_column)
            right_registration = self.engine.resolve_table(join.table)
            right_column = self.engine.quote_column(join.table, join.right_column)

            sql += (
                f" {join_type} JOIN {right_registration.sql_name} "
                f"AS {quote_identifier(join.alias)} "
                f"ON {quote_identifier(join.left_alias)}.{left_column} = "
                f"{quote_identifier(join.alias)}.{right_column}"
            )
            aliases[join.alias] = join.table

        def selection_expression(selection: Selection) -> str:
            if selection.table_alias not in aliases:
                raise KeyError(f"Unknown table alias: {selection.table_alias}")
            column_sql = self.engine.quote_column(
                aliases[selection.table_alias], selection.column
            )
            return f"{quote_identifier(selection.table_alias)}.{column_sql}"

        def selection_sql(selection: Selection) -> str:
            expression = selection_expression(selection)
            if selection.output_alias:
                expression += f" AS {quote_identifier(selection.output_alias)}"
            return expression

        group_items = list(group_by or [])
        metric_items = list(metrics or [])
        if metric_items:
            select_items = [selection_sql(item) for item in group_items]
            for metric in metric_items:
                function = metric.function.upper()
                if function not in _ALLOWED_AGGREGATES:
                    raise ValueError(f"Unsupported join aggregation: {function}")
                if metric.source is None:
                    if function != "COUNT":
                        raise ValueError("Only COUNT can aggregate '*' in JoinMetric")
                    expression = "*"
                else:
                    if metric.source.table_alias not in aliases:
                        raise KeyError(f"Unknown table alias: {metric.source.table_alias}")
                    source_sql = selection_expression(metric.source)
                    if function == "COUNT_DISTINCT":
                        expression = f"DISTINCT {source_sql}"
                        function = "COUNT"
                    else:
                        expression = source_sql
                select_items.append(
                    f"{function}({expression}) AS {quote_identifier(metric.output_alias)}"
                )
            if not select_items:
                raise ValueError("Aggregated join needs a grouping column or metric")
        else:
            select_items = [selection_sql(item) for item in (selections or [])]
            if not select_items:
                raise ValueError("Provide selections or metrics for a join query")

        query = "SELECT " + ", ".join(select_items) + " " + sql
        parameters: list[Any] = []

        filter_clauses = []
        for condition in filters or []:
            if condition.table_alias not in aliases:
                raise KeyError(f"Unknown filter alias: {condition.table_alias}")
            operator_key = condition.operator.strip().upper()
            if operator_key not in _ALLOWED_OPERATORS:
                raise ValueError(f"Unsupported filter operator: {condition.operator}")
            operator = _ALLOWED_OPERATORS[operator_key]
            column_sql = self.engine.quote_column(
                aliases[condition.table_alias], condition.column
            )
            expression = f"{quote_identifier(condition.table_alias)}.{column_sql}"

            if operator in {"IS NULL", "IS NOT NULL"}:
                filter_clauses.append(f"{expression} {operator}")
            elif operator in {"IN", "NOT IN"}:
                if isinstance(condition.value, (str, bytes)):
                    raise TypeError("IN/NOT IN value must be a non-string sequence")
                values = list(condition.value)
                if not values:
                    filter_clauses.append("FALSE" if operator == "IN" else "TRUE")
                else:
                    filter_clauses.append(
                        f"{expression} {operator} ({', '.join('?' for _ in values)})"
                    )
                    parameters.extend(values)
            elif operator == "BETWEEN":
                if not isinstance(condition.value, (tuple, list)) or len(condition.value) != 2:
                    raise ValueError("BETWEEN requires a two-item tuple/list")
                filter_clauses.append(f"{expression} BETWEEN ? AND ?")
                parameters.extend(condition.value)
            else:
                filter_clauses.append(f"{expression} {operator} ?")
                parameters.append(condition.value)

        if filter_clauses:
            query += " WHERE " + " AND ".join(filter_clauses)

        if metric_items and group_items:
            query += " GROUP BY " + ", ".join(
                selection_expression(item) for item in group_items
            )

        if order_by:
            order_parts = []
            for column_alias, direction in order_by:
                direction = direction.upper()
                if direction not in {"ASC", "DESC"}:
                    raise ValueError("ORDER BY direction must be ASC or DESC")
                order_parts.append(f"{quote_identifier(column_alias)} {direction}")
            query += " ORDER BY " + ", ".join(order_parts)

        if limit is not None:
            if not isinstance(limit, int) or limit < 0:
                raise ValueError("limit must be a non-negative integer")
            query += " LIMIT ?"
            parameters.append(limit)

        return query, parameters

    def join(self, base_table: str, **kwargs: Any):
        query, parameters = self.build_join_query(base_table, **kwargs)
        return self.engine.execute_query(query, parameters)

    def fetch_df(self, base_table: str, **kwargs: Any):
        query, parameters = self.build_join_query(base_table, **kwargs)
        return self.engine.fetch_df(query, parameters)
