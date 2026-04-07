"""
reporter.py — Export duplicate reports and render ASCII space charts.
"""

from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Formatting helpers (shared with display.py but kept independent)
# ---------------------------------------------------------------------------

def fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_json(
    duplicates: dict[str, list[Path]],
    stats: dict,
    output_path: Path,
) -> None:
    """
    Write a machine-readable JSON report of all duplicate groups.

    Schema:
      {
        "summary": { groups, duplicate_files, wasted_bytes, wasted_human },
        "groups":  [
          {
            "hash": "...",
            "file_size": 12345,
            "copies": ["path/a", "path/b", ...]
          },
          ...
        ]
      }
    """
    groups_data = []
    for digest, paths in duplicates.items():
        try:
            size = paths[0].stat().st_size
        except OSError:
            size = 0
        groups_data.append({
            "hash":      digest,
            "file_size": size,
            "copies":    [str(p) for p in paths],
        })

    report = {
        "summary": {
            **stats,
            "wasted_human": fmt_bytes(stats["wasted_bytes"]),
        },
        "groups": sorted(groups_data, key=lambda g: g["file_size"], reverse=True),
    }

    output_path.write_text(json.dumps(report, indent=2))


def export_csv(
    duplicates: dict[str, list[Path]],
    output_path: Path,
) -> None:
    """
    Write a flat CSV where every row is one file path in a duplicate group.

    Columns: hash, file_size, copy_index, path
    """
    with output_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["hash", "file_size", "copy_index", "path"])
        for digest, paths in sorted(
            duplicates.items(),
            key=lambda kv: kv[1][0].stat().st_size if kv[1] else 0,
            reverse=True,
        ):
            try:
                size = paths[0].stat().st_size
            except OSError:
                size = 0
            for i, p in enumerate(paths):
                writer.writerow([digest, size, i, str(p)])


# ---------------------------------------------------------------------------
# ASCII bar chart — duplicate weight by directory
# ---------------------------------------------------------------------------

def _dir_waste(duplicates: dict[str, list[Path]]) -> dict[str, int]:
    """
    For each duplicate group, attribute the wasted bytes to the parent
    directories of the *extra* copies (all but the first).
    """
    waste: dict[str, int] = defaultdict(int)
    for paths in duplicates.values():
        if not paths:
            continue
        try:
            size = paths[0].stat().st_size
        except OSError:
            continue
        for extra in paths[1:]:
            waste[str(extra.parent)] += size
    return dict(waste)


def render_dir_chart(
    duplicates: dict[str, list[Path]],
    top_n: int = 10,
    bar_width: int = 40,
) -> str:
    """
    Return a multi-line ASCII bar chart showing the top *top_n* directories
    by duplicate waste, suitable for printing to a terminal.
    """
    waste = _dir_waste(duplicates)
    if not waste:
        return "  (no duplicate waste to chart)"

    ranked = sorted(waste.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    max_bytes = ranked[0][1]

    # Truncate long directory paths for display
    def _short(path_str: str, maxlen: int = 40) -> str:
        if len(path_str) <= maxlen:
            return path_str
        return "…" + path_str[-(maxlen - 1):]

    lines: list[str] = ["", "  Duplicate waste by directory:", ""]
    for dir_str, bytes_wasted in ranked:
        filled = int(bar_width * bytes_wasted / max_bytes)
        bar    = "█" * filled + "░" * (bar_width - filled)
        label  = _short(dir_str).ljust(42)
        lines.append(f"  {label} [{bar}] {fmt_bytes(bytes_wasted)}")

    lines.append("")
    return "\n".join(lines)
