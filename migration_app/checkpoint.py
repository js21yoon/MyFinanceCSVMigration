"""Tracks which CODEIDs have already been fully upserted in a --run pass
(PRD §11 Phase 7), so an interrupted migration can resume without
reprocessing companies it already finished. Written one line per CODEID,
flushed immediately after that CODEID's upsert succeeds -- so the file on
disk always reflects exactly what has been durably committed.
"""
from __future__ import annotations

from pathlib import Path

CHECKPOINTS_DIR = Path(__file__).resolve().parent / "checkpoints"
DEFAULT_CHECKPOINT_FILE = CHECKPOINTS_DIR / "completed_codeids.txt"


def load_checkpoint(path: Path = DEFAULT_CHECKPOINT_FILE) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def append_checkpoint(codeid: str, path: Path = DEFAULT_CHECKPOINT_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(codeid + "\n")
        f.flush()


def clear_checkpoint(path: Path = DEFAULT_CHECKPOINT_FILE) -> None:
    if path.exists():
        path.unlink()
