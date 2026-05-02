#!/usr/bin/env python3
# DEPRECATED: superseded by storage.dep_store.ensure_schema automatic migration.
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

DEFAULT_DATABASE_PATH = "./data/app.sqlite3"
MODEL_WEIGHT_GLOBS = (
    "*.safetensors",
    "pytorch_model*.bin",
    "model.ckpt*",
    "tf_model.h5",
    "flax_model.msgpack",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill dep_cache from local Hugging Face cache.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing SQLite.")
    parser.add_argument("--database-path", default=os.getenv("DATABASE_PATH", DEFAULT_DATABASE_PATH), help="SQLite path (default: env DATABASE_PATH or ./data/app.sqlite3).")
    return parser.parse_args()


def provider_dependencies(provider_type: str) -> list[tuple[str, str]]:
    try:
        from gen3d.model.providers.hunyuan3d.provider import Hunyuan3DProvider
        from gen3d.model.providers.step1x3d.provider import Step1X3DProvider
        from gen3d.model.providers.trellis2.provider import Trellis2Provider
    except Exception as exc:
        raise RuntimeError(f"failed to import providers: {exc}") from exc

    provider_cls = {"trellis2": Trellis2Provider, "hunyuan3d": Hunyuan3DProvider, "step1x3d": Step1X3DProvider}.get(provider_type.strip().lower())
    if provider_cls is None:
        return []

    deps: list[tuple[str, str]] = []
    for dep in provider_cls.dependencies() or []:
        dep_id = str(getattr(dep, "dep_id", "") or "").strip()
        hf_repo_id = str(getattr(dep, "hf_repo_id", "") or "").strip()
        if dep_id and hf_repo_id:
            deps.append((dep_id, hf_repo_id))
    return deps


def resolve_local_snapshot(hf_repo_id: str) -> str | None:
    try:
        from huggingface_hub import snapshot_download
    except ModuleNotFoundError as exc:
        raise RuntimeError("huggingface_hub is required.") from exc

    try:
        return snapshot_download(repo_id=hf_repo_id, local_files_only=True)
    except Exception:
        return None


def snapshot_has_model_weights(snapshot_path: str | None) -> bool:
    if not snapshot_path:
        return False
    candidate = Path(snapshot_path).expanduser()
    if not candidate.exists() or not candidate.is_dir():
        return False
    for pattern in MODEL_WEIGHT_GLOBS:
        try:
            next(candidate.rglob(pattern))
        except StopIteration:
            continue
        return True
    return False


def migrate(conn: sqlite3.Connection, dry_run: bool) -> tuple[int, int, int]:
    conn.execute("CREATE TABLE IF NOT EXISTS dep_cache (dep_id TEXT PRIMARY KEY, hf_repo_id TEXT NOT NULL, resolved_path TEXT, download_status TEXT NOT NULL DEFAULT 'pending', download_progress INTEGER NOT NULL DEFAULT 0, download_speed_bps INTEGER NOT NULL DEFAULT 0, download_error TEXT, revision TEXT DEFAULT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS model_dep_requirements (model_id TEXT NOT NULL REFERENCES model_definitions(id) ON DELETE CASCADE, dep_id TEXT NOT NULL REFERENCES dep_cache(dep_id), PRIMARY KEY (model_id, dep_id))")
    model_table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_definitions' LIMIT 1"
    ).fetchone()
    if model_table_exists is None:
        print("[WARN] model_definitions table not found; nothing to migrate.")
        return 0, 0, 0

    rows = conn.execute("SELECT id, provider_type FROM model_definitions WHERE LOWER(TRIM(download_status)) = 'done' ORDER BY created_at, id").fetchall()

    dep_status_cache: dict[str, tuple[str, str | None]] = {}
    ready_dep_ids: set[str] = set()
    pending_dep_ids: set[str] = set()
    no_weight_dep_ids: set[str] = set()
    for row in rows:
        model_id = str(row["id"])
        for dep_id, hf_repo_id in provider_dependencies(str(row["provider_type"])):
            status, path = dep_status_cache.get(dep_id, ("", None))
            if not status:
                resolved_snapshot_path = resolve_local_snapshot(hf_repo_id)
                if snapshot_has_model_weights(resolved_snapshot_path):
                    status = "done"
                    path = resolved_snapshot_path
                else:
                    status = "pending"
                    path = None
                    if resolved_snapshot_path:
                        no_weight_dep_ids.add(dep_id)
                dep_status_cache[dep_id] = (status, path)
            (ready_dep_ids if status == "done" else pending_dep_ids).add(dep_id)

            suffix = f" / {path}" if path else ""
            print(f"{model_id} / {dep_id} / {status}{suffix}")
            if dry_run:
                continue
            conn.execute("INSERT INTO dep_cache (dep_id, hf_repo_id, resolved_path, download_status, download_progress, download_speed_bps, download_error) VALUES (?, ?, ?, ?, ?, 0, NULL) ON CONFLICT(dep_id) DO UPDATE SET hf_repo_id=excluded.hf_repo_id, resolved_path=excluded.resolved_path, download_status=excluded.download_status, download_progress=excluded.download_progress, download_speed_bps=0, download_error=NULL", (dep_id, hf_repo_id, path, status, 100 if status == "done" else 0))
            conn.execute(
                "INSERT OR IGNORE INTO model_dep_requirements (model_id, dep_id) VALUES (?, ?)",
                (model_id, dep_id),
            )

    if not dry_run:
        conn.commit()
    return len(ready_dep_ids), len(pending_dep_ids), len(no_weight_dep_ids)


def main() -> int:
    args = parse_args()
    db_path = os.path.abspath(os.path.expanduser(args.database_path))
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        ready_count, pending_count, no_weight_count = migrate(conn, dry_run=args.dry_run)
    except sqlite3.Error as exc:
        print(f"[ERROR] sqlite error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()

    mode = "DRY-RUN" if args.dry_run else "APPLY"
    print(f"[{mode}] ready={ready_count} pending={pending_count} no_model_weights={no_weight_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
