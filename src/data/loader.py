from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


TABULAR_EXTENSIONS = {".csv", ".xlsx", ".xlsm", ".sqlite", ".sqlite3", ".db"}
MARKDOWN_EXTENSIONS = {".md", ".markdown"}


@dataclass
class LoadedTable:
    """Một bảng đã được đọc từ CSV, Excel hoặc SQLite."""

    business_id: str
    table_name: str
    source_file: str
    source_type: str
    dataframe: pd.DataFrame
    sheet_name: str | None = None
    foreign_keys: list[dict[str, str | None]] = field(default_factory=list)
    cleaning_report: dict[str, Any] = field(default_factory=dict)

    @property
    def qualified_name(self) -> str:
        """Tên định danh tránh trùng bảng giữa các doanh nghiệp."""
        return f"{self.business_id}.{self.table_name}"


@dataclass
class LoadedDocument:
    """Tài liệu Markdown; giữ nội dung để dùng ở phase sau."""

    business_id: str
    file_name: str
    source_file: str
    content: str


@dataclass
class DataPackage:
    package_dir: Path
    tables: list[LoadedTable] = field(default_factory=list)
    documents: list[LoadedDocument] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)


class DataPackageLoader:
    """Đọc một package DataMate.

    Cấu trúc được hỗ trợ:
      package_dir/
        data/biz_101/**/*.(csv|xlsx|xlsm|db|sqlite|sqlite3|md)
        calendar.csv
        rulebook.md

    Nếu truyền trực tiếp thư mục data/, loader vẫn nhận diện các biz_*.
    questions.jsonl và answers.jsonl được cố ý bỏ qua vì chúng là nhãn/câu hỏi
    huấn luyện, không phải bảng nghiệp vụ của doanh nghiệp.
    """

    def __init__(self, package_dir: str | Path):
        self.package_dir = Path(package_dir).expanduser().resolve()
        if not self.package_dir.exists():
            raise FileNotFoundError(f"Package directory not found: {self.package_dir}")
        if not self.package_dir.is_dir():
            raise NotADirectoryError(self.package_dir)

    def load(self) -> DataPackage:
        package = DataPackage(package_dir=self.package_dir)

        # Nếu package có thư mục data/ thì doanh nghiệp nằm trong đó.
        business_root = self.package_dir / "data"
        if not business_root.is_dir():
            business_root = self.package_dir

        business_dirs = sorted(
            p for p in business_root.iterdir()
            if p.is_dir() and p.name.lower().startswith("biz_")
        )

        for business_dir in business_dirs:
            self._load_business_dir(business_dir, package)

        # Đọc các tài nguyên dùng chung nằm trực tiếp ở package root.
        # Chỉ nhận CSV/Excel/SQLite và Markdown; không đọc JSONL.
        if business_root != self.package_dir:
            for path in sorted(self.package_dir.iterdir()):
                if not path.is_file() or path.name.startswith("~$"):
                    continue
                if path.suffix.lower() in TABULAR_EXTENSIONS:
                    self._load_tabular_file(path, business_id="__global__", package=package)
                elif path.suffix.lower() in MARKDOWN_EXTENSIONS:
                    self._load_markdown_file(path, business_id="__global__", package=package)

        return package

    def _load_business_dir(self, business_dir: Path, package: DataPackage) -> None:
        business_id = business_dir.name

        for path in sorted(business_dir.rglob("*")):
            if not path.is_file() or path.name.startswith("~$") or path.name.startswith("."):
                continue

            suffix = path.suffix.lower()
            if suffix in TABULAR_EXTENSIONS:
                self._load_tabular_file(path, business_id, package)
            elif suffix in MARKDOWN_EXTENSIONS:
                self._load_markdown_file(path, business_id, package)
            # Các định dạng khác được bỏ qua có chủ đích ở Phase 1.

    def _load_tabular_file(
        self,
        path: Path,
        business_id: str,
        package: DataPackage,
    ) -> None:
        suffix = path.suffix.lower()
        relative_path = self._relative_path(path)

        try:
            if suffix == ".csv":
                df = self._read_csv(path)
                package.tables.append(
                    LoadedTable(
                        business_id=business_id,
                        table_name=path.stem,
                        source_file=relative_path,
                        source_type="csv",
                        dataframe=df,
                    )
                )

            elif suffix in {".xlsx", ".xlsm"}:
                # Đọc tất cả sheet; mỗi sheet được xem là một bảng riêng.
                excel = pd.ExcelFile(path, engine="openpyxl")
                for sheet in excel.sheet_names:
                    df = pd.read_excel(excel, sheet_name=sheet, engine="openpyxl")
                    package.tables.append(
                        LoadedTable(
                            business_id=business_id,
                            table_name=f"{path.stem}__{sheet}",
                            source_file=relative_path,
                            source_type="excel",
                            dataframe=df,
                            sheet_name=sheet,
                        )
                    )

            elif suffix in {".sqlite", ".sqlite3", ".db"}:
                self._load_sqlite(path, business_id, package)

        except Exception as exc:
            package.errors.append(
                {
                    "source_file": relative_path,
                    "business_id": business_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    @staticmethod
    def _read_csv(path: Path) -> pd.DataFrame:
        """Thử các encoding phổ biến; sep=None giúp nhận diện dấu phân cách."""
        encodings = ["utf-8-sig", "utf-8", "cp1258", "latin1"]
        last_error: Exception | None = None

        for encoding in encodings:
            try:
                return pd.read_csv(
                    path,
                    encoding=encoding,
                    sep=None,
                    engine="python",
                )
            except UnicodeDecodeError as exc:
                last_error = exc

        if last_error:
            raise last_error
        raise RuntimeError(f"Could not read CSV: {path}")

    def _load_sqlite(self, path: Path, business_id: str, package: DataPackage) -> None:
        """Đọc tất cả bảng người dùng và lấy khóa ngoại được khai báo trong DB."""
        connection = sqlite3.connect(path)
        try:
            table_rows = connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()

            for (table_name,) in table_rows:
                # Quote identifier an toàn cho tên bảng có dấu cách/ký tự đặc biệt.
                quoted_name = '"' + str(table_name).replace('"', '""') + '"'
                df = pd.read_sql_query(f"SELECT * FROM {quoted_name}", connection)

                fk_rows = connection.execute(
                    f"PRAGMA foreign_key_list({quoted_name})"
                ).fetchall()

                foreign_keys = []
                for row in fk_rows:
                    # PRAGMA columns: id, seq, table, from, to, on_update, ...
                    foreign_keys.append(
                        {
                            "from_column": row[3],
                            "to_table": row[2],
                            "to_column": row[4],
                        }
                    )

                package.tables.append(
                    LoadedTable(
                        business_id=business_id,
                        table_name=str(table_name),
                        source_file=self._relative_path(path),
                        source_type="sqlite",
                        dataframe=df,
                        foreign_keys=foreign_keys,
                    )
                )
        finally:
            connection.close()

    def _load_markdown_file(
        self,
        path: Path,
        business_id: str,
        package: DataPackage,
    ) -> None:
        try:
            content = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            content = path.read_text(encoding="cp1258")

        package.documents.append(
            LoadedDocument(
                business_id=business_id,
                file_name=path.name,
                source_file=self._relative_path(path),
                content=content,
            )
        )

    def _relative_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.package_dir))
        except ValueError:
            return str(path)
