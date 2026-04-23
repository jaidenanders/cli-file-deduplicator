# 🗂 CLI File Deduplicator

> A fast, safe, and fully-featured command-line tool for finding and cleaning duplicate files — built for real-world use, not demos.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Tests](https://img.shields.io/badge/Tests-69%20passing-brightgreen?style=flat-square)
![Version](https://img.shields.io/badge/Version-1.1.0-orange?style=flat-square)

---

## What it does

`dedup` recursively scans any directory, identifies duplicate files using cryptographic hashing, and walks you through reviewing and cleaning them — all from the terminal. It's fast, it's safe, and it never deletes anything without asking.

```
dedup ~/Downloads
```

---

## Features

### 🔍 Smart Detection
- **Three-pass hashing pipeline** — groups files by size first (free), then partial hash (4 KB read), then full hash. Only true duplicates ever get a full read, making it fast on large trees.
- **Hardlink detection** — files sharing the same inode are never flagged as duplicates. They already share disk blocks; deleting one would silently destroy the other.
- **Auto-ignore** — skips `.git`, `node_modules`, `__pycache__`, `.venv`, and other noisy directories by default.
- **Extension & size filters** — scan only specific file types or skip files below a size threshold.

### 🛡️ Four Disposal Modes

| Mode | What happens |
|------|-------------|
| `delete` | Permanent removal |
| `trash` | Move to OS trash — recoverable |
| `hardlink` | Replace duplicates with hardlinks to the kept copy |
| `symlink` | Replace duplicates with symlinks to the kept copy |

### 🎛️ Flexible Keep Logic
- `--keep-newest` — auto-keep the most recently modified copy
- `--keep-oldest` — auto-keep the oldest copy
- `--keep-path DIR` — always keep copies inside a specific directory

### 📊 Reporting
- `--export-json` — machine-readable report of all duplicate groups
- `--export-csv` — flat CSV, one row per file copy
- `--undo-log` — timestamped JSON log of everything acted on
- ASCII bar chart showing which directories hold the most duplicate weight

### ⚙️ Config File
Persist your preferred defaults in a `.deduprc` file. CLI flags always win.

---

## Installation

```bash
pip install cli-file-deduplicator
```

Or install from source for development:

```bash
git clone https://github.com/YOUR_USERNAME/cli-file-deduplicator.git
cd cli-file-deduplicator
pip install -e ".[dev]"
```

**Requires Python 3.10+**

---

## Usage

```
dedup [OPTIONS] DIRECTORY
```

### Examples

```bash
# Interactive review — safest starting point
dedup ~/Downloads

# Preview everything, touch nothing
dedup ~/Downloads --dry-run

# Move duplicates to trash instead of deleting
dedup ~/Downloads --disposal trash

# Replace duplicates with hardlinks (saves space, keeps all paths alive)
dedup ~/Downloads --disposal hardlink --keep-newest

# Scan only images, skip files under 100 KB
dedup ~/Pictures -e .jpg -e .png -e .heic --min-size 102400

# Export a full report without interactive review
dedup ~/Documents --export-json report.json --export-csv report.csv

# Auto-keep any copy inside ~/Originals, trash the rest
dedup ~/Pictures --keep-path ~/Originals --disposal trash

# Generate a .deduprc config file with all available options
dedup --init-config
```

### All Options

| Flag | Default | Description |
|------|---------|-------------|
| `--algorithm`, `-a` | `sha256` | Hash algorithm: `md5` (faster) or `sha256` (safer) |
| `--ext`, `-e` | *(all)* | Restrict to file extension — repeatable |
| `--min-size`, `-s` | `1` | Skip files smaller than N bytes |
| `--ignore-dir` | — | Extra directory name to skip — repeatable |
| `--disposal`, `-d` | `delete` | `delete` \| `trash` \| `hardlink` \| `symlink` |
| `--keep-newest` | off | Auto-keep the most recently modified copy |
| `--keep-oldest` | off | Auto-keep the oldest copy |
| `--keep-path DIR` | — | Always keep copies inside DIR |
| `--sort-by` | `size` | Order groups by `size` \| `count` \| `path` |
| `--dry-run`, `-n` | off | Preview only — no files are modified |
| `--export-json FILE` | — | Write JSON duplicate report |
| `--export-csv FILE` | — | Write CSV duplicate report |
| `--undo-log FILE` | — | Write JSON log of acted-on files |
| `--chart / --no-chart` | on | Show ASCII bar chart of waste by directory |
| `--init-config` | — | Write an example `.deduprc` and exit |
| `--version`, `-V` | — | Show version and exit |

---

## How it works

```
DIRECTORY
    │
    ▼
Recursive file walk
  Skips: symlinks, hidden dirs, node_modules, __pycache__, .git, etc.
    │
    ▼
Pass 1 — Group by file size       (stat only — zero disk reads)
    │
    ▼
Pass 2 — Partial hash (4 KB)      (tiny read, eliminates most collisions)
    │
    ▼
Pass 3 — Full hash                (only for true duplicate candidates)
    │
    ▼
Hardlink deduplication
  Collapse paths sharing the same inode — they're already sharing blocks
    │
    ▼
Interactive review (or auto-mode with --keep-* flags)
  Per group: pick which copies to act on, or batch with 'a'
    │
    ▼
Disposal: delete | trash | hardlink | symlink
    │
    ▼
Summary report + optional JSON/CSV export + undo log
```

---

## Config File

Run `dedup --init-config` to generate a `.deduprc` in your current directory:

```ini
[dedup]
# Hash algorithm: md5 (faster) or sha256 (safer)
algorithm = sha256

# Skip files smaller than this many bytes
min_size = 1

# Comma-separated extension whitelist (blank = all types)
# extensions = .jpg,.png,.pdf

# Default disposal mode
disposal = trash

# Sort duplicate groups by: size | count | path
sort_by = size
```

The tool searches for `.deduprc` in the current directory first, then your home directory. CLI flags always override config values.

---

## Shell Completion

Click generates shell completion automatically:

```bash
# Bash
_DEDUP_COMPLETE=bash_source dedup > ~/.dedup-complete.bash
echo '. ~/.dedup-complete.bash' >> ~/.bashrc

# Zsh
_DEDUP_COMPLETE=zsh_source dedup > ~/.dedup-complete.zsh
echo '. ~/.dedup-complete.zsh' >> ~/.zshrc

# Fish
_DEDUP_COMPLETE=fish_source dedup > ~/.config/fish/completions/dedup.fish
```

---

## Project Structure

```
cli-file-deduplicator/
├── dedup/
│   ├── __init__.py       Package entry
│   ├── __main__.py       CLI — Click commands and orchestration
│   ├── core.py           Scanning, hashing, duplicate detection
│   ├── actions.py        Disposal backends, keeper selection, undo log
│   ├── display.py        Rich UI — tables, panels, interactive prompts
│   ├── reporter.py       JSON/CSV export and ASCII bar chart
│   └── config.py         .deduprc loading and default merging
├── tests/
│   ├── conftest.py        Shared fixtures
│   ├── test_core.py       Scanning and hashing tests
│   ├── test_actions.py    Disposal and keeper selection tests
│   ├── test_reporter.py   Export and chart tests
│   └── test_config.py     Config loading tests
└── pyproject.toml
```

---

## Running Tests

```bash
# Run all 69 tests
pytest

# With coverage report
pytest --cov=dedup --cov-report=term-missing

# Run a specific module
pytest tests/test_core.py -v
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| [click](https://click.palletsprojects.com/) | CLI framework |
| [rich](https://rich.readthedocs.io/) | Terminal UI — tables, progress bars, panels |
| [send2trash](https://github.com/arsenetar/send2trash) | Cross-platform OS trash support |

---

## License

MIT
