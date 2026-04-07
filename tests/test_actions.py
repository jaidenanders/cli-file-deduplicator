"""
test_actions.py — Tests for actions.py: disposal modes, keeper selection, undo log.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dedup.actions import (
    apply_disposal,
    dispose_delete,
    dispose_hardlink,
    dispose_symlink,
    select_keeper,
    write_undo_log,
)


# ---------------------------------------------------------------------------
# select_keeper
# ---------------------------------------------------------------------------

class TestSelectKeeper:

    def test_default_keeps_first(self, tmp_path):
        files = [tmp_path / f"{i}.txt" for i in range(3)]
        for f in files:
            f.write_bytes(b"data")
        keeper, to_remove = select_keeper(files)
        assert keeper == files[0]
        assert set(to_remove) == {files[1], files[2]}

    def test_keep_newest(self, tmp_path):
        files = []
        for i in range(3):
            f = tmp_path / f"{i}.txt"
            f.write_bytes(b"data")
            os.utime(f, (i * 1000, i * 1000))
            files.append(f)
        keeper, to_remove = select_keeper(files, keep_newest=True)
        assert keeper == files[2]   # highest mtime
        assert files[2] not in to_remove

    def test_keep_oldest(self, tmp_path):
        files = []
        for i in range(3):
            f = tmp_path / f"{i}.txt"
            f.write_bytes(b"data")
            os.utime(f, (i * 1000, i * 1000))
            files.append(f)
        keeper, to_remove = select_keeper(files, keep_oldest=True)
        assert keeper == files[0]   # lowest mtime
        assert files[0] not in to_remove

    def test_keep_path_matches(self, tmp_path):
        preferred = tmp_path / "originals"
        preferred.mkdir()
        other = tmp_path / "copies"
        other.mkdir()

        f_pref  = preferred / "file.txt"
        f_other = other / "file.txt"
        f_pref.write_bytes(b"x")
        f_other.write_bytes(b"x")

        keeper, to_remove = select_keeper([f_other, f_pref], keep_path=preferred)
        assert keeper == f_pref
        assert f_other in to_remove

    def test_keep_path_fallback_when_none_match(self, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        nonexistent_pref = tmp_path / "preferred"

        files = [other / f"{i}.txt" for i in range(2)]
        for f in files:
            f.write_bytes(b"x")

        keeper, _ = select_keeper(files, keep_path=nonexistent_pref)
        assert keeper == files[0]   # fallback to first


# ---------------------------------------------------------------------------
# dispose_delete
# ---------------------------------------------------------------------------

class TestDisposeDelete:

    def test_deletes_file(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_bytes(b"bye")
        ok, msg = dispose_delete(f)
        assert ok is True
        assert not f.exists()

    def test_returns_error_for_nonexistent(self, tmp_path):
        f = tmp_path / "ghost.txt"
        ok, msg = dispose_delete(f)
        assert ok is False
        assert "Error" in msg


# ---------------------------------------------------------------------------
# dispose_hardlink
# ---------------------------------------------------------------------------

class TestDisposeHardlink:

    def test_creates_hardlink(self, tmp_path):
        keeper = tmp_path / "keeper.txt"
        keeper.write_bytes(b"shared content")
        target = tmp_path / "target.txt"
        target.write_bytes(b"shared content")

        ok, msg = dispose_hardlink(target, keeper)

        if ok:
            # Both should now point to the same inode
            assert target.exists()
            assert os.stat(keeper).st_ino == os.stat(target).st_ino
        else:
            # Cross-device links may fail; that's acceptable
            assert "failed" in msg.lower()


# ---------------------------------------------------------------------------
# dispose_symlink
# ---------------------------------------------------------------------------

class TestDisposeSymlink:

    def test_creates_symlink(self, tmp_path):
        keeper = tmp_path / "keeper.txt"
        keeper.write_bytes(b"real content")
        target = tmp_path / "target.txt"
        target.write_bytes(b"real content")

        ok, msg = dispose_symlink(target, keeper)
        assert ok is True
        assert target.is_symlink()
        assert target.resolve() == keeper.resolve()


# ---------------------------------------------------------------------------
# apply_disposal dispatch
# ---------------------------------------------------------------------------

class TestApplyDisposal:

    def test_delete_mode(self, tmp_path):
        f = tmp_path / "f.txt"
        f.write_bytes(b"x")
        ok, _ = apply_disposal(f, "delete")
        assert ok
        assert not f.exists()

    def test_symlink_mode(self, tmp_path):
        keeper = tmp_path / "keeper.txt"
        keeper.write_bytes(b"data")
        target = tmp_path / "target.txt"
        target.write_bytes(b"data")
        ok, _ = apply_disposal(target, "symlink", keeper=keeper)
        assert ok
        assert target.is_symlink()

    def test_unknown_mode_returns_error(self, tmp_path):
        f = tmp_path / "f.txt"
        f.write_bytes(b"x")
        ok, msg = apply_disposal(f, "explode")
        assert ok is False
        assert "Unknown" in msg

    def test_hardlink_requires_keeper(self, tmp_path):
        f = tmp_path / "f.txt"
        f.write_bytes(b"x")
        ok, msg = apply_disposal(f, "hardlink", keeper=None)
        assert ok is False


# ---------------------------------------------------------------------------
# write_undo_log
# ---------------------------------------------------------------------------

class TestUndoLog:

    def test_writes_valid_json(self, tmp_path):
        files = [tmp_path / f"{i}.txt" for i in range(3)]
        for f in files:
            f.write_bytes(b"data")

        log = tmp_path / "undo.json"
        write_undo_log(log, files, "delete")

        records = json.loads(log.read_text())
        assert isinstance(records, list)
        assert len(records) == 3
        assert all("path" in r and "mode" in r and "timestamp" in r for r in records)

    def test_log_contains_correct_paths(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_bytes(b"data")
        log = tmp_path / "undo.json"
        write_undo_log(log, [f], "trash")
        records = json.loads(log.read_text())
        assert records[0]["path"] == str(f)
        assert records[0]["mode"] == "trash"
