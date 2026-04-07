"""
conftest.py — Shared pytest fixtures for the deduplicator test suite.
"""

from __future__ import annotations

import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Basic duplicate tree
# ---------------------------------------------------------------------------

@pytest.fixture
def dup_tree(tmp_path: Path) -> dict:
    """
    Create a directory tree with known duplicates.

    Layout:
        root/
          a/
            file1.txt          "hello world"
            unique.txt         "i am unique"
          b/
            file1_copy.txt     "hello world"   ← dup of a/file1.txt
            file2.jpg          "image data XY"
          c/
            file1_copy2.txt    "hello world"   ← dup of a/file1.txt
            file2_dup.jpg      "image data XY" ← dup of b/file2.jpg

    Expected: 2 duplicate groups, 3 redundant files.
    """
    root = tmp_path / "root"
    dirs = [root / "a", root / "b", root / "c"]
    for d in dirs:
        d.mkdir(parents=True)

    content_a = b"hello world"
    content_b = b"image data XY"

    (root / "a" / "file1.txt").write_bytes(content_a)
    (root / "a" / "unique.txt").write_bytes(b"i am unique and special")
    (root / "b" / "file1_copy.txt").write_bytes(content_a)
    (root / "b" / "file2.jpg").write_bytes(content_b)
    (root / "c" / "file1_copy2.txt").write_bytes(content_a)
    (root / "c" / "file2_dup.jpg").write_bytes(content_b)

    return {
        "root":       root,
        "content_a":  content_a,
        "content_b":  content_b,
        "total_files": 6,
        "dup_groups":  2,
        "dup_files":   3,    # 2 extra for content_a, 1 extra for content_b
    }


# ---------------------------------------------------------------------------
# Edge-case trees
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_dir(tmp_path: Path) -> Path:
    d = tmp_path / "empty"
    d.mkdir()
    return d


@pytest.fixture
def no_duplicates_tree(tmp_path: Path) -> Path:
    """Six files, all with distinct content."""
    root = tmp_path / "nodups"
    root.mkdir()
    for i in range(6):
        (root / f"file_{i}.txt").write_bytes(f"unique content {i} {'x' * i}".encode())
    return root


@pytest.fixture
def hardlinked_tree(tmp_path: Path) -> dict:
    """
    Two paths pointing to the same inode (hardlink).
    Should NOT appear as a duplicate — they share disk blocks.
    """
    import os
    root = tmp_path / "hardlinks"
    root.mkdir()
    original = root / "original.txt"
    original.write_bytes(b"shared inode content")
    linked = root / "linked.txt"
    os.link(original, linked)
    return {"root": root, "original": original, "linked": linked}


@pytest.fixture
def mixed_extensions_tree(tmp_path: Path) -> Path:
    """Tree with multiple file types, some duplicated."""
    root = tmp_path / "mixed"
    root.mkdir()
    (root / "doc.pdf").write_bytes(b"PDF content AAA")
    (root / "doc_copy.pdf").write_bytes(b"PDF content AAA")   # dup
    (root / "image.jpg").write_bytes(b"JPEG data BBB")
    (root / "image_copy.jpg").write_bytes(b"JPEG data BBB")   # dup
    (root / "script.py").write_bytes(b"print('hello')")       # unique
    return root


@pytest.fixture
def size_threshold_tree(tmp_path: Path) -> Path:
    """Files of varying sizes including some below common thresholds."""
    root = tmp_path / "sizes"
    root.mkdir()
    (root / "tiny.txt").write_bytes(b"x")                     # 1 byte
    (root / "tiny_dup.txt").write_bytes(b"x")                 # 1 byte, dup
    (root / "small.txt").write_bytes(b"small" * 100)          # 500 bytes
    (root / "small_dup.txt").write_bytes(b"small" * 100)      # 500 bytes, dup
    (root / "medium.txt").write_bytes(b"m" * 5000)            # 5000 bytes
    (root / "medium_dup.txt").write_bytes(b"m" * 5000)        # 5000 bytes, dup
    return root


@pytest.fixture
def ignored_dirs_tree(tmp_path: Path) -> Path:
    """Tree with a node_modules dir that should be ignored."""
    root = tmp_path / "with_ignored"
    (root / "src").mkdir(parents=True)
    (root / "node_modules" / "pkg").mkdir(parents=True)

    content = b"duplicate content"
    (root / "src" / "file.js").write_bytes(content)
    (root / "node_modules" / "pkg" / "file.js").write_bytes(content)  # should be ignored
    return root
