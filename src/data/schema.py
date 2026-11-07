from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .loader import DataPackage, LoadedTable


def _quote_table_name(table_name: str) -> str:
    return table_name.strip().lower()


def infer_relationship_candidates(tables: list[LoadedTable]) -> list[dict[str, Any]]:
    """Tạo candidate relationship từ tên cột *_id.

    Đây chỉ là heuristic cho CSV/Excel, KHÔNG được xem là foreign key đã xác nhận.
    Quan hệ được khai báo trong SQLite được lấy riêng từ PRAGMA foreign_key_list.
    """
    relationships: list[dict[str, Any]] = []

    # Quan hệ khai báo rõ trong SQLite.
    for source in tables:
        for fk in source.foreign_keys:
            target_table = str(fk.get("to_table") or "")
            target_column = fk.get("to_column")
            relationships.append(
                {
                    "source_table": source.qualified_name,
                    "source_column": fk.get("from_column"),
                    "target_table": f"{source.business_id}.{target_table}",
                    "target_column": target_column,
                    "relationship_type": "foreign_key",
                    "evidence": "sqlite_constraint",
                    "verified": True,
                }
            )

    # Chỉ dò quan hệ tên cột trong cùng một doanh nghiệp.
    for source in tables:
        source_columns = {str(c).lower() for c in source.dataframe.columns}
        for column in source_columns:
            if not column.endswith("_id") or column in {"id", "business_id"}:
                continue

            prefix = column[:-3]
            possible_names = {
                prefix,
                prefix + "s",
                prefix + "es",
            }

            candidates = [
                target for target in tables
                if target.business_id == source.business_id
                and target is not source
                and _quote_table_name(target.table_name) in possible_names
            ]

            if len(candidates) != 1:
                continue

            target = candidates[0]
            target_columns = {str(c).lower() for c in target.dataframe.columns}
            target_key = column if column in target_columns else ("id" if "id" in target_columns else None)
            if target_key is None:
                continue

            relationships.append(
                {
                    "source_table": source.qualified_name,
                    "source_column": column,
                    "target_table": target.qualified_name,
                    "target_column": target_key,
                    "relationship_type": "candidate_many_to_one",
                    "evidence": "column_and_table_name_heuristic",
                    "verified": False,
                }
            )

    # Khử trùng lặp khi SQLite FK và heuristic cùng phát hiện một quan hệ.
    unique = {}
    for relation in relationships:
        key = (
            relation["source_table"], relation["source_column"],
            relation["target_table"], relation["target_column"],
        )
        if key not in unique or relation["verified"]:
            unique[key] = relation

    return list(unique.values())


def build_schema(
    package: DataPackage,
    table_metadata: list[dict[str, Any]],
) -> dict[str, Any]:
    business_ids = sorted({t.business_id for t in package.tables if t.business_id != "__global__"} |
                          {d.business_id for d in package.documents if d.business_id != "__global__"})

    businesses = []
    for business_id in business_ids:
        businesses.append(
            {
                "business_id": business_id,
                "tables": [t.qualified_name for t in package.tables if t.business_id == business_id],
                "documents": [d.source_file for d in package.documents if d.business_id == business_id],
            }
        )

    document_metadata = [
        {
            "business_id": doc.business_id,
            "file_name": doc.file_name,
            "source_file": doc.source_file,
            "character_count": len(doc.content),
        }
        for doc in package.documents
    ]

    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "package_dir": str(package.package_dir),
        "summary": {
            "business_count": len(business_ids),
            "table_count": len(package.tables),
            "document_count": len(package.documents),
            "load_error_count": len(package.errors),
        },
        "businesses": businesses,
        "tables": table_metadata,
        "global_tables": [t.qualified_name for t in package.tables if t.business_id == "__global__"],
        "documents": document_metadata,
        "relationships": infer_relationship_candidates(package.tables),
        "load_errors": package.errors,
    }


def save_schema(schema: dict[str, Any], output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2, default=str)
    return output_path
