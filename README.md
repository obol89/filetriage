# FileTriage

Interactive TUI for reviewing and deleting old files and directories on Linux, Windows, and macOS.

## Features

- Recursively scans one or more directories for old files and subdirectories
- Filters items by last accessed time (or modification time on Windows when atime is disabled)
- Presents items one at a time, sorted oldest-first, with full metadata
- Keep, delete, or defer each item with a single keypress
- Super delete to remove an entire parent directory at once
- Confirmation prompt before deleting non-empty directories
- Dry-run mode to simulate deletions without removing anything
- Real-time freed space counter
- Interactive startup screen for configuring scan paths, age threshold, and dry-run toggle
- Optional CLI arguments to pre-fill the startup screen for scripting
- Graceful handling of permission errors on all platforms
- Builds to a single portable binary via PyInstaller

## Requirements

- Python 3.8+
- [textual](https://github.com/Textualize/textual)

## Installation

```sh
git clone https://codeberg.org/porana/filetriage.git
cd filetriage
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

On Windows, replace `.venv/bin/pip` with `.venv\Scripts\pip`.

## Usage

```sh
# Linux / macOS
.venv/bin/python filetriage.py

# Windows
.venv\Scripts\python filetriage.py
```

The app opens an interactive startup screen where you configure directories to scan, minimum file age, and dry-run mode before scanning begins.

Optional CLI arguments pre-fill the startup screen values:

```sh
.venv/bin/python filetriage.py /path/one /path/two --min-age 60 --dry-run
```

| Argument    | Description                                    | Default |
|-------------|------------------------------------------------|---------|
| `paths`     | Directories to scan (positional, zero or more) | —       |
| `--min-age` | Minimum age in days based on last access time  | 30      |
| `--dry-run` | Pre-enable dry-run mode                        | off     |

## Releases

Pre-built binaries for Linux, Windows, and macOS are available on the [Releases](https://codeberg.org/porana/filetriage/releases) page. Download the binary for your platform and run it directly — no Python installation required.

## Building from source

Install PyInstaller (included in `requirements.txt`) and run:

```sh
.venv/bin/python build.py
```

The script detects your OS and produces a single-file binary in `dist/`:

| Platform | Output                |
|----------|-----------------------|
| Linux    | `dist/filetriage`     |
| macOS    | `dist/filetriage`     |
| Windows  | `dist\filetriage.exe` |

## CI/CD

GitHub Actions automatically builds binaries for Linux, Windows, and macOS on each version tag push (e.g. `v1.0.0`). All three binaries are attached to the corresponding GitHub Release.

## Keyboard shortcuts

| Key | Action                                   |
|-----|------------------------------------------|
| `d` | Delete the current item                  |
| `D` | Super delete — remove the parent directory |
| `k` | Keep the current item                    |
| `l` | Defer to later (re-queue to the end)     |
| `q` | Quit and show summary                    |

When deleting a non-empty directory, press `Enter` to confirm or `Esc` to cancel.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
