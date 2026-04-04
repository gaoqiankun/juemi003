#!/usr/bin/env python3
"""Backfill missing dep_instances and model_dep_requirements rows.

For each model_definitions row marked 'done', compare the provider's current
declared dependencies against what is already assigned in model_dep_requirements.
Any dep_type that is not yet assigned gets a dep_instance created (or an
existing one reused) and linked to the model.

Usage:
    # Dry run (no writes):
    python scripts/migrate_missing_deps.py --dry-run

    # Apply:
    python scripts/migrate_missing_deps.py
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATABASE_PATH = "./data/app.sqlite3"
MODEL_WEIGHT_GLOBS = (
    "*.safetensors",
    "pytorch_model*.bin",
    "model.ckpt*",
    "tf_model.h5",
    "flax_model.msgpack",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill dep_instances / model_dep_requirements for existing models."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without writing to SQLite.",
    )
    parser.add_argument(
        "--database-path",
        default=os.getenv("DATABASE_PATH", DEFAULT_DATABASE_PATH),
        help="SQLite path (default: env DATABASE_PATH or ./data/app.sqlite3).",
    )
    return parser.parse_args()


@dataclass
class DepSpec:
    dep_type: str
    hf_repo_id: str
    description: str


def provider_dep_specs(provider_type: str) -> list[DepSpec]:
    try:
        from gen3d.model.hunyuan3d.provider import Hunyuan3DProvider
        from gen3d.model.step1x3d.provider import Step1X3DProvider
        from gen3d.model.trellis2.provider import Trellis2Provider
    except Exception as exc:
        raise RuntimeError(f"failed to import providers: {exc}") from exc

    provider_cls = {
        "trellis2": Trellis2Provider,
        "hunyuan3d": Hunyuan3DProvider,
        "step1x3d": Step1X3DProvider,
    }.get(provider_type.strip().lower())
    if provider_cls is None:
        return []

    specs: list[DepSpec] = []
    for dep in provider_cls.dependencies() or []:
        dep_type = str(getattr(dep, "dep_id", "") or "").strip()
        hf_repo_id = str(getattr(dep, "hf_repo_id", "") or "").strip()
        description = str(getattr(dep, "description", "") or dep_type).strip()
        if dep_type and hf_repo_id:
            specs.append(DepSpec(dep_type=dep_type, hf_repo_id=hf_repo_id, description=description))
    return specs


def resolve_local_snapshot(hf_repo_id: str) -> str | None:
    try:
        from huggingface_hub import snapshot_download
    except ModuleNotFoundError as exc:
        raise RuntimeError("huggingface_hub is required.") from exc
    try:
        return snapshot_download(repo_id=hf_repo_id, local_files_only=True)
    except Exception:
        return None


def snapshot_has_model_weights(path: str | None) -> bool:
    if not path:
        return False
    candidate = Path(path).expanduser()
    if not candidate.exists() or not candidate.is_dir():
        return False
    for pattern in MODEL_WEIGHT_GLOBS:
        try:
            next(candidate.rglob(pattern))
        except StopIteration:
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# Core migration
# ---------------------------------------------------------------------------


def get_best_instance_for_dep_type(
    conn: sqlite3.Connection, dep_type: str
) -> dict | None:
    """Return the best existing dep_instance for dep_type (prefer 'done')."""
    row = conn.execute(
        """
        SELECT id, dep_type, hf_repo_id, display_name, download_status, resolved_path
        FROM dep_instances
        WHERE dep_type = ?
        ORDER BY
            CASE download_status WHEN 'done' THEN 0
                                 WHEN 'downloading' THEN 1
                                 WHEN 'pending' THEN 2
                                 ELSE 3 END,
            created_at, id
        LIMIT 1
        """,
        (dep_type,),
    ).fetchone()
    return dict(row) if row else None


def get_assigned_dep_types(conn: sqlite3.Connection, model_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT dep_type FROM model_dep_requirements WHERE model_id = ?",
        (model_id,),
    ).fetchall()
    return {str(r["dep_type"]) for r in rows}


def migrate(conn: sqlite3.Connection, dry_run: bool) -> tuple[int, int, int]:
    """
    Returns (models_updated, instances_created, assignments_added).
    """
    # Verify dep_instances table exists (app must have started once to create it)
    dep_instances_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dep_instances' LIMIT 1"
    ).fetchone()
    if dep_instances_exists is None:
        print(
            "[ERROR] dep_instances table not found. "
            "Start the app once to run the automatic schema migration, then re-run this script.",
            file=sys.stderr,
        )
        sys.exit(1)

    model_rows = conn.execute(
        "SELECT id, provider_type FROM model_definitions "
        "WHERE LOWER(TRIM(download_status)) = 'done' "
        "ORDER BY created_at, id"
    ).fetchall()
    if not model_rows:
        print("[INFO] No 'done' model instances found.")
        return 0, 0, 0

    # Cache: dep_type → (instance_id, status) that we reuse or just created
    # so multiple models sharing the same dep_type get the same instance.
    dep_type_instance_cache: dict[str, str] = {}

    models_updated = 0
    instances_created = 0
    assignments_added = 0

    for model_row in model_rows:
        model_id = str(model_row["id"])
        provider_type = str(model_row["provider_type"] or "").strip().lower()

        dep_specs = provider_dep_specs(provider_type)
        if not dep_specs:
            continue

        assigned = get_assigned_dep_types(conn, model_id)
        missing = [s for s in dep_specs if s.dep_type not in assigned]
        if not missing:
            continue

        model_had_update = False
        for spec in missing:
            dep_type = spec.dep_type

            # Determine which instance_id to link
            if dep_type in dep_type_instance_cache:
                instance_id = dep_type_instance_cache[dep_type]
                action = "reuse-cached"
            else:
                existing = get_best_instance_for_dep_type(conn, dep_type)
                if existing:
                    instance_id = str(existing["id"])
                    dep_type_instance_cache[dep_type] = instance_id
                    action = f"reuse-existing (status={existing['download_status']})"
                else:
                    # Create a new dep_instance
                    resolved = resolve_local_snapshot(spec.hf_repo_id)
                    has_weights = snapshot_has_model_weights(resolved)
                    status = "done" if has_weights else "pending"
                    resolved_path = resolved if has_weights else None
                    progress = 100 if has_weights else 0
                    display_name = spec.dep_type
                    instance_id = dep_type  # use dep_type as id for the default instance

                    suffix = f" → {resolved_path}" if resolved_path else " (will download)"
                    action = f"create-new ({status}){suffix}"

                    if not dry_run:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO dep_instances
                                (id, dep_type, hf_repo_id, display_name, weight_source,
                                 resolved_path, download_status, download_progress,
                                 download_speed_bps, download_error)
                            VALUES (?, ?, ?, ?, 'huggingface', ?, ?, ?, 0, NULL)
                            """,
                            (
                                instance_id,
                                dep_type,
                                spec.hf_repo_id,
                                display_name,
                                resolved_path,
                                status,
                                progress,
                            ),
                        )
                        instances_created += 1
                    else:
                        instances_created += 1

                    dep_type_instance_cache[dep_type] = instance_id

            print(
                f"  model={model_id}  dep_type={dep_type}  instance={instance_id}  [{action}]"
            )

            if not dry_run:
                conn.execute(
                    "INSERT OR IGNORE INTO model_dep_requirements "
                    "(model_id, dep_type, dep_instance_id) VALUES (?, ?, ?)",
                    (model_id, dep_type, instance_id),
                )
                assignments_added += 1
            else:
                assignments_added += 1

            model_had_update = True

        if model_had_update:
            models_updated += 1

    if not dry_run:
        conn.commit()

    return models_updated, instances_created, assignments_added


def main() -> int:
    args = parse_args()
    db_path = os.path.abspath(os.path.expanduser(args.database_path))

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        models_updated, instances_created, assignments_added = migrate(
            conn, dry_run=args.dry_run
        )
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
    print(
        f"[{mode}] models_updated={models_updated}  "
        f"instances_created={instances_created}  "
        f"assignments_added={assignments_added}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
