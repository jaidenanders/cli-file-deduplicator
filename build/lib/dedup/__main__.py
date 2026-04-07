#!/usr/bin/env python3
"""
dedup.py — CLI entry point for the File Deduplicator.

Usage examples
--------------
  python dedup.py ~/Downloads                        # interactive review
  python dedup.py ~/Downloads --dry-run              # preview only
  python dedup.py ~/Downloads --disposal trash       # move to OS trash
  python dedup.py ~/Downloads --disposal hardlink    # replace with hardlinks
  python dedup.py ~/Downloads --keep-newest          # auto-keep newest copy
  python dedup.py ~/Downloads --keep-path ~/orig     # always keep copies here
  python dedup.py ~/Downloads --ext .jpg --ext .png  # images only
  python dedup.py ~/Downloads --min-size 10240       # skip files < 10 KB
  python dedup.py ~/Downloads --sort-by count        # largest groups first
  python dedup.py ~/Downloads --export-json out.json # export report
  python dedup.py ~/Downloads --export-csv  out.csv
  python dedup.py --init-config                      # write example .deduprc
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from dedup.actions import (
    DISPOSAL_MODES,
    apply_disposal,
    select_keeper,
    write_undo_log,
)
from dedup.config import load_config, parse_list, write_example_config
from dedup.core import DEFAULT_IGNORE_DIRS, find_duplicates, duplicate_stats
from dedup.display import (
    console,
    fmt_bytes,
    print_banner,
    print_final_report,
    print_no_duplicates,
    print_scan_summary,
    review_group,
)
from dedup.reporter import export_csv, export_json, render_dir_chart


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

def _sort_groups(
    duplicates: dict[str, list[Path]],
    sort_by: str,
) -> list[tuple[str, list[Path]]]:
    items = list(duplicates.items())
    if sort_by == "count":
        items.sort(key=lambda kv: len(kv[1]), reverse=True)
    elif sort_by == "path":
        items.sort(key=lambda kv: str(kv[1][0]))
    else:  # size (default)
        items.sort(
            key=lambda kv: kv[1][0].stat().st_size if kv[1] else 0,
            reverse=True,
        )
    return items


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument(
    "directory",
    required=False,
    type=click.Path(exists=True, file_okay=False, readable=True, path_type=Path),
)
# ── Scan options ─────────────────────────────────────────────────────────────
@click.option(
    "--algorithm", "-a",
    default=None,
    type=click.Choice(["md5", "sha256"], case_sensitive=False),
    help="Hash algorithm. MD5 is faster; SHA-256 is safer. [default: sha256]",
)
@click.option(
    "--ext", "-e",
    "extensions",
    multiple=True,
    metavar="EXT",
    help="Restrict to extension (repeatable), e.g. -e .jpg -e .png",
)
@click.option(
    "--min-size", "-s",
    default=None,
    type=int,
    metavar="BYTES",
    help="Skip files smaller than BYTES. [default: 1]",
)
@click.option(
    "--ignore-dir",
    "extra_ignore_dirs",
    multiple=True,
    metavar="NAME",
    help="Extra directory name to ignore (repeatable).",
)
# ── Disposal options ──────────────────────────────────────────────────────────
@click.option(
    "--disposal", "-d",
    default=None,
    type=click.Choice(DISPOSAL_MODES, case_sensitive=False),
    help="What to do with duplicates: delete|trash|hardlink|symlink. [default: delete]",
)
@click.option(
    "--keep-newest",
    is_flag=True,
    default=False,
    help="Automatically keep the most recently modified copy.",
)
@click.option(
    "--keep-oldest",
    is_flag=True,
    default=False,
    help="Automatically keep the oldest copy.",
)
@click.option(
    "--keep-path",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    metavar="DIR",
    help="Always keep copies located inside DIR; act on the rest.",
)
# ── UX options ────────────────────────────────────────────────────────────────
@click.option(
    "--sort-by",
    default=None,
    type=click.Choice(["size", "count", "path"], case_sensitive=False),
    help="Order duplicate groups by size|count|path. [default: size]",
)
@click.option(
    "--dry-run", "-n",
    is_flag=True,
    default=False,
    help="Preview what would happen — no files are modified.",
)
# ── Output options ────────────────────────────────────────────────────────────
@click.option(
    "--export-json",
    default=None,
    type=click.Path(path_type=Path),
    metavar="FILE",
    help="Write a JSON duplicate report to FILE.",
)
@click.option(
    "--export-csv",
    default=None,
    type=click.Path(path_type=Path),
    metavar="FILE",
    help="Write a CSV duplicate report to FILE.",
)
@click.option(
    "--undo-log",
    default=None,
    type=click.Path(path_type=Path),
    metavar="FILE",
    help="Write a JSON undo log of all acted-on files.",
)
@click.option(
    "--chart/--no-chart",
    default=True,
    help="Show an ASCII bar chart of duplicate waste by directory.",
)
# ── Config helpers ────────────────────────────────────────────────────────────
@click.option(
    "--init-config",
    is_flag=True,
    default=False,
    is_eager=True,
    help="Write an example .deduprc to the current directory and exit.",
)
@click.version_option("1.1.0", "--version", "-V")
def main(
    directory: Path | None,
    algorithm: str | None,
    extensions: tuple[str, ...],
    min_size: int | None,
    extra_ignore_dirs: tuple[str, ...],
    disposal: str | None,
    keep_newest: bool,
    keep_oldest: bool,
    keep_path: Path | None,
    sort_by: str | None,
    dry_run: bool,
    export_json: Path | None,
    export_csv: Path | None,
    undo_log: Path | None,
    chart: bool,
    init_config: bool,
) -> None:
    """
    \b
    🗂  CLI File Deduplicator
    Recursively scan DIRECTORY for duplicate files, then review and clean them.
    """
    # ── --init-config shortcut ────────────────────────────────────────────────
    if init_config:
        dest = Path.cwd() / ".deduprc"
        write_example_config(dest)
        console.print(f"[green]✓[/green] Example config written to [bold]{dest}[/bold]")
        console.print("[dim]Edit it to set your preferred defaults.[/dim]")
        raise SystemExit(0)

    if directory is None:
        console.print("[red]Error:[/red] DIRECTORY argument is required.")
        raise SystemExit(1)

    # ── Load config, apply CLI overrides ──────────────────────────────────────
    cfg = load_config()

    resolved_algorithm  = algorithm  or cfg["algorithm"]
    resolved_min_size   = min_size   if min_size  is not None else int(cfg["min_size"])
    resolved_disposal   = disposal   or cfg["disposal"]
    resolved_sort_by    = sort_by    or cfg["sort_by"]

    cfg_extensions = parse_list(cfg["extensions"])
    ext_filter: list[str] | None = None
    all_exts = list(extensions) + cfg_extensions
    if all_exts:
        ext_filter = [e if e.startswith(".") else f".{e}" for e in all_exts]

    cfg_ignore = parse_list(cfg["ignore_dirs"])
    ignore_dirs = DEFAULT_IGNORE_DIRS | frozenset(extra_ignore_dirs) | frozenset(cfg_ignore)

    # ── Validate conflicting flags ────────────────────────────────────────────
    if sum([keep_newest, keep_oldest, keep_path is not None]) > 1:
        console.print("[red]Error:[/red] --keep-newest, --keep-oldest, and --keep-path are mutually exclusive.")
        raise SystemExit(1)

    # ── Print banner + config summary ─────────────────────────────────────────
    print_banner()

    if ext_filter:
        console.print(f"[dim]Extensions:[/dim] {', '.join(ext_filter)}")
    if resolved_min_size > 1:
        console.print(f"[dim]Min size:[/dim] {fmt_bytes(resolved_min_size)}")
    if dry_run:
        console.print("[bold yellow]DRY-RUN — nothing will be modified.[/bold yellow]")
    if keep_newest:
        console.print("[dim]Auto-keep:[/dim] newest copy")
    if keep_oldest:
        console.print("[dim]Auto-keep:[/dim] oldest copy")
    if keep_path:
        console.print(f"[dim]Auto-keep path:[/dim] {keep_path}")
    console.print()

    # ── Phase 1 + 2 + 3: Scan ─────────────────────────────────────────────────
    hashed_count = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        MofNCompleteColumn(),
        BarColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(f"Scanning [bold]{directory}[/bold] …", total=None)

        def _progress_cb(path: Path) -> None:
            nonlocal hashed_count
            hashed_count += 1
            progress.update(task, description=f"Hashing [dim]{path.name}[/dim]", advance=1)

        duplicates, total_files, error_count = find_duplicates(
            directory,
            algorithm=resolved_algorithm,
            extensions=ext_filter,
            min_size=resolved_min_size,
            ignore_dirs=ignore_dirs,
            progress_cb=_progress_cb,
        )

    stats = duplicate_stats(duplicates)
    print_scan_summary(
        directory, total_files, error_count, stats,
        resolved_algorithm, resolved_disposal, dry_run,
    )

    # ── Export reports (regardless of whether user reviews) ──────────────────
    if export_json:
        export_json_path = Path(export_json)
        from dedup.reporter import export_json as _ej
        _ej(duplicates, stats, export_json_path)
        console.print(f"[green]✓[/green] JSON report written to [bold]{export_json_path}[/bold]")

    if export_csv:
        export_csv_path = Path(export_csv)
        from dedup.reporter import export_csv as _ec
        _ec(duplicates, export_csv_path)
        console.print(f"[green]✓[/green] CSV report written to  [bold]{export_csv_path}[/bold]")

    if not duplicates:
        print_no_duplicates()
        return

    # ── Phase 2: Interactive review ───────────────────────────────────────────
    sorted_groups = _sort_groups(duplicates, resolved_sort_by)
    acted_files:  list[Path] = []
    freed_bytes:  int = 0

    auto_mode = keep_newest or keep_oldest or (keep_path is not None)

    for i, (digest, paths) in enumerate(sorted_groups, 1):
        # Determine keeper for auto modes
        pre_keeper: Path | None = None
        if auto_mode:
            pre_keeper, _ = select_keeper(
                paths,
                keep_newest=keep_newest,
                keep_oldest=keep_oldest,
                keep_path=keep_path,
            )

        try:
            chosen_keeper, to_act = review_group(
                index=i,
                total_groups=len(sorted_groups),
                digest=digest,
                paths=paths,
                dry_run=dry_run,
                disposal=resolved_disposal,
                keeper=pre_keeper,
            )
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Interrupted.[/yellow]")
            break

        if not to_act:
            console.print()
            continue

        # Apply disposal to each selected path
        for path in to_act:
            try:
                size = path.stat().st_size
            except OSError:
                size = 0

            ok, msg = apply_disposal(path, resolved_disposal, keeper=chosen_keeper)
            if ok:
                acted_files.append(path)
                if resolved_disposal in ("delete", "trash"):
                    freed_bytes += size
                console.print(f"  [green]✓[/green] {msg}")
            else:
                console.print(f"  [red]✗[/red] {msg}")

        console.print()

    # ── Undo log ──────────────────────────────────────────────────────────────
    undo_log_path: Path | None = None
    if undo_log and acted_files and not dry_run:
        undo_log_path = Path(undo_log)
        write_undo_log(undo_log_path, acted_files, resolved_disposal)

    # ── Dir chart ─────────────────────────────────────────────────────────────
    chart_str: str | None = None
    if chart and duplicates:
        from dedup.reporter import render_dir_chart
        chart_str = render_dir_chart(duplicates)

    # ── Final report ──────────────────────────────────────────────────────────
    print_final_report(
        acted=acted_files,
        freed_bytes=freed_bytes,
        dry_run=dry_run,
        disposal=resolved_disposal,
        undo_log=undo_log_path,
        chart=chart_str,
    )


if __name__ == "__main__":
    main()
