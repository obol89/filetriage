#!/usr/bin/env python3
"""FileTriage - Interactive TUI for reviewing and deleting old files and directories."""

import argparse
import os
import platform
import shutil
import sys
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Header, Input, Label, Static, Switch


# ── Utility functions ────────────────────────────────────────────────────────


def human_size(nbytes: int) -> str:
    """Convert bytes to human-readable size string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} PB"


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _detect_atime_disabled(roots: list[str]) -> bool:
    """On Windows, sample files to check if atime tracking appears disabled."""
    if not _is_windows():
        return False
    matches = 0
    checked = 0
    for root in roots:
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            continue
        try:
            for entry in root_path.rglob("*"):
                if not entry.is_file():
                    continue
                try:
                    st = entry.stat()
                    checked += 1
                    if st.st_atime == st.st_mtime:
                        matches += 1
                    if checked >= 50:
                        break
                except OSError:
                    continue
        except OSError:
            continue
        if checked >= 50:
            break
    if checked == 0:
        return False
    return (matches / checked) > 0.9


def _get_file_time(st: os.stat_result, use_mtime: bool) -> float:
    """Get the relevant timestamp from a stat result."""
    return st.st_mtime if use_mtime else st.st_atime


def get_atime(path: Path, use_mtime: bool = False) -> float:
    """Get access time (or mtime fallback) of a path, returning 0 on error."""
    try:
        st = path.stat()
        return _get_file_time(st, use_mtime)
    except OSError:
        return 0.0


def dir_stats(path: Path, use_mtime: bool = False) -> tuple[int, int, float]:
    """Return (item_count, total_size, oldest_time) for a directory's contents."""
    count = 0
    total = 0
    oldest = float("inf")
    try:
        for entry in path.rglob("*"):
            try:
                st = entry.stat()
                count += 1
                if entry.is_file():
                    total += st.st_size
                t = _get_file_time(st, use_mtime)
                if t < oldest:
                    oldest = t
            except OSError:
                continue
    except OSError:
        pass
    if oldest == float("inf"):
        oldest = get_atime(path, use_mtime)
    return count, total, oldest


def scan_paths(
    roots: list[str],
    min_age_days: int,
    warnings: list[str],
    use_mtime: bool = False,
) -> list[dict]:
    """Scan directories and collect items older than min_age days."""
    cutoff = datetime.now().timestamp() - (min_age_days * 86400)
    files: list[dict] = []
    dirs: list[dict] = []

    for root in roots:
        root_path = Path(root).resolve()
        if not root_path.exists():
            warnings.append(f"Path does not exist: {root_path}")
            continue
        if not root_path.is_dir():
            warnings.append(f"Not a directory: {root_path}")
            continue

        try:
            for entry in root_path.rglob("*"):
                try:
                    if entry.is_file():
                        st = entry.stat()
                        t = _get_file_time(st, use_mtime)
                        if t < cutoff:
                            files.append(
                                {
                                    "path": entry,
                                    "type": "file",
                                    "size": st.st_size,
                                    "atime": t,
                                    "extension": entry.suffix or "(none)",
                                }
                            )
                    elif entry.is_dir():
                        count, total, oldest = dir_stats(entry, use_mtime)
                        if oldest < cutoff:
                            dirs.append(
                                {
                                    "path": entry,
                                    "type": "directory",
                                    "size": total,
                                    "atime": oldest,
                                    "item_count": count,
                                    "empty": count == 0,
                                }
                            )
                except PermissionError:
                    warnings.append(f"Permission denied: {entry}")
                except OSError as e:
                    warnings.append(f"Error accessing {entry}: {e}")
        except PermissionError:
            warnings.append(f"Permission denied scanning: {root_path}")
        except OSError as e:
            warnings.append(f"Error scanning {root_path}: {e}")

    files.sort(key=lambda x: x["atime"])
    dirs.sort(key=lambda x: x["atime"])
    return files + dirs


# ── Textual Widgets ──────────────────────────────────────────────────────────


class DryRunBanner(Static):
    """Banner shown when dry-run mode is active."""

    def render(self) -> str:
        return "DRY-RUN MODE — no files will be deleted"

    DEFAULT_CSS = """
    DryRunBanner {
        background: $warning;
        color: $text;
        text-align: center;
        text-style: bold;
        padding: 0 1;
        dock: top;
        width: 100%;
    }
    """


class MtimeBanner(Static):
    """Banner shown when falling back to mtime on Windows."""

    def render(self) -> str:
        return (
            "atime tracking appears disabled — "
            "using modification time (mtime) instead"
        )

    DEFAULT_CSS = """
    MtimeBanner {
        background: $primary;
        color: $text;
        text-align: center;
        text-style: bold;
        padding: 0 1;
        dock: top;
        width: 100%;
    }
    """


class WarningPanel(Static):
    """Shows scan warnings."""

    DEFAULT_CSS = """
    WarningPanel {
        background: $error 20%;
        color: $warning;
        padding: 0 1;
        margin: 0 1;
        max-height: 6;
        overflow-y: auto;
    }
    """


class ItemDisplay(Static):
    """Displays details for the current item."""

    DEFAULT_CSS = """
    ItemDisplay {
        padding: 1 2;
        margin: 1 2;
        border: solid $accent;
        height: auto;
    }
    """


class ConfirmOverlay(Static):
    """Confirmation overlay for non-empty directory deletion."""

    DEFAULT_CSS = """
    ConfirmOverlay {
        background: $error 40%;
        color: $text;
        text-align: center;
        text-style: bold;
        padding: 1 2;
        margin: 1 2;
        border: heavy $error;
        display: none;
    }
    """

    def render(self) -> str:
        return (
            "Delete this non-empty directory and ALL its contents?\n\n"
            "[enter] confirm    [esc] cancel"
        )


class KeyLegend(Static):
    """Keyboard legend at the bottom."""

    DEFAULT_CSS = """
    KeyLegend {
        dock: bottom;
        background: $surface;
        color: $text-muted;
        text-align: center;
        padding: 0 1;
    }
    """

    def render(self) -> str:
        return "[d] delete  [k] keep  [l] later  [q] quit"


# ── Startup Screen ───────────────────────────────────────────────────────────


class StartupScreen(Screen):
    """Interactive config screen shown before scanning."""

    BINDINGS = [
        Binding("escape", "quit_app", "Quit", show=False),
    ]

    DEFAULT_CSS = """
    StartupScreen {
        align: center middle;
    }
    #startup-box {
        width: 80;
        height: auto;
        border: heavy $accent;
        padding: 2 4;
        background: $surface;
    }
    #startup-box Static {
        margin-bottom: 0;
    }
    .section-label {
        text-style: bold;
        margin-top: 1;
    }
    #path-list {
        margin: 0 2;
        height: auto;
        max-height: 8;
        color: $success;
    }
    #path-input {
        margin: 0 0 1 0;
    }
    #age-input {
        margin: 0 0 1 0;
        width: 20;
    }
    #dryrun-row {
        height: 3;
        margin: 0 0 1 0;
    }
    #dryrun-row Static {
        width: auto;
        margin-right: 2;
    }
    #start-hint {
        text-align: center;
        text-style: italic;
        color: $text-muted;
        margin-top: 1;
    }
    """

    def __init__(
        self,
        preset_paths: list[str] | None = None,
        preset_min_age: int = 30,
        preset_dry_run: bool = False,
    ) -> None:
        super().__init__()
        self.paths: list[str] = list(preset_paths) if preset_paths else []
        self.preset_min_age = preset_min_age
        self.preset_dry_run = preset_dry_run

    def compose(self) -> ComposeResult:
        with Vertical(id="startup-box"):
            yield Static("── FileTriage Setup ──")
            yield Static("")
            yield Static("Directories to scan:", classes="section-label")
            yield Static(self._path_list_text(), id="path-list")
            yield Input(
                placeholder="Enter directory path, then press Enter (empty to finish)",
                id="path-input",
            )
            yield Static("Minimum file age (days):", classes="section-label")
            yield Input(
                value=str(self.preset_min_age),
                id="age-input",
                type="integer",
            )
            yield Static("Dry-run mode:", classes="section-label")
            with Vertical(id="dryrun-row"):
                yield Switch(value=self.preset_dry_run, id="dryrun-switch")
            yield Static(
                "Press [ctrl+s] to start scanning  |  [esc] to quit",
                id="start-hint",
            )

    def _path_list_text(self) -> str:
        if not self.paths:
            return "(none added yet)"
        return "\n".join(f"  {p}" for p in self.paths)

    def _update_path_display(self) -> None:
        self.query_one("#path-list", Static).update(self._path_list_text())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "path-input":
            val = event.value.strip()
            if val:
                resolved = str(Path(val).resolve())
                self.paths.append(resolved)
                self._update_path_display()
                event.input.value = ""
            else:
                # Empty submit on path input — move focus to age input
                self.query_one("#age-input", Input).focus()
        elif event.input.id == "age-input":
            # Enter on age input — move focus to switch
            self.query_one("#dryrun-switch", Switch).focus()

    def on_key(self, event) -> None:
        if event.key == "ctrl+s":
            self._start_scan()

    def _start_scan(self) -> None:
        if not self.paths:
            self.notify("Add at least one directory to scan.", severity="warning")
            return

        age_input = self.query_one("#age-input", Input)
        try:
            min_age = int(age_input.value)
            if min_age < 0:
                raise ValueError
        except ValueError:
            self.notify("Min age must be a positive integer.", severity="error")
            return

        dry_run = self.query_one("#dryrun-switch", Switch).value
        self.dismiss((self.paths, min_age, dry_run))

    def action_quit_app(self) -> None:
        self.app.exit()


# ── Summary Screen ───────────────────────────────────────────────────────────


class SummaryScreen(Screen):
    """Final summary screen shown after all items are processed or on quit."""

    BINDINGS = [
        Binding("q", "quit_app", "Quit"),
        Binding("escape", "quit_app", "Quit"),
    ]

    DEFAULT_CSS = """
    SummaryScreen {
        align: center middle;
    }
    #summary-box {
        width: 60;
        height: auto;
        border: heavy $accent;
        padding: 2 4;
        background: $surface;
    }
    #summary-box Static {
        text-align: center;
        margin-bottom: 1;
    }
    .summary-stat {
        text-align: center;
    }
    """

    def __init__(
        self,
        deleted: int,
        kept: int,
        deferred: int,
        dry_run: bool,
    ) -> None:
        super().__init__()
        self.deleted = deleted
        self.kept = kept
        self.deferred = deferred
        self.dry_run = dry_run

    def compose(self) -> ComposeResult:
        with Vertical(id="summary-box"):
            yield Static("── FileTriage Summary ──", classes="summary-stat")
            if self.dry_run:
                yield Static(
                    "(DRY-RUN — nothing was actually deleted)",
                    classes="summary-stat",
                )
            yield Static("")
            yield Static(f"Deleted:  {self.deleted}", classes="summary-stat")
            yield Static(f"Kept:     {self.kept}", classes="summary-stat")
            yield Static(f"Deferred: {self.deferred}", classes="summary-stat")
            yield Static("")
            yield Static(
                "Press [q] or [esc] to exit", classes="summary-stat"
            )

    def action_quit_app(self) -> None:
        self.app.exit()


# ── Main App ─────────────────────────────────────────────────────────────────


class FileTriageApp(App):
    """Main FileTriage TUI application."""

    CSS = """
    #progress {
        text-align: center;
        text-style: bold;
        padding: 0 1;
        background: $primary;
        color: $text;
        dock: top;
        width: 100%;
    }
    #main-area {
        height: 1fr;
    }
    #scanning-msg {
        text-align: center;
        padding: 2;
        text-style: italic;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("d", "delete_item", "Delete", show=False),
        Binding("k", "keep_item", "Keep", show=False),
        Binding("l", "later_item", "Later", show=False),
        Binding("q", "quit_triage", "Quit", show=False),
        Binding("enter", "confirm_delete", "Confirm", show=False),
        Binding("escape", "cancel_delete", "Cancel", show=False),
    ]

    confirming = reactive(False)

    def __init__(
        self,
        preset_paths: list[str] | None = None,
        preset_min_age: int = 30,
        preset_dry_run: bool = False,
    ) -> None:
        super().__init__()
        self.preset_paths = preset_paths or []
        self.preset_min_age = preset_min_age
        self.preset_dry_run = preset_dry_run
        self.queue: list[dict] = []
        self.later_queue: list[dict] = []
        self.dry_run = preset_dry_run
        self.scan_warnings: list[str] = []
        self.use_mtime = False
        self.current_index = 0
        self.deleted = 0
        self.kept = 0
        self.deferred = 0
        self.total_initial = 0
        self.processing_later = False
        self.triage_started = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Label("", id="progress")
        with Vertical(id="main-area"):
            yield ItemDisplay("")
            yield ConfirmOverlay()
        yield KeyLegend()

    def on_mount(self) -> None:
        self.title = "FileTriage"
        self.query_one("#progress", Label).styles.display = "none"
        self.query_one(ItemDisplay).styles.display = "none"
        self.query_one(KeyLegend).styles.display = "none"
        self.push_screen(
            StartupScreen(
                preset_paths=self.preset_paths,
                preset_min_age=self.preset_min_age,
                preset_dry_run=self.preset_dry_run,
            ),
            callback=self._on_startup_done,
        )

    def _on_startup_done(self, result) -> None:
        if result is None:
            self.exit()
            return
        paths, min_age, dry_run = result
        self.dry_run = dry_run

        # Detect atime disabled on Windows
        self.use_mtime = _detect_atime_disabled(paths)

        warnings: list[str] = []
        items = scan_paths(paths, min_age, warnings, self.use_mtime)
        self.scan_warnings = warnings
        self.queue = items
        self.total_initial = len(items)

        # Now build the triage UI
        self.triage_started = True
        self._build_triage_ui()

    def _build_triage_ui(self) -> None:
        """Populate the main screen for triage after scanning."""
        main_area = self.query_one("#main-area", Vertical)

        # Mount banners at the top of the app (before progress)
        if self.dry_run:
            self.mount(DryRunBanner(), before=self.query_one("#progress"))
        if self.use_mtime:
            self.mount(MtimeBanner(), before=self.query_one("#progress"))

        # Mount warnings inside main area, before ItemDisplay
        if self.scan_warnings:
            main_area.mount(
                WarningPanel(
                    "\n".join(f"! {w}" for w in self.scan_warnings)
                ),
                before=self.query_one(ItemDisplay),
            )

        # Show progress bar and triage elements
        self.query_one("#progress", Label).styles.display = "block"
        self.query_one(ItemDisplay).styles.display = "block"
        self.query_one(KeyLegend).styles.display = "block"

        if self.queue:
            self._show_current()
        else:
            self._show_summary()

    @property
    def active_queue(self) -> list[dict]:
        return self.later_queue if self.processing_later else self.queue

    @property
    def current_item(self) -> dict | None:
        q = self.active_queue
        if self.current_index < len(q):
            return q[self.current_index]
        return None

    def _progress_text(self) -> str:
        q = self.active_queue
        total = len(q)
        num = min(self.current_index + 1, total)
        phase = " (deferred items)" if self.processing_later else ""
        return f"Item {num} of {total}{phase}"

    def _show_current(self) -> None:
        item = self.current_item
        if item is None:
            if not self.processing_later and self.later_queue:
                self.processing_later = True
                self.current_index = 0
                self._show_current()
                return
            self._show_summary()
            return

        self.query_one("#progress", Label).update(self._progress_text())

        time_label = "Last modified" if self.use_mtime else "Last accessed"
        lines: list[str] = []
        path = item["path"]
        lines.append(f"Path: {path}")

        if item["type"] == "file":
            lines.append("Type: file")
            lines.append(f"Extension: {item.get('extension', '(none)')}")
        else:
            if item.get("empty"):
                lines.append("Type: directory (empty)")
            else:
                lines.append(
                    f"Type: directory (non-empty — {item['item_count']} items)"
                )

        lines.append(f"Size: {human_size(item['size'])}")
        atime_dt = datetime.fromtimestamp(item["atime"])
        age_days = (datetime.now() - atime_dt).days
        lines.append(
            f"{time_label}: {atime_dt:%Y-%m-%d %H:%M}  ({age_days} days ago)"
        )

        self.query_one(ItemDisplay).update("\n".join(lines))
        self.query_one(ConfirmOverlay).styles.display = "none"
        self.confirming = False

    def _advance(self) -> None:
        self.current_index += 1
        self._show_current()

    def _do_delete(self, item: dict) -> None:
        """Perform the actual deletion (or simulate in dry-run)."""
        path: Path = item["path"]
        if self.dry_run:
            self.deleted += 1
            return
        try:
            if item["type"] == "file":
                path.unlink()
            elif item.get("empty"):
                path.rmdir()
            else:
                shutil.rmtree(path)
            self.deleted += 1
        except OSError as e:
            self.notify(f"Delete failed: {e}", severity="error", timeout=4)

    def _show_summary(self) -> None:
        self.push_screen(
            SummaryScreen(
                deleted=self.deleted,
                kept=self.kept,
                deferred=self.deferred,
                dry_run=self.dry_run,
            )
        )

    # ── Actions ──────────────────────────────────────────────────────────

    def action_delete_item(self) -> None:
        if not self.triage_started or self.confirming:
            return
        item = self.current_item
        if item is None:
            return
        if item["type"] == "directory" and not item.get("empty"):
            self.query_one(ConfirmOverlay).styles.display = "block"
            self.confirming = True
            return
        self._do_delete(item)
        self._advance()

    def action_confirm_delete(self) -> None:
        if not self.confirming:
            return
        item = self.current_item
        if item is None:
            return
        self._do_delete(item)
        self.confirming = False
        self._advance()

    def action_cancel_delete(self) -> None:
        if not self.confirming:
            return
        self.query_one(ConfirmOverlay).styles.display = "none"
        self.confirming = False

    def action_keep_item(self) -> None:
        if not self.triage_started or self.confirming:
            return
        if self.current_item is None:
            return
        self.kept += 1
        self._advance()

    def action_later_item(self) -> None:
        if not self.triage_started or self.confirming:
            return
        item = self.current_item
        if item is None:
            return
        if not self.processing_later:
            self.later_queue.append(item)
        else:
            self.later_queue.append(self.later_queue.pop(self.current_index))
            self._show_current()
            return
        self.deferred += 1
        self._advance()

    def action_quit_triage(self) -> None:
        if not self.triage_started:
            self.exit()
            return
        if self.confirming:
            return
        q = self.active_queue
        remaining = len(q) - self.current_index
        if self.processing_later:
            self.deferred += remaining
        else:
            self.deferred += remaining + len(self.later_queue)
        self._show_summary()


# ── CLI Entry Point ──────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="filetriage",
        description="Interactively review and delete old files and directories.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=[],
        help="Directories to scan (pre-fills startup screen)",
    )
    parser.add_argument(
        "--min-age",
        type=int,
        default=30,
        help="Minimum age in days (default: 30, pre-fills startup screen)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pre-enable dry-run mode on startup screen",
    )

    args = parser.parse_args()

    app = FileTriageApp(
        preset_paths=args.paths,
        preset_min_age=args.min_age,
        preset_dry_run=args.dry_run,
    )
    app.run()


if __name__ == "__main__":
    main()
