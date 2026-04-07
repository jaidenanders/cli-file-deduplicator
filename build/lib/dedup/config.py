"""
config.py — Load persistent defaults from ~/.deduprc or a project-local .deduprc.

File format (TOML-like INI, parsed with configparser):

  [dedup]
  algorithm  = sha256
  min_size   = 0
  extensions = .jpg,.png,.pdf
  ignore_dirs = node_modules,__pycache__,.git
  disposal   = trash
  sort_by    = size

Values here are overridden by explicit CLI flags — the config only
supplies *defaults* for flags the user hasn't specified.
"""

from __future__ import annotations

import configparser
from pathlib import Path


CONFIG_FILENAME = ".deduprc"

_DEFAULTS = {
    "algorithm":   "sha256",
    "min_size":    "1",
    "extensions":  "",
    "ignore_dirs": "",
    "disposal":    "delete",
    "sort_by":     "size",
}


def _find_config() -> Path | None:
    """
    Search for .deduprc in:
      1. Current working directory
      2. User home directory
    Returns the first found, or None.
    """
    for candidate in (Path.cwd() / CONFIG_FILENAME, Path.home() / CONFIG_FILENAME):
        if candidate.is_file():
            return candidate
    return None


def load_config() -> dict[str, str]:
    """
    Load config from disk and return a flat dict of string values.
    Missing keys are filled from _DEFAULTS.
    """
    cfg = configparser.ConfigParser(defaults=_DEFAULTS)
    cfg.read_dict({"dedup": _DEFAULTS})

    config_path = _find_config()
    if config_path:
        cfg.read(config_path)

    section = cfg["dedup"]
    return {
        "algorithm":   section.get("algorithm",   _DEFAULTS["algorithm"]),
        "min_size":    section.get("min_size",    _DEFAULTS["min_size"]),
        "extensions":  section.get("extensions",  _DEFAULTS["extensions"]),
        "ignore_dirs": section.get("ignore_dirs", _DEFAULTS["ignore_dirs"]),
        "disposal":    section.get("disposal",    _DEFAULTS["disposal"]),
        "sort_by":     section.get("sort_by",     _DEFAULTS["sort_by"]),
    }


def parse_list(value: str) -> list[str]:
    """Split a comma-separated config value into a cleaned list."""
    return [v.strip() for v in value.split(",") if v.strip()]


def write_example_config(dest: Path) -> None:
    """Write a commented example .deduprc to *dest*."""
    dest.write_text("""\
[dedup]
# Hash algorithm: md5 (faster) or sha256 (safer)
algorithm = sha256

# Skip files smaller than this many bytes (0 = include everything)
min_size = 1

# Comma-separated extension whitelist (leave blank for all types)
# extensions = .jpg,.png,.pdf,.mp4

# Extra directory names to skip (added to the built-in ignore list)
# ignore_dirs = build,dist,tmp

# Default disposal mode: delete | trash | hardlink | symlink
disposal = trash

# Sort duplicate groups by: size | count | path
sort_by = size
""")
