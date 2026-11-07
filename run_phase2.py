from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.data.cleaner import clean_dataframe
from src.data.loader import DataPackageLoader
from src.executor import DuckDBEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load a DataMate package into DuckDB and create a table inventory."
    )
    parser.add_argument(
        "--package-dir",
        default="train data",
        help="Path to the DataMate package (default: ./train data)",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs",
        help="Directory for Phase 2 reports (default: ./outputs)",
    )
    parser.add_argument(
        "--database",
        default=":memory:",
        help="DuckDB database path, or :memory: (default: :memory:)",
    )
    parser.add_argument(
        "--preview-rows",
        type=int,
        default=5,
        help="Rows to show for the first 3 tables (default: 5)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    package_dir = Path(args.package_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading DataMate package: {package_dir}")
    package = DataPackageLoader(package_dir).load()

    print("\n========== PHASE 1 LOADER SUMMARY ==========")
    print("Tables discovered:", len(package.tables))
    print("Markdown documents:", len(package.documents))
    print("Load errors:", len(package.errors))

    # Follow the same conservative cleaning step as run_phase1.py before
    # registering the DataFrames in DuckDB. Missing values are not filled.
    for table in package.tables:
        cleaned_df, cleaning_report = clean_dataframe(table.dataframe)
        table.dataframe = cleaned_df
        table.cleaning_report = cleaning_report

        # Báo cáo các giá trị không parse được trong cột ngày. Ví dụ thường gặp
        # là file Excel/CSV có lặp lại dòng header ở giữa dữ liệu.
        invalid_dates = cleaning_report.get("date_invalid_examples", {})
        for column, examples in invalid_dates.items():
            print(
                f"[DATE CLEANING] {table.qualified_name} | {table.source_file} "
                f"| column={column!r} | invalid examples={examples}"
            )

    if not package.tables:
        print("No tabular data was loaded. Check the package folder and file types.")
        return 1

    with DuckDBEngine(args.database) as engine:
        registrations = engine.register_package(package, replace=True)

        print("\n========== DUCKDB REGISTRATION ==========")
        print("Registered tables:", len(registrations))
        print("DuckDB database:", args.database)

        inventory = engine.list_tables()
        inventory_rows = []

        for item in inventory:
            count_df = engine.fetch_df(
                f"SELECT COUNT(*) AS row_count FROM {item['sql_name']}"
            )
            actual_row_count = int(count_df.loc[0, "row_count"])
            row = {**item, "row_count_in_duckdb": actual_row_count}
            inventory_rows.append(row)
            print(
                f"- {item['qualified_name']:<38} "
                f"rows={actual_row_count:<10} columns={item['column_count']}"
            )

        # Show a small preview of the first three registered tables.
        print("\n========== DATA PREVIEW ==========")
        for item in inventory[:3]:
            print(f"\n{item['qualified_name']} ({item['source_file']})")
            preview = engine.fetch_df(
                f"SELECT * FROM {item['sql_name']} LIMIT ?",
                [max(0, args.preview_rows)],
            )
            print(preview.to_string(index=False))

        inventory_df = pd.DataFrame(inventory_rows)
        inventory_path = output_dir / "phase2_table_inventory.csv"
        inventory_df.to_csv(inventory_path, index=False, encoding="utf-8-sig")

        summary = {
            "package_dir": str(package_dir),
            "database": args.database,
            "registered_table_count": len(registrations),
            "markdown_document_count": len(package.documents),
            "loader_error_count": len(package.errors),
            "tables": inventory_rows,
            "loader_errors": package.errors,
        }
        summary_path = output_dir / "phase2_run_summary.json"
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    print("\n========== PHASE 2 RESULT ==========")
    print("Tables registered in DuckDB:", len(registrations))
    print("Inventory saved to:", inventory_path)
    print("Run summary saved to:", summary_path)
    if package.errors:
        print("Some files could not be read by the Phase 1 loader; inspect loader_errors in the summary.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
