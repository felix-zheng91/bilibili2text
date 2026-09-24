#!/usr/bin/env python3
"""Delete PNG export caches for the most recent transcription runs."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from minio import Minio

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from b2t.config import load_config


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Delete PNG objects belonging to the most recent summary-bearing "
            "transcription runs."
        )
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "n",
        type=int,
        nargs="?",
        help="number of recent transcription runs",
    )
    selection.add_argument(
        "--bvid",
        help="delete PNG caches for all runs matching this BVID",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="optional config.toml path (defaults to the normal B2T config lookup)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list the selected runs and objects without deleting anything",
    )
    args = parser.parse_args()
    if args.n is not None and args.n <= 0:
        parser.error("n must be a positive integer")
    return args


def _recent_runs(db_path: Path, limit: int) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            """
            SELECT run_id, bvid, title, created_at
            FROM transcription_runs
            WHERE record_type = 'transcription' AND has_summary = 1
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()


def _runs_for_bvid(db_path: Path, bvid: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            """
            SELECT run_id, bvid, title, created_at
            FROM transcription_runs
            WHERE record_type = 'transcription' AND lower(bvid) = lower(?)
            ORDER BY created_at DESC, id DESC
            """,
            (bvid.strip(),),
        ).fetchall()
    finally:
        conn.close()


def _png_objects(client: Minio, bucket: str, prefix: str) -> list[str]:
    return [
        obj.object_name
        for obj in client.list_objects(bucket, prefix=prefix, recursive=True)
        if obj.object_name.lower().endswith(".png")
    ]


def _objects_for_runs(
    client: Minio,
    *,
    bucket: str,
    base_prefix: str,
    runs: list[sqlite3.Row],
) -> list[str]:
    object_keys: set[str] = set()
    for run in runs:
        run_prefix = f"{base_prefix}/{run['run_id']}" if base_prefix else run["run_id"]
        object_keys.update(_png_objects(client, bucket, f"{run_prefix}/"))

    bvids = {str(run["bvid"] or "").strip() for run in runs}
    bvids.discard("")
    if not bvids:
        return sorted(object_keys)

    converted_prefix = f"{base_prefix}/converted/" if base_prefix else "converted/"
    for key in _png_objects(client, bucket, converted_prefix):
        filename = Path(key).name
        filename_lower = filename.lower()
        if any(filename_lower.startswith(f"{bvid.lower()}_") for bvid in bvids):
            object_keys.add(key)
    return sorted(object_keys)


def main() -> int:
    args = _parse_args()
    config = load_config(args.config)
    if config.storage.backend.strip().lower() != "minio":
        raise SystemExit(
            "Configured storage.backend is not minio; refusing to delete objects."
        )

    db_path = Path(config.download.db_dir) / "b2t_history.db"
    if not db_path.exists():
        raise SystemExit(f"History database does not exist: {db_path}")

    runs = (
        _runs_for_bvid(db_path, args.bvid)
        if args.bvid
        else _recent_runs(db_path, args.n)
    )
    if not runs:
        print("No matching transcription runs found.")
        return 0

    minio_config = config.storage.minio
    client = Minio(
        endpoint=minio_config.endpoint.strip(),
        access_key=minio_config.access_key,
        secret_key=minio_config.secret_key,
        secure=minio_config.secure,
        region=minio_config.region.strip() or None,
    )
    bucket = minio_config.bucket.strip()
    base_prefix = minio_config.base_prefix.strip("/")
    object_keys = _objects_for_runs(
        client,
        bucket=bucket,
        base_prefix=base_prefix,
        runs=runs,
    )

    print(f"Selected {len(runs)} recent transcription run(s):")
    for run in runs:
        print(f"- {run['run_id']} | {run['created_at']} | {run['title']}")
    print(f"PNG objects matched: {len(object_keys)}")
    for key in object_keys:
        print(f"  {key}")

    if args.dry_run:
        print("Dry run: no objects deleted.")
        return 0

    for key in object_keys:
        client.remove_object(bucket, key)
    print(f"Deleted {len(object_keys)} PNG object(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
