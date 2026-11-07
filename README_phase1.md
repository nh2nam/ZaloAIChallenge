# DataMate Phase 1 — Data Processing Engine

Starter implementation for loading, cleaning, inspecting and exporting schema metadata from a DataMate-style package.

## Expected input layout

```text
project/
├── train data/
│   ├── data/
│   │   ├── biz_101/
│   │   │   ├── customers.csv
│   │   │   ├── orders.xlsx
│   │   │   └── README.md
│   │   └── biz_102/
│   │       └── company.db
│   ├── calendar.csv
│   ├── rulebook.md
│   ├── questions.jsonl
│   └── answers.jsonl
├── src/
│   └── data/
│       ├── loader.py
│       ├── inspector.py
│       ├── cleaner.py
│       └── schema.py
├── outputs/
└── run_phase1.py
```

`questions.jsonl` and `answers.jsonl` are intentionally not loaded as business tables. The loader reads business files under `data/biz_*`, plus package-level `calendar.csv` and `rulebook.md`.

## 1. Create environment and install packages

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install pandas openpyxl
```

`sqlite3` is part of Python's standard library, so it does not need a separate pip install.

## 2. Put the real data beside the code

The folder `train data/` should be at the same level as `run_phase1.py`. If it is somewhere else, edit `PACKAGE_DIR` in `run_phase1.py`.

## 3. Run

From the project root:

```bash
python run_phase1.py
```

The script prints loading stats and some data previews, then writes:

```text
outputs/schema.json
```

## What each module does

- `loader.py`: discovers business folders; reads CSV, every sheet of XLSX/XLSM, every user table in SQLite; reads Markdown as documents; records failed files without crashing the entire package.
- `cleaner.py`: trims strings, normalizes common missing tokens, cautiously converts date/numeric columns. It never fills missing values unless `fill_values` is explicitly passed.
- `inspector.py`: records row/column counts, semantic dtype, missing percentage, unique count and sample values.
- `schema.py`: combines metadata, documents and relationships into JSON. SQLite foreign keys are marked verified; name-based CSV/Excel relationships are only candidates.

## Important safety against data corruption

Do not replace missing numeric values with zero automatically. A missing amount is not necessarily a zero amount. Also, identifier-like columns (`customer_id`, `phone`, `sku`, etc.) are protected from numeric conversion because leading zeros may matter.

## First validation checklist

1. `Tables loaded` is greater than zero.
2. `calendar.csv` appears under `global_tables` in `schema.json`.
3. Markdown files appear under `documents`.
4. Each Excel sheet appears as a separate table.
5. `row_count` and `columns` look reasonable for a few manually inspected files.
6. `load_errors` is empty, or every error has been investigated.
7. Any relationship with `verified: false` is treated as a candidate, not a confirmed join key.

## Current scope / limitations

- CSV, XLSX, XLSM, SQLite/DB and Markdown are supported.
- Legacy `.xls` is not included by default; it needs an extra Excel reader dependency.
- CSV delimiter detection is automatic, but unusual files may need an explicit separator.
- Relationships from CSV/Excel cannot be known with certainty from file structure alone. This starter marks name-based matches as unverified candidates.
- The code loads tables into memory. Very large files may need chunked loading or DuckDB in the next phase.
