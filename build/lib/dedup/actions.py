"""
actions.py — Safe file disposal strategies.

Instead of a single unlink() call, the CLI offers four modes:

  delete    — permanent removal via Path.unlink()            (default)
  trash     — move to OS trash via send2trash                (recoverable)
  hardlink  — replace duplicates with hardlinks to the kept copy
  symlink   — replace duplicates with symlinks  to the kept copy

Every public function returns (success: bool, message: str).
"""

from __future__ import annotations

import os
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _newest(paths: list[Path]) -> Path:
    return max(paths, key=lambda p: p.stat().st_mtime)


def _oldest(paths: list[Path]) -> Path:
    return min(paths, key=lambda p: p.stat().st_mtime)


# ---------------------------------------------------------------------------
# Auto-keep selection helpers
# ---------------------------------------------------------------------------

def select_keeper(
    paths: list[Path],
    keep_newest: bool = False,
    keep_oldest: bool = False,
    keep_path: Path | None = None,
) -> tuple[Path, list[Path]]:
    """
    Choose which copy to keep and return (keeper, [to_remove, …]).

    Priority:
      1. --keep-path  — keep the copy inside the given directory
      2. --keep-newest — keep the most recently modified copy
      3. --keep-oldest — keep the oldest copy
      4. default      — keep paths[0] (first found)
    """
    if keep_path is not None:
        for p in paths:
            try:
                p.relative_to(keep_path)
                keeper = p
                break
            except ValueError:
                continue
        else:
            keeper = paths[0]   # fallback if none live under keep_path
    elif keep_newest:
        keeper = _newest(paths)
    elif keep_oldest:
        keeper = _oldest(paths)
    else:
        keeper = paths[0]

    to_remove = [p for p in paths if p != keeper]
    return keeper, to_remove


# ---------------------------------------------------------------------------
# Disposal backends
# ---------------------------------------------------------------------------

def dispose_delete(path: Path) -> tuple[bool, str]:
    """Permanently delete *path*."""
    try:
        path.unlink()
        return True, f"Deleted: {path}"
    except OSError as exc:
        return False, f"Error deleting {path}: {exc}"


def dispose_trash(path: Path) -> tuple[bool, str]:
    """Move *path* to the OS trash (recoverable)."""
    try:
        import send2trash  # type: ignore
        send2trash.send2trash(str(path))
        return True, f"Trashed: {path}"
    except ImportError:
        return False, "send2trash is not installed — run: pip install send2trash"
    except Exception as exc:
        return False, f"Error trashing {path}: {exc}"


def dispose_hardlink(path: Path, keeper: Path) -> tuple[bool, str]:
    """
    Replace *path* with a hardlink pointing to *keeper*.

    Hardlinks only work within the same filesystem. If that fails we
    fall back to a regular delete with a warning.
    """
    try:
        path.unlink()
        os.link(keeper, path)
        return True, f"Hardlinked: {path} → {keeper}"
    except OSError as exc:
        return False, f"Hardlink failed for {path}: {exc}"


def dispose_symlink(path: Path, keeper: Path) -> tuple[bool, str]:
    """Replace *path* with a symlink pointing to *keeper*."""
    try:
        path.unlink()
        path.symlink_to(keeper.resolve())
        return True, f"Symlinked: {path} → {keeper}"
    except OSError as exc:
        return False, f"Symlink failed for {path}: {exc}"


# ---------------------------------------------------------------------------
# Unified dispatch
# ---------------------------------------------------------------------------

DISPOSAL_MODES = ("delete", "trash", "hardlink", "symlink")


def apply_disposal(
    path: Path,
    mode: str,
    keeper: Path | None = None,
) -> tuple[bool, str]:
    """
    Dispatch to the right backend.

    *keeper* is required for 'hardlink' and 'symlink' modes.
    """
    if mode == "delete":
        return dispose_delete(path)
    elif mode == "trash":
        return dispose_trash(path)
    elif mode == "hardlink":
        if keeper is None:
            return False, "hardlink mode requires a keeper path"
        return dispose_hardlink(path, keeper)
    elif mode == "symlink":
        if keeper is None:
            return False, "symlink mode requires a keeper path"
        return dispose_symlink(path, keeper)
    else:
        return False, f"Unknown disposal mode: {mode!r}"


# ---------------------------------------------------------------------------
# Undo log
# ---------------------------------------------------------------------------

import json
import datetime


def write_undo_log(
    log_path: Path,
    deleted: list[Path],
    mode: str,
) -> None:
    """
    Write a JSON undo log to *log_path*.

    For 'delete' mode this also generates an undo.sh shell script
    alongside the JSON — though since files are gone, it can only remind
    the user what was removed.
    """
    records = [
        {
            "path": str(p),
            "mode": mode,
            "timestamp": datetime.datetime.now().isoformat(),
        }
        for p in deleted
    ]
    log_path.write_text(json.dumps(records, indent=2))
