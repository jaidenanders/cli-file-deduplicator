"""
test_core.py — Tests for core.py: scanning, hashing, duplicate detection.
"""

from __future__ import annotations

import os
import hashlib
from pathlib import Path

import pytest

from dedup.core import (
    DEFAULT_IGNORE_DIRS,
    find_duplicates,
    duplicate_stats,
    full_hash,
    iter_files,
    partial_hash,
)


# ---------------------------------------------------------------------------
# iter_files
# ---------------------------------------------------------------------------

class TestIterFiles:

    def test_yields_all_regular_files(self, dup_tree):
        files = list(iter_files(dup_tree["root"]))
        assert len(files) == dup_tree["total_files"]

    def test_skips_symlinks(self, tmp_path):
        real = tmp_path / "real.txt"
        real.write_bytes(b"data")
        link = tmp_path / "link.txt"
        link.symlink_to(real)
        files = list(iter_files(tmp_path))
        assert real in files
        assert link not in files

    def test_skips_ignored_dirs(self, ignored_dirs_tree):
        files = list(iter_files(ignored_dirs_tree))
        paths_str = [str(f) for f in files]
        assert not any("node_modules" in p for p in paths_str)

    def test_extension_filter(self, mixed_extensions_tree):
        pdfs = list(iter_files(mixed_extensions_tree, extensions=[".pdf"]))
        assert all(p.suffix == ".pdf" for p in pdfs)
        assert len(pdfs) == 2

    def test_min_size_filter(self, size_threshold_tree):
        # Only files >= 500 bytes
        files = list(iter_files(size_threshold_tree, min_size=500))
        assert all(p.stat().st_size >= 500 for p in files)

    def test_empty_directory(self, empty_dir):
        assert list(iter_files(empty_dir)) == []

    def test_extra_ignore_dirs(self, tmp_path):
        (tmp_path / "build").mkdir()
        (tmp_path / "build" / "artifact.o").write_bytes(b"compiled")
        (tmp_path / "main.c").write_bytes(b"int main(){}")
        files = list(iter_files(tmp_path, ignore_dirs=frozenset({"build"})))
        names = {f.name for f in files}
        assert "main.c" in names
        assert "artifact.o" not in names


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

class TestHashing:

    def test_full_hash_correctness(self, tmp_path):
        data = b"test content for hashing"
        f = tmp_path / "file.bin"
        f.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert full_hash(f, "sha256") == expected

    def test_full_hash_md5(self, tmp_path):
        data = b"md5 test"
        f = tmp_path / "f.bin"
        f.write_bytes(data)
        expected = hashlib.md5(data).hexdigest()
        assert full_hash(f, "md5") == expected

    def test_partial_hash_reads_only_first_bytes(self, tmp_path):
        from dedup.core import PARTIAL_BYTES
        data = b"A" * PARTIAL_BYTES + b"B" * 1000   # extra B's should be ignored
        same_prefix = b"A" * PARTIAL_BYTES + b"C" * 1000
        f1 = tmp_path / "f1.bin"
        f2 = tmp_path / "f2.bin"
        f1.write_bytes(data)
        f2.write_bytes(same_prefix)
        # Same prefix → same partial hash; different full content → different full hash
        assert partial_hash(f1) == partial_hash(f2)
        assert full_hash(f1) != full_hash(f2)

    def test_identical_files_have_same_hash(self, tmp_path):
        content = b"identical content"
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_bytes(content)
        f2.write_bytes(content)
        assert full_hash(f1) == full_hash(f2)


# ---------------------------------------------------------------------------
# find_duplicates
# ---------------------------------------------------------------------------

class TestFindDuplicates:

    def test_finds_correct_groups(self, dup_tree):
        dupes, total, errors = find_duplicates(dup_tree["root"])
        assert errors == 0
        assert total == dup_tree["total_files"]
        assert len(dupes) == dup_tree["dup_groups"]

    def test_each_group_has_correct_paths(self, dup_tree):
        dupes, _, _ = find_duplicates(dup_tree["root"])
        for paths in dupes.values():
            assert len(paths) >= 2
            # All files in a group must have identical content
            hashes = {full_hash(p) for p in paths}
            assert len(hashes) == 1

    def test_no_duplicates(self, no_duplicates_tree):
        dupes, total, errors = find_duplicates(no_duplicates_tree)
        assert dupes == {}
        assert total == 6
        assert errors == 0

    def test_empty_directory(self, empty_dir):
        dupes, total, errors = find_duplicates(empty_dir)
        assert dupes == {}
        assert total == 0

    def test_hardlinks_not_flagged_as_duplicates(self, hardlinked_tree):
        dupes, _, _ = find_duplicates(hardlinked_tree["root"])
        assert dupes == {}

    def test_extension_filter(self, mixed_extensions_tree):
        dupes, _, _ = find_duplicates(mixed_extensions_tree, extensions=[".pdf"])
        # Only PDFs should be considered; .jpg duplicates ignored
        for paths in dupes.values():
            assert all(p.suffix == ".pdf" for p in paths)

    def test_min_size_filter(self, size_threshold_tree):
        # Only find duplicates in files >= 5000 bytes
        dupes, _, _ = find_duplicates(size_threshold_tree, min_size=5000)
        for paths in dupes.values():
            assert all(p.stat().st_size >= 5000 for p in paths)

    def test_ignored_dirs_excluded(self, ignored_dirs_tree):
        dupes, _, _ = find_duplicates(ignored_dirs_tree)
        # node_modules is ignored, so no duplicates should be found
        assert dupes == {}

    def test_algorithm_md5(self, dup_tree):
        dupes_sha, _, _ = find_duplicates(dup_tree["root"], algorithm="sha256")
        dupes_md5, _, _  = find_duplicates(dup_tree["root"], algorithm="md5")
        assert len(dupes_sha) == len(dupes_md5)

    def test_progress_callback_called(self, dup_tree):
        visited = []
        find_duplicates(dup_tree["root"], progress_cb=lambda p: visited.append(p))
        # Callback should have been called at least once per duplicate candidate
        assert len(visited) > 0

    def test_three_way_duplicate(self, tmp_path):
        content = b"same content in three files"
        for name in ("a.txt", "b.txt", "c.txt"):
            (tmp_path / name).write_bytes(content)
        dupes, _, _ = find_duplicates(tmp_path)
        assert len(dupes) == 1
        paths = list(dupes.values())[0]
        assert len(paths) == 3


# ---------------------------------------------------------------------------
# duplicate_stats
# ---------------------------------------------------------------------------

class TestDuplicateStats:

    def test_stats_correctness(self, dup_tree):
        dupes, _, _ = find_duplicates(dup_tree["root"])
        stats = duplicate_stats(dupes)
        assert stats["groups"] == dup_tree["dup_groups"]
        assert stats["duplicate_files"] == dup_tree["dup_files"]
        assert stats["wasted_bytes"] > 0

    def test_empty_duplicates(self):
        stats = duplicate_stats({})
        assert stats == {"groups": 0, "duplicate_files": 0, "wasted_bytes": 0}

    def test_wasted_bytes_calculation(self, tmp_path):
        content = b"x" * 1000
        (tmp_path / "a.bin").write_bytes(content)
        (tmp_path / "b.bin").write_bytes(content)
        (tmp_path / "c.bin").write_bytes(content)
        dupes, _, _ = find_duplicates(tmp_path)
        stats = duplicate_stats(dupes)
        # 3 copies, 2 extras → wasted = 2 * 1000
        assert stats["wasted_bytes"] == 2000
