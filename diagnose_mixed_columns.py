from __future__ import annotations

import argparse
from datetime import date, datetime
from math import ceil
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.loader import DataPackageLoader


def is_temporal(value) -> bool:
    return isinstance(value, (pd.Timestamp, datetime, date, np.datetime64))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find mixed datetime/text columns and repeated header rows in a DataMate package."
    )
    parser.add_argument(
        "--package-dir",
        default="train data",
        help="DataMate package path (default: ./train data)",
    )
    args = parser.parse_args()

    package_dir = Path(args.package_dir).expanduser().resolve()
    package = DataPackageLoader(package_dir).load()

    print(f"Package: {package_dir}")
    print(f"Tables loaded: {len(package.tables)}")
    print("Scanning for mixed datetime/text columns and repeated headers...\n")

    findings = 0

    for table in package.tables:
        df = table.dataframe
        if df.empty or len(df.columns) == 0:
            continue

        # 1. Python datetime values and text values in one object column.
        for column in df.columns:
            series = df[column]
            if not pd.api.types.is_object_dtype(series):
                continue

            values = series.dropna()
            if values.empty:
                continue

            temporal_mask = values.map(is_temporal)
            text_mask = values.map(lambda value: isinstance(value, str))

            if temporal_mask.any() and text_mask.any():
                findings += 1
                sample = values.loc[temporal_mask | text_mask].head(8)
                print("[MIXED DATETIME/TEXT]")
                print(f"  Table:  {table.qualified_name}")
                print(f"  File:   {table.source_file}")
                print(f"  Column: {column!r}")
                print(f"  Types:  {values.map(lambda x: type(x).__name__).value_counts().to_dict()}")
                print("  Sample:")
                for index, value in sample.items():
                    print(f"    row={index!r}, type={type(value).__name__}, value={value!r}")
                print()

            # 2. A cell whose value is exactly the column header.
            header_text = str(column).strip().casefold()
            header_mask = (
                series.astype("string")
                .str.strip()
                .str.casefold()
                .eq(header_text)
            )
            if header_mask.any():
                findings += 1
                indexes = df.index[header_mask].tolist()[:10]
                print("[CELL MATCHES ITS COLUMN HEADER]")
                print(f"  Table:  {table.qualified_name}")
                print(f"  File:   {table.source_file}")
                print(f"  Column: {column!r}")
                print(f"  Rows:   {indexes}")
                print()

        # 3. Detect likely repeated header rows: multiple cells in a row equal
        #    the corresponding DataFrame column names. This only reports; it
        #    does not delete any records.
        if len(df.columns) >= 2:
            matches = pd.Series(0, index=df.index, dtype="int64")
            for column in df.columns:
                mask = (
                    df[column].astype("string")
                    .str.strip()
                    .str.casefold()
                    .eq(str(column).strip().casefold())
                )
                matches += mask.fillna(False).astype("int64")

            threshold = max(2, ceil(len(df.columns) * 0.30))
            likely_header_rows = matches[matches >= threshold]
            if not likely_header_rows.empty:
                findings += len(likely_header_rows)
                print("[LIKELY REPEATED HEADER ROW]")
                print(f"  Table: {table.qualified_name}")
                print(f"  File:  {table.source_file}")
                print(f"  Rows:  {likely_header_rows.index.tolist()[:20]}")
                print(f"  Matching cells per row: {likely_header_rows.head(20).to_dict()}")
                print()

    print("=" * 68)
    print(f"Findings: {findings}")
    if findings == 0:
        print("No mixed datetime/text columns or repeated headers detected by these heuristics.")
    else:
        print("Review the reported source files and rows. This script does not modify data.")

    if package.errors:
        print(f"Loader errors: {len(package.errors)}")
        for error in package.errors[:10]:
            print(error)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
