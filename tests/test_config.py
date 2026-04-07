"""
test_config.py — Tests for config.py: .deduprc loading, parse_list, defaults.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dedup.config import load_config, parse_list, write_example_config


class TestParseList:

    def test_empty_string(self):
        assert parse_list("") == []

    def test_single_item(self):
        assert parse_list(".jpg") == [".jpg"]

    def test_multiple_items(self):
        assert parse_list(".jpg,.png,.pdf") == [".jpg", ".png", ".pdf"]

    def test_strips_whitespace(self):
        assert parse_list(" .jpg , .png ") == [".jpg", ".png"]

    def test_ignores_empty_tokens(self):
        assert parse_list(",.jpg,,") == [".jpg"]


class TestLoadConfig:

    def test_returns_defaults_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))
        cfg = load_config()
        assert cfg["algorithm"]  == "sha256"
        assert cfg["disposal"]   == "delete"
        assert cfg["sort_by"]    == "size"

    def test_reads_local_deduprc(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        rc = tmp_path / ".deduprc"
        rc.write_text("[dedup]\nalgorithm = md5\ndisposal = trash\n")
        cfg = load_config()
        assert cfg["algorithm"] == "md5"
        assert cfg["disposal"]  == "trash"

    def test_partial_config_keeps_defaults(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        rc = tmp_path / ".deduprc"
        rc.write_text("[dedup]\nalgorithm = md5\n")
        cfg = load_config()
        assert cfg["algorithm"] == "md5"
        assert cfg["sort_by"]   == "size"     # default preserved


class TestWriteExampleConfig:

    def test_creates_file(self, tmp_path):
        dest = tmp_path / ".deduprc"
        write_example_config(dest)
        assert dest.exists()

    def test_file_is_valid_ini(self, tmp_path):
        import configparser
        dest = tmp_path / ".deduprc"
        write_example_config(dest)
        cfg = configparser.ConfigParser()
        cfg.read(dest)
        assert cfg.has_section("dedup")

    def test_file_contains_key_options(self, tmp_path):
        dest = tmp_path / ".deduprc"
        write_example_config(dest)
        content = dest.read_text()
        assert "algorithm" in content
        assert "disposal"  in content
        assert "sort_by"   in content
