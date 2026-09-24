"""Import an exported ClauseGuide SQLite database and its files into MongoDB.

Run from backend/ after setting MONGODB_URI. The default mode validates the
source without writing. --apply writes only to csi.clauseguide_ai and can be
re-run safely after an interruption.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.sql.sqltypes import Boolean, DateTime, Enum, JSON

from app.core.mongo import _collection, put_file_chunk
from app.models import chat, clause, document, evaluation, markdown, report, user  # noqa: F401
from app.models.base import Base


def locate_file(old_path: str, files_root: Path | None, subdir: str) -> Path | None:
    original = Path(old_path)
    candidates = [original]
    if files_root:
        candidates += [
            files_root / subdir / original.name,
            files_root / original.name,
        ]
    return next((path for path in candidates if path.is_file()), None)


def convert_row(table: Any, row: sqlite3.Row) -> dict[str, Any]:
    values: dict[str, Any] = {}
    keys = set(row.keys())
    for column in table.columns:
        value = row[column.name] if column.name in keys else None
        if value is not None:
            if isinstance(column.type, DateTime):
                value = datetime.fromisoformat(value)
                if value.tzinfo is None:
                    value = value.replace(tzinfo=UTC)
            elif isinstance(column.type, JSON):
                value = json.loads(value)
            elif isinstance(column.type, Boolean):
                value = bool(value)
            elif isinstance(column.type, Enum):
                value = str(value)
        values[column.name] = value
    return values


async def apply_rows(
    records: list[tuple[str, dict[str, Any]]],
    files: list[tuple[str, Path]],
) -> None:
    collection = _collection()
    inserted = 0
    for kind, values in records:
        result = await collection.update_one(
            {"_id": f"{kind}:{values['id']}"},
            {"$setOnInsert": {"kind": kind, "version": 1, **values}},
            upsert=True,
        )
        inserted += bool(result.upserted_id)
    for table in Base.metadata.sorted_tables:
        ids = [
            values["id"]
            for kind, values in records
            if kind == table.name and isinstance(values["id"], int)
        ]
        if ids:
            await collection.update_one(
                {"_id": f"_counter:{table.name}"},
                {"$max": {"value": max(ids)}},
                upsert=True,
            )
    for file_id, path in files:
        with path.open("rb") as source:
            index = 0
            while chunk := source.read(2 * 1024 * 1024):
                await put_file_chunk(file_id, index, chunk)
                index += 1
    print(f"Imported {inserted} new records; verified/stored {len(files)} files.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path, help="Exported SQLite .db file")
    parser.add_argument(
        "--files-root",
        type=Path,
        help="Directory containing exported uploads/ and reports/ subdirectories",
    )
    parser.add_argument("--apply", action="store_true", help="Write after validation")
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error("SQLite database file not found")

    source = sqlite3.connect(f"file:{args.database.resolve()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    available = {
        row["name"] for row in source.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    records: list[tuple[str, dict[str, Any]]] = []
    files: list[tuple[str, Path]] = []
    missing: list[str] = []
    counts: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        if table.name not in available:
            continue
        rows = source.execute(f'SELECT * FROM "{table.name}"').fetchall()
        counts[table.name] = len(rows)
        for row in rows:
            values = convert_row(table, row)
            if table.name in {"documents", "reports"}:
                subdir = "uploads" if table.name == "documents" else "reports"
                path = locate_file(values["file_path"], args.files_root, subdir)
                if path is None:
                    missing.append(f"{table.name}:{values['id']} ({Path(values['file_path']).name})")
                else:
                    files.append((str(values["id"]), path))
                values["file_path"] = f"mongo:{values['id']}"
            records.append((table.name, values))
    source.close()
    print("Rows:", ", ".join(f"{key}={value}" for key, value in counts.items()))
    print(f"Files found: {len(files)}")
    if missing:
        for item in missing[:20]:
            print(f"Missing file: {item}")
        raise SystemExit(f"Stopped: {len(missing)} referenced files are missing")
    if args.apply:
        asyncio.run(apply_rows(records, files))
    else:
        print("Validation only. Add --apply to import.")


if __name__ == "__main__":
    main()
