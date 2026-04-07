"""
test_reporter.py — Tests for reporter.py: JSON/CSV export, ASCII chart.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from dedup.core import find_duplicates, duplicate_stats
from dedup.reporter import export_csv, export_json, render_dir_chart, fmt_bytes


# ---------------------------------------------------------------------------
# fmt_bytes
# ---------------------------------------------------------------------------

class TestFmtBytes:

    @pytest.mark.parametrize("n, expected", [
        (0,         "0.0 B"),
        (512,       "512.0 B"),
        (1024,      "1.0 KB"),
        (1536,      "1.5 KB"),
        (1_048_576, "1.0 MB"),
        (1_073_741_824, "1.0 GB"),
    ])
    def test_formats(self, n, expected):
        assert fmt_bytes(n) == expected


# ---------------------------------------------------------------------------
# export_json
# ---------------------------------------------------------------------------

class TestExportJson:

    def test_writes_valid_json(self, dup_tree, tmp_path):
        dupes, _, _ = find_duplicates(dup_tree["root"])
        stats = duplicate_stats(dupes)
        out = tmp_path / "report.json"
        export_json(dupes, stats, out)

        data = json.loads(out.read_text())
        assert "summary" in data
        assert "groups" in data
        assert isinstance(data["groups"], list)

    def test_summary_matches_stats(self, dup_tree, tmp_path):
        dupes, _, _ = find_duplicates(dup_tree["root"])
        stats = duplicate_stats(dupes)
        out = tmp_path / "report.json"
        export_json(dupes, stats, out)

        data = json.loads(out.read_text())
        assert data["summary"]["groups"]          == stats["groups"]
        assert data["summary"]["duplicate_files"] == stats["duplicate_files"]
        assert data["summary"]["wasted_bytes"]    == stats["wasted_bytes"]
        assert "wasted_human" in data["summary"]

    def test_groups_contain_correct_fields(self, dup_tree, tmp_path):
        dupes, _, _ = find_duplicates(dup_tree["root"])
        stats = duplicate_stats(dupes)
        out = tmp_path / "report.json"
        export_json(dupes, stats, out)

        data = json.loads(out.read_text())
        for group in data["groups"]:
            assert "hash"      in group
            assert "file_size" in group
            assert "copies"    in group
            assert len(group["copies"]) >= 2

    def test_groups_sorted_by_size_descending(self, dup_tree, tmp_path):
        dupes, _, _ = find_duplicates(dup_tree["root"])
        stats = duplicate_stats(dupes)
        out = tmp_path / "report.json"
        export_json(dupes, stats, out)

        data = json.loads(out.read_text())
        sizes = [g["file_size"] for g in data["groups"]]
        assert sizes == sorted(sizes, reverse=True)

    def test_empty_duplicates(self, tmp_path):
        out = tmp_path / "empty.json"
        export_json({}, {"groups": 0, "duplicate_files": 0, "wasted_bytes": 0}, out)
        data = json.loads(out.read_text())
        assert data["groups"] == []
        assert data["summary"]["groups"] == 0


# ---------------------------------------------------------------------------
# export_csv
# ---------------------------------------------------------------------------

class TestExportCsv:

    def test_writes_valid_csv(self, dup_tree, tmp_path):
        dupes, _, _ = find_duplicates(dup_tree["root"])
        out = tmp_path / "report.csv"
        export_csv(dupes, out)

        with out.open() as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        assert len(rows) > 0
        for row in rows:
            assert "hash"       in row
            assert "file_size"  in row
            assert "copy_index" in row
            assert "path"       in row

    def test_row_count_matches_total_copies(self, dup_tree, tmp_path):
        dupes, _, _ = find_duplicates(dup_tree["root"])
        total_copies = sum(len(v) for v in dupes.values())

        out = tmp_path / "report.csv"
        export_csv(dupes, out)

        with out.open() as fh:
            rows = list(csv.DictReader(fh))

        assert len(rows) == total_copies

    def test_copy_index_is_sequential(self, dup_tree, tmp_path):
        dupes, _, _ = find_duplicates(dup_tree["root"])
        out = tmp_path / "report.csv"
        export_csv(dupes, out)

        with out.open() as fh:
            rows = list(csv.DictReader(fh))

        # Group rows by hash and verify copy_index starts at 0
        from collections import defaultdict
        by_hash: dict = defaultdict(list)
        for row in rows:
            by_hash[row["hash"]].append(int(row["copy_index"]))
        for indices in by_hash.values():
            assert sorted(indices) == list(range(len(indices)))


# ---------------------------------------------------------------------------
# render_dir_chart
# ---------------------------------------------------------------------------

class TestRenderDirChart:

    def test_returns_string(self, dup_tree):
        dupes, _, _ = find_duplicates(dup_tree["root"])
        chart = render_dir_chart(dupes)
        assert isinstance(chart, str)
        assert len(chart) > 0

    def test_contains_directory_names(self, dup_tree):
        dupes, _, _ = find_duplicates(dup_tree["root"])
        chart = render_dir_chart(dupes)
        # At least one of the duplicate source dirs should appear in the chart
        assert any(
            str(p.parent).split(os.sep)[-1] in chart
            for paths in dupes.values()
            for p in paths[1:]   # extras only
        )

    def test_empty_duplicates_returns_message(self):
        chart = render_dir_chart({})
        assert "no duplicate waste" in chart

    def test_bar_chart_has_blocks(self, dup_tree):
        dupes, _, _ = find_duplicates(dup_tree["root"])
        chart = render_dir_chart(dupes)
        assert "█" in chart


import os
