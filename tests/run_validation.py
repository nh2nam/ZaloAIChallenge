from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import pandas as pd
from pandas.testing import assert_frame_equal

# Allow running this file directly from the project root or tests/.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.executor import (  # noqa: E402
    DuckDBEngine,
    FilterCondition,
    JoinHandler,
    JoinMetric,
    JoinSpec,
    Metric,
    QueryBuilder,
    Selection,
    aggregate,
    calculate_change,
    percentage_of_total,
    period_over_period,
    rank_groups,
    rank_rows,
)


def make_demo_data():
    customers = pd.DataFrame(
        [
            ("C001", "An", "North"),
            ("C002", "Bao", "South"),
            ("C003", "Chi", "North"),
            ("C004", "Dung", "South"),
            ("C005", "En", "East"),  # no orders: exercises LEFT JOIN
        ],
        columns=["customer_id", "customer_name", "region"],
    )

    products = pd.DataFrame(
        [
            ("P01", "Notebook", "Stationery"),
            ("P02", "Pen", "Stationery"),
            ("P03", "Mug", "Home"),
            ("P04", "Bag", "Accessories"),
        ],
        columns=["product_id", "product_name", "category"],
    )

    orders = pd.DataFrame(
        [
            ("O001", "C001", "2026-01-05"),
            ("O002", "C002", "2026-01-15"),
            ("O003", "C001", "2026-02-03"),
            ("O004", "C003", "2026-02-17"),
            ("O005", "C004", "2026-03-01"),
            ("O006", "C002", "2026-03-12"),
        ],
        columns=["order_id", "customer_id", "order_date"],
    )
    orders["order_date"] = pd.to_datetime(orders["order_date"])

    order_items = pd.DataFrame(
        [
            ("I001", "O001", "P01", 2, 10000),
            ("I002", "O001", "P02", 3, 5000),
            ("I003", "O002", "P03", 1, 20000),
            ("I004", "O003", "P04", 1, 50000),
            ("I005", "O004", "P01", 1, 10000),
            ("I006", "O004", "P03", 2, 20000),
            ("I007", "O005", "P02", 5, 5000),
            ("I008", "O006", "P01", 3, 10000),
        ],
        columns=["item_id", "order_id", "product_id", "quantity", "unit_price"],
    )
    order_items["line_total"] = order_items["quantity"] * order_items["unit_price"]
    order_items = order_items.merge(
        orders[["order_id", "order_date"]], on="order_id", how="left"
    )

    return customers, products, orders, order_items


def assert_scalar(actual, expected, *, tolerance=1e-8):
    if isinstance(expected, (int, float)):
        assert abs(float(actual) - float(expected)) <= tolerance, (actual, expected)
    else:
        assert actual == expected, (actual, expected)


def assert_frames(actual, expected, *, sort_by):
    actual = actual[expected.columns].sort_values(sort_by).reset_index(drop=True)
    expected = expected.sort_values(sort_by).reset_index(drop=True)
    assert_frame_equal(
        actual,
        expected,
        check_dtype=False,
        check_exact=False,
        atol=1e-8,
        rtol=1e-8,
    )


def main():
    customers, products, orders, order_items = make_demo_data()
    checks: list[tuple[str, Callable[[], None]]] = []

    with DuckDBEngine() as engine:
        engine.register_dataframe("biz_demo.customers", customers)
        engine.register_dataframe("biz_demo.products", products)
        engine.register_dataframe("biz_demo.orders", orders)
        engine.register_dataframe("biz_demo.order_items", order_items)

        # 1. Count customer rows.
        def check_01():
            result = engine.fetch_df(
                f"SELECT COUNT(*) AS n FROM {engine.sql_table('biz_demo.customers')}"
            )
            assert_scalar(result.loc[0, "n"], len(customers))

        checks.append(("01 Count customers", check_01))

        # 2. Query Builder: parameterized filter + selected columns.
        def check_02():
            actual = QueryBuilder(engine).select(
                "biz_demo.orders",
                columns=["order_id", "customer_id"],
                filters=[FilterCondition("customer_id", "=", "C002")],
                order_by=[("order_id", "ASC")],
            )["result"]
            expected = (
                orders.loc[orders["customer_id"] == "C002", ["order_id", "customer_id"]]
                .sort_values("order_id").reset_index(drop=True)
            )
            assert_frames(actual, expected, sort_by=["order_id"])

        checks.append(("02 Query Builder SELECT and parameterized filter", check_02))

        # 3. Count distinct customers who placed orders.
        def check_03():
            result = aggregate(
                engine,
                "biz_demo.orders",
                {"active_customers": ("COUNT_DISTINCT", "customer_id")},
            )["result"]
            expected = orders["customer_id"].nunique()
            assert_scalar(result.loc[0, "active_customers"], expected)

        checks.append(("03 Distinct ordering customers", check_03))

        # 4. Sum all line totals.
        def check_04():
            result = aggregate(
                engine,
                "biz_demo.order_items",
                {"revenue": ("SUM", "line_total")},
            )["result"]
            assert_scalar(result.loc[0, "revenue"], order_items["line_total"].sum())

        checks.append(("04 Total revenue", check_04))

        # 5. Average line total.
        def check_05():
            result = aggregate(
                engine,
                "biz_demo.order_items",
                {"average_line": ("AVG", "line_total")},
            )["result"]
            assert_scalar(result.loc[0, "average_line"], order_items["line_total"].mean())

        checks.append(("05 Average line total", check_05))

        # 6. Minimum line total.
        def check_06():
            result = aggregate(
                engine,
                "biz_demo.order_items",
                {"minimum": ("MIN", "line_total")},
            )["result"]
            assert_scalar(result.loc[0, "minimum"], order_items["line_total"].min())

        checks.append(("06 Minimum line total", check_06))

        # 7. Maximum line total.
        def check_07():
            result = aggregate(
                engine,
                "biz_demo.order_items",
                {"maximum": ("MAX", "line_total")},
            )["result"]
            assert_scalar(result.loc[0, "maximum"], order_items["line_total"].max())

        checks.append(("07 Maximum line total", check_07))

        # 8. Revenue by product.
        def check_08():
            actual = aggregate(
                engine,
                "biz_demo.order_items",
                {"revenue": ("SUM", "line_total")},
                group_by=["product_id"],
                order_by=[("product_id", "ASC")],
            )["result"]
            expected = (
                order_items.groupby("product_id", as_index=False)["line_total"]
                .sum().rename(columns={"line_total": "revenue"})
            )
            assert_frames(actual, expected, sort_by=["product_id"])

        checks.append(("08 Aggregation by product", check_08))

        # 9. LEFT JOIN: customers with zero orders must remain in result.
        def check_09():
            joins = JoinHandler(engine)
            actual = joins.fetch_df(
                "biz_demo.customers",
                base_alias="c",
                joins=[
                    JoinSpec(
                        table="biz_demo.orders",
                        alias="o",
                        left_alias="c",
                        left_column="customer_id",
                        right_column="customer_id",
                        join_type="LEFT",
                    )
                ],
                group_by=[
                    Selection("c", "customer_id"),
                    Selection("c", "customer_name"),
                ],
                metrics=[
                    JoinMetric("order_count", "COUNT", Selection("o", "order_id"))
                ],
                order_by=[("customer_id", "ASC")],
            )
            expected = customers.merge(orders, on="customer_id", how="left")
            expected = (
                expected.groupby(["customer_id", "customer_name"], as_index=False)
                .agg(order_count=("order_id", "count"))
            )
            assert_frames(actual, expected, sort_by=["customer_id"])

        checks.append(("09 LEFT JOIN order counts", check_09))

        # 10. Multi-table join: revenue by customer region.
        def check_10():
            joins = JoinHandler(engine)
            actual = joins.fetch_df(
                "biz_demo.orders",
                base_alias="o",
                joins=[
                    JoinSpec("biz_demo.customers", "c", "o", "customer_id", "customer_id"),
                    JoinSpec("biz_demo.order_items", "i", "o", "order_id", "order_id"),
                ],
                group_by=[Selection("c", "region")],
                metrics=[JoinMetric("revenue", "SUM", Selection("i", "line_total"))],
                order_by=[("region", "ASC")],
            )
            expected_base = (
                orders.merge(customers, on="customer_id")
                .merge(order_items, on=["order_id", "order_date"])
            )
            expected = (
                expected_base.groupby("region", as_index=False)["line_total"]
                .sum().rename(columns={"line_total": "revenue"})
            )
            assert_frames(actual, expected, sort_by=["region"])

        checks.append(("10 Three-table join revenue by region", check_10))

        # 11. Top 3 products by revenue (group ranking).
        def check_11():
            actual = rank_groups(
                engine,
                "biz_demo.order_items",
                group_by=["product_id"],
                metric_column="line_total",
                aggregate_function="SUM",
                k=3,
                direction="top",
            )["result"]
            expected = (
                order_items.groupby("product_id", as_index=False)["line_total"]
                .sum().rename(columns={"line_total": "metric_value"})
                .sort_values(["metric_value", "product_id"], ascending=[False, True])
                .head(3)
            )
            assert_frames(actual, expected, sort_by=["product_id"])
            # Also check ordered values explicitly because a sort in assert_frames is neutral.
            assert actual["product_id"].tolist() == expected["product_id"].tolist()

        checks.append(("11 Top-3 products by revenue", check_11))

        # 12. Bottom 2 products by revenue.
        def check_12():
            actual = rank_groups(
                engine,
                "biz_demo.order_items",
                group_by=["product_id"],
                metric_column="line_total",
                aggregate_function="SUM",
                k=2,
                direction="bottom",
            )["result"]
            expected = (
                order_items.groupby("product_id", as_index=False)["line_total"]
                .sum().rename(columns={"line_total": "metric_value"})
                .sort_values(["metric_value", "product_id"], ascending=[True, True])
                .head(2)
            )
            assert actual["product_id"].tolist() == expected["product_id"].tolist()
            assert_frames(actual, expected, sort_by=["product_id"])

        checks.append(("12 Bottom-2 products by revenue", check_12))

        # 13. Top 3 raw transaction lines.
        def check_13():
            actual = rank_rows(
                engine,
                "biz_demo.order_items",
                "line_total",
                3,
                direction="top",
                columns=["item_id", "line_total"],
                tie_breakers=[("item_id", "ASC")],
            )["result"]
            expected = order_items[["item_id", "line_total"]].sort_values(
                ["line_total", "item_id"], ascending=[False, True]
            ).head(3).reset_index(drop=True)
            assert_frames(actual, expected, sort_by=["item_id"])
            assert actual["item_id"].tolist() == expected["item_id"].tolist()

        checks.append(("13 Top-3 raw line items", check_13))

        # 14. Monthly revenue and previous-period values.
        def check_14():
            actual = period_over_period(
                engine,
                "biz_demo.order_items",
                date_column="order_date",
                value_column="line_total",
                period="month",
                aggregation="SUM",
            )
            expected = order_items.assign(
                period=order_items["order_date"].dt.to_period("M").dt.to_timestamp()
            ).groupby("period")["line_total"].sum().sort_index()
            assert actual["current_value"].tolist() == expected.tolist()
            assert pd.to_datetime(actual["period"]).dt.to_period("M").tolist() == expected.index.to_period("M").tolist()

        checks.append(("14 Monthly revenue trend", check_14))

        # 15. Number of orders per month.
        def check_15():
            actual = engine.fetch_df(
                f"""
                SELECT DATE_TRUNC('month', order_date) AS month,
                       COUNT(*) AS order_count
                FROM {engine.sql_table('biz_demo.orders')}
                GROUP BY 1 ORDER BY 1
                """
            )
            expected = orders.assign(
                month=orders["order_date"].dt.to_period("M").dt.to_timestamp()
            ).groupby("month").size().rename("order_count").reset_index()
            assert_frames(actual, expected, sort_by=["month"])

        checks.append(("15 Monthly order counts", check_15))

        # 16. Percentage share of each product's revenue.
        def check_16():
            actual = percentage_of_total(
                engine,
                "biz_demo.order_items",
                group_by="product_id",
                value_column="line_total",
            )
            expected = (
                order_items.groupby("product_id")["line_total"].sum().sort_index()
            )
            expected_df = expected.rename("total_value").reset_index()
            expected_df["percentage"] = expected_df["total_value"] / expected_df["total_value"].sum() * 100
            expected_df = expected_df.rename(columns={"product_id": "group_value"})
            assert_frames(actual, expected_df, sort_by=["group_value"])

        checks.append(("16 Product revenue percentage of total", check_16))

        # 17. Date range filter: Jan + Feb revenue.
        def check_17():
            result = aggregate(
                engine,
                "biz_demo.order_items",
                {"revenue": ("SUM", "line_total")},
                filters=[
                    FilterCondition(
                        "order_date",
                        "BETWEEN",
                        (pd.Timestamp("2026-01-01"), pd.Timestamp("2026-02-28")),
                    )
                ],
            )["result"]
            expected = order_items.loc[
                order_items["order_date"].between(
                    pd.Timestamp("2026-01-01"), pd.Timestamp("2026-02-28")
                ),
                "line_total",
            ].sum()
            assert_scalar(result.loc[0, "revenue"], expected)

        checks.append(("17 Date-range filter and aggregation", check_17))

        # 18. Filter with a comparison operator.
        def check_18():
            result = aggregate(
                engine,
                "biz_demo.order_items",
                {"line_count": ("COUNT", "*")},
                filters=[FilterCondition("line_total", ">", 30000)],
            )["result"]
            expected = int((order_items["line_total"] > 30000).sum())
            assert_scalar(result.loc[0, "line_count"], expected)

        checks.append(("18 Parameterized numeric filter", check_18))

        # 19. Difference and growth from Jan to Feb.
        def check_19():
            monthly = order_items.assign(
                month=order_items["order_date"].dt.to_period("M")
            ).groupby("month")["line_total"].sum()
            change = calculate_change(monthly.loc[pd.Period("2026-02", freq="M")],
                                      monthly.loc[pd.Period("2026-01", freq="M")])
            expected_difference = monthly.loc[pd.Period("2026-02", freq="M")] - monthly.loc[pd.Period("2026-01", freq="M")]
            expected_growth = expected_difference / monthly.loc[pd.Period("2026-01", freq="M")] * 100
            assert_scalar(change["absolute_change"], expected_difference)
            assert_scalar(change["growth_pct"], expected_growth)
            assert_scalar(change["ratio"], monthly.loc[pd.Period("2026-02", freq="M")] / monthly.loc[pd.Period("2026-01", freq="M")])

        checks.append(("19 Absolute change and growth rate", check_19))

        # 20. Three-table join: revenue by product category.
        def check_20():
            joins = JoinHandler(engine)
            actual = joins.fetch_df(
                "biz_demo.order_items",
                base_alias="i",
                joins=[
                    JoinSpec("biz_demo.products", "p", "i", "product_id", "product_id")
                ],
                group_by=[Selection("p", "category")],
                metrics=[JoinMetric("revenue", "SUM", Selection("i", "line_total"))],
                order_by=[("category", "ASC")],
            )
            expected_base = order_items.merge(products, on="product_id")
            expected = (
                expected_base.groupby("category", as_index=False)["line_total"]
                .sum().rename(columns={"line_total": "revenue"})
            )
            assert_frames(actual, expected, sort_by=["category"])

        checks.append(("20 Join and aggregate by product category", check_20))

        passed = 0
        failed = []
        print("\n========== PHASE 2 VALIDATION ==========")
        for name, check in checks:
            try:
                check()
                passed += 1
                print(f"[PASS] {name}")
            except Exception as exc:
                failed.append((name, exc))
                print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")

        print("\n========== RESULT ==========")
        print(f"Passed: {passed}/{len(checks)}")
        print(f"Failed: {len(failed)}")

        if failed:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
