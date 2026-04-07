"""
display.py — Rich-powered UI helpers.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

console = Console()


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_hash(h: str, length: int = 12) -> str:
    return f"[dim]{h[:length]}…[/dim]"


def fmt_mtime(path: Path) -> str:
    try:
        ts = path.stat().st_mtime
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return "?"


# ---------------------------------------------------------------------------
# Banner / summary
# ---------------------------------------------------------------------------

def print_banner() -> None:
    console.print(Panel.fit(
        "[bold cyan]🗂  CLI File Deduplicator[/bold cyan]\n"
        "[dim]Scan · Compare · Clean[/dim]",
        border_style="cyan",
    ))
    console.print()


def print_scan_summary(
    directory: Path,
    total_files: int,
    error_count: int,
    stats: dict,
    algorithm: str,
    disposal: str,
    dry_run: bool,
) -> None:
    table = Table(box=box.ROUNDED, show_header=False, border_style="dim")
    table.add_column(style="bold", no_wrap=True)
    table.add_column()

    table.add_row("Directory",        str(directory.resolve()))
    table.add_row("Algorithm",        algorithm.upper())
    table.add_row("Disposal mode",    disposal + (" [yellow](dry-run)[/yellow]" if dry_run else ""))
    table.add_row("Files scanned",    str(total_files))
    table.add_row("Scan errors",      f"[red]{error_count}[/red]" if error_count else "0")
    table.add_row("Duplicate groups", str(stats["groups"]))
    table.add_row("Redundant files",  str(stats["duplicate_files"]))
    table.add_row("Reclaimable",      f"[green]{fmt_bytes(stats['wasted_bytes'])}[/green]")

    console.print(Panel(table, title="[bold]Scan Results[/bold]", border_style="cyan"))
    console.print()


def print_no_duplicates() -> None:
    console.print(Panel(
        "[green]✓  No duplicate files found.[/green]",
        border_style="green",
    ))


# ---------------------------------------------------------------------------
# Per-group interactive review
# ---------------------------------------------------------------------------

_REVIEW_HELP = (
    "[dim]"
    "Enter comma-separated file numbers to act on  |  "
    "[bold]a[/bold]=auto (keep first, act on rest)  |  "
    "[bold]k[/bold]=keep all  |  "
    "[bold]q[/bold]=quit"
    "[/dim]"
)


def review_group(
    index: int,
    total_groups: int,
    digest: str,
    paths: list[Path],
    dry_run: bool,
    disposal: str,
    keeper: Path | None = None,     # pre-selected keeper (auto modes)
) -> tuple[Path | None, list[Path]]:
    """
    Display one duplicate group and prompt the user.

    Returns (keeper_path, [paths_to_act_on]).
    keeper_path is None when the user skips the group.
    """
    console.rule(
        f"[bold]Group {index}/{total_groups}[/bold]  "
        f"{fmt_hash(digest)}  "
        f"([dim]{len(paths)} copies · {fmt_bytes(paths[0].stat().st_size if paths else 0)}[/dim])"
    )

    table = Table(box=box.SIMPLE_HEAVY, show_lines=False)
    table.add_column("#",        style="bold cyan", width=3)
    table.add_column("Path",     style="white")
    table.add_column("Size",     style="green",  justify="right", no_wrap=True)
    table.add_column("Modified", style="yellow", justify="right", no_wrap=True)

    # Mark pre-selected keeper
    for i, p in enumerate(paths, 1):
        try:
            size = fmt_bytes(p.stat().st_size)
        except OSError:
            size = "?"
        mtime  = fmt_mtime(p)
        marker = " [bold green]★ keep[/bold green]" if (keeper and p == keeper) else ""
        table.add_row(str(i), str(p) + marker, size, mtime)

    console.print(table)
    console.print(_REVIEW_HELP)
    answer = Prompt.ask("[bold cyan]>[/bold cyan]", default="k").strip().lower()

    if answer == "q":
        raise SystemExit(0)

    if answer in ("k", ""):
        return None, []

    # Auto: keep pre-selected keeper (or first), act on rest
    if answer == "a":
        chosen_keeper = keeper or paths[0]
        to_act = [p for p in paths if p != chosen_keeper]
        return chosen_keeper, _confirm_act(to_act, dry_run, disposal)

    # Manual selection
    selected: list[Path] = []
    for token in answer.split(","):
        token = token.strip()
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(paths):
                selected.append(paths[idx])

    if not selected:
        return None, []

    # Safety: must keep at least one copy
    if len(selected) >= len(paths):
        console.print("[yellow]⚠  Can't act on every copy — keeping the first one.[/yellow]")
        chosen_keeper = paths[0]
        selected = [p for p in selected if p != chosen_keeper]
    else:
        # Keeper = first path not in selected
        chosen_keeper = next(p for p in paths if p not in selected)

    return chosen_keeper, _confirm_act(selected, dry_run, disposal)


def _confirm_act(
    paths: list[Path],
    dry_run: bool,
    disposal: str,
) -> list[Path]:
    """Show what will happen and ask for confirmation (unless dry_run)."""
    if not paths:
        return []

    verb = {
        "delete":   "[red]Delete[/red]",
        "trash":    "[yellow]Trash[/yellow]",
        "hardlink": "[cyan]Hardlink[/cyan]",
        "symlink":  "[cyan]Symlink[/cyan]",
    }.get(disposal, disposal)

    console.print()
    for p in paths:
        console.print(f"  {verb}: {p}")

    if dry_run:
        console.print("[dim]  (dry-run — no action taken)[/dim]")
        return []

    if Confirm.ask(f"[bold]Proceed ({disposal})?[/bold]", default=False):
        return paths
    return []


# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------

def print_final_report(
    acted: list[Path],
    freed_bytes: int,
    dry_run: bool,
    disposal: str,
    undo_log: Path | None = None,
    chart: str | None = None,
) -> None:
    console.print()

    if dry_run:
        label = "[bold yellow]DRY-RUN complete[/bold yellow] — no files were modified."
    elif not acted:
        label = "[bold]No files acted on.[/bold]"
    else:
        verb = {
            "delete":   "Deleted",
            "trash":    "Trashed",
            "hardlink": "Hardlinked",
            "symlink":  "Symlinked",
        }.get(disposal, "Processed")
        label = (
            f"[bold green]Done![/bold green]  "
            f"{verb} [bold]{len(acted)}[/bold] file(s)"
        )
        if disposal in ("delete", "trash"):
            label += f", freed [bold green]{fmt_bytes(freed_bytes)}[/bold green]"

    console.print(Panel(label, border_style="green" if not dry_run else "yellow"))

    if acted:
        t = Table(title="Files Processed", box=box.MINIMAL_DOUBLE_HEAD)
        t.add_column("File", style="red" if disposal == "delete" else "yellow")
        for p in acted:
            t.add_row(str(p))
        console.print(t)

    if undo_log:
        console.print(f"\n[dim]Undo log written to:[/dim] {undo_log}")

    if chart:
        console.print(chart)
