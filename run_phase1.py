from __future__ import annotations

from pathlib import Path

from src.data.cleaner import clean_dataframe
from src.data.inspector import inspect_package, show_table_preview
from src.data.loader import DataPackageLoader
from src.data.schema import build_schema, save_schema


# Sửa đường dẫn này nếu folder train data nằm ở nơi khác.
PACKAGE_DIR = Path("train data")
OUTPUT_DIR = Path("outputs")


def main() -> None:
    print(f"Loading package: {PACKAGE_DIR.resolve()}")
    package = DataPackageLoader(PACKAGE_DIR).load()

    print("\n========== LOADING SUMMARY ==========")
    print("Tables loaded:", len(package.tables))
    print("Markdown documents:", len(package.documents))
    print("Load errors:", len(package.errors))

    # Clean từng bảng nhưng không tự ý điền missing values.
    for table in package.tables:
        cleaned_df, cleaning_report = clean_dataframe(table.dataframe)
        table.dataframe = cleaned_df
        table.cleaning_report = cleaning_report

    # Hiển thị một vài bảng mẫu để kiểm tra bằng mắt.
    for table in package.tables[:5]:
        show_table_preview(table, rows=5)

    # Metadata sau khi clean.
    table_metadata = inspect_package(package.tables, sample_size=3)
    schema = build_schema(package, table_metadata)

    output_path = save_schema(schema, OUTPUT_DIR / "schema.json")

    print("\n========== PHASE 1 RESULT ==========")
    print("Businesses:", schema["summary"]["business_count"])
    print("Tables:", schema["summary"]["table_count"])
    print("Documents:", schema["summary"]["document_count"])
    print("Relationships:", len(schema["relationships"]))
    print("Load errors:", schema["summary"]["load_error_count"])
    print("Schema saved to:", output_path.resolve())

    if package.errors:
        print("\nSome files could not be loaded. See load_errors in schema.json")
        for error in package.errors[:10]:
            print("-", error)


if __name__ == "__main__":
    main()
