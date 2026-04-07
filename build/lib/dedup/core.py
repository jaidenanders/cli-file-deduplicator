"""
core.py — Scanning, hashing, and duplicate detection.

Hashing strategy (three-pass pipeline):
  1. Group by file size  (free — just stat())
  2. Partial hash        (first PARTIAL_BYTES of each size-collision group)
  3. Full hash           (only files whose partial hash also collides)

This means the vast majority of files are eliminated after step 1 or 2,
and an expensive full read is only done when truly necessary.
"""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from pathlib import Path
from typing import Callable, Generator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PARTIAL_BYTES = 4_096
CHUNK_SIZE    = 65_536

DEFAULT_IGNORE_DIRS: frozenset[str] = frozenset({
    ".git", ".hg", ".svn",
    "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".tox", ".venv", "venv", "env",
})


# ---------------------------------------------------------------------------
# File iteration
# ---------------------------------------------------------------------------

def iter_files(
    directory: Path,
    extensions: list[str] | None = None,
    min_size: int = 1,
    ignore_dirs: frozenset[str] = DEFAULT_IGNORE_DIRS,
) -> Generator[Path, None, None]:
    """
    Recursively yield files under *directory*.

    Skips symlinks, hidden/ignored directories, files below min_size,
    and files not matching the extension whitelist.
    """
    try:
        entries = list(os.scandir(directory))
    except PermissionError:
        return

    for entry in entries:
        try:
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                if entry.name.startswith(".") or entry.name in ignore_dirs:
                    continue
                yield from iter_files(Path(entry.path), extensions, min_size, ignore_dirs)
            elif entry.is_file(follow_symlinks=False):
                if entry.stat().st_size < min_size:
                    continue
                path = Path(entry.path)
                if extensions and path.suffix.lower() not in extensions:
                    continue
                yield path
        except (PermissionError, OSError):
            continue


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def partial_hash(path: Path, algorithm: str = "sha256") -> str:
    """Hash only the first PARTIAL_BYTES of a file."""
    h = hashlib.new(algorithm)
    with path.open("rb") as fh:
        h.update(fh.read(PARTIAL_BYTES))
    return h.hexdigest()


def full_hash(path: Path, algorithm: str = "sha256") -> str:
    """Hash the entire file in CHUNK_SIZE chunks."""
    h = hashlib.new(algorithm)
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Hardlink helpers
# ---------------------------------------------------------------------------

def _inode_key(path: Path) -> tuple[int, int]:
    s = path.stat()
    return (s.st_dev, s.st_ino)


def _deduplicate_hardlinks(paths: list[Path]) -> list[Path]:
    """
    Collapse paths that share the same inode (already hardlinked).
    Keeps one representative per inode — deleting one would silently
    destroy the data for all of them.
    """
    seen: set[tuple[int, int]] = set()
    result: list[Path] = []
    for p in paths:
        try:
            key = _inode_key(p)
        except OSError:
            result.append(p)
            continue
        if key not in seen:
            seen.add(key)
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# Three-pass duplicate finder
# ---------------------------------------------------------------------------

def find_duplicates(
    directory: Path,
    algorithm: str = "sha256",
    extensions: list[str] | None = None,
    min_size: int = 1,
    ignore_dirs: frozenset[str] = DEFAULT_IGNORE_DIRS,
    progress_cb: Callable[[Path], None] | None = None,
) -> tuple[dict[str, list[Path]], int, int]:
    """
    Return groups of files with identical content.

    Pass 1 — group by size       (stat only, zero reads)
    Pass 2 — group by partial hash  (reads PARTIAL_BYTES per file)
    Pass 3 — group by full hash     (full read, true collisions only)

    Returns (duplicates, total_files_scanned, error_count).
    """
    # Pass 1: size
    by_size: dict[int, list[Path]] = defaultdict(list)
    total = 0
    errors = 0

    for path in iter_files(directory, extensions, min_size, ignore_dirs):
        total += 1
        try:
            by_size[path.stat().st_size].append(path)
        except OSError:
            errors += 1

    size_collisions = [g for g in by_size.values() if len(g) > 1]

    # Pass 2: partial hash
    by_partial: dict[str, list[Path]] = defaultdict(list)
    for group in size_collisions:
        for path in group:
            if progress_cb:
                progress_cb(path)
            try:
                by_partial[partial_hash(path, algorithm)].append(path)
            except OSError:
                errors += 1

    partial_collisions = [g for g in by_partial.values() if len(g) > 1]

    # Pass 3: full hash
    by_full: dict[str, list[Path]] = defaultdict(list)
    for group in partial_collisions:
        for path in group:
            if progress_cb:
                progress_cb(path)
            try:
                by_full[full_hash(path, algorithm)].append(path)
            except OSError:
                errors += 1

    # Collapse hardlinks, filter singletons
    duplicates: dict[str, list[Path]] = {}
    for digest, paths in by_full.items():
        unique = _deduplicate_hardlinks(paths)
        if len(unique) > 1:
            duplicates[digest] = unique

    return duplicates, total, errors


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def duplicate_stats(duplicates: dict[str, list[Path]]) -> dict:
    groups    = len(duplicates)
    dup_files = 0
    wasted    = 0
    for paths in duplicates.values():
        extras = len(paths) - 1
        dup_files += extras
        try:
            wasted += paths[0].stat().st_size * extras
        except OSError:
            pass
    return {"groups": groups, "duplicate_files": dup_files, "wasted_bytes": wasted}
