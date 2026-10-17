"""The throwaway SQLite database each benchmark run starts from."""

from __future__ import annotations

from pathlib import Path


def wipe_db(db_path: Path) -> None:
    """Remove a SQLite db file and its WAL-mode sidecar files."""
    for suffix in ("", "-shm", "-wal"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
