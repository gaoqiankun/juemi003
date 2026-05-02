#!/usr/bin/env python3
from __future__ import annotations

# One-off migration usage:
# 1) Optional: export DATABASE_PATH=/path/to/cubie3d.db
# 2) Optional: export HF_HOME=/path/to/hf/cache
# 3) Dry run:  python scripts/migrate_resolved_path.py --dry-run
# 4) Apply:    python scripts/migrate_resolved_path.py
import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass
from typing import Iterable

DEFAULT_DATABASE_PATH = "/data/cubie3d.db"


@dataclass(frozen=True)
class ModelRecord:
    model_id: str
    model_path: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill model_definitions.resolved_path from local Hugging Face cache."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and print results without writing to SQLite.",
    )
    return parser.parse_args()


def get_database_path() -> str:
    return os.getenv("DATABASE_PATH", DEFAULT_DATABASE_PATH)


def fetch_unresolved_models(conn: sqlite3.Connection) -> Iterable[ModelRecord]:
    cursor = conn.execute(
        """
        SELECT id, model_path
        FROM model_definitions
        WHERE resolved_path IS NULL
        ORDER BY created_at, id
        """
    )
    rows = cursor.fetchall()
    for row in rows:
        yield ModelRecord(model_id=str(row["id"]), model_path=str(row["model_path"]))


def resolve_from_local_hf_cache(model_path: str) -> str | None:
    try:
        from huggingface_hub import snapshot_download
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "huggingface_hub is required. Install it before running this script."
        ) from exc

    try:
        return snapshot_download(repo_id=model_path, local_files_only=True)
    except Exception:
        return None


def run_migration(db_path: str, dry_run: bool) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    processed = 0
    updated = 0
    not_found = 0

    try:
        for record in fetch_unresolved_models(conn):
            processed += 1
            resolved_path = resolve_from_local_hf_cache(record.model_path)

            if resolved_path is None:
                not_found += 1
                print(
                    f"[WARN] local HF cache not found for {record.model_id} "
                    f"(repo_id={record.model_path}); skip"
                )
                print(f"{record.model_id} / NOT FOUND")
                continue

            print(f"{record.model_id} / {resolved_path}")
            if not dry_run:
                conn.execute(
                    "UPDATE model_definitions SET resolved_path = ? WHERE id = ?",
                    (resolved_path, record.model_id),
                )
                updated += 1

        if not dry_run:
            conn.commit()
    finally:
        conn.close()

    mode_label = "DRY-RUN" if dry_run else "APPLY"
    print(
        f"[{mode_label}] processed={processed} updated={updated} not_found={not_found}"
    )
    return 0


def main() -> int:
    args = parse_args()
    db_path = get_database_path()
    try:
        return run_migration(db_path=db_path, dry_run=args.dry_run)
    except sqlite3.Error as exc:
        print(f"[ERROR] sqlite error for {db_path}: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
