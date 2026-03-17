#!/usr/bin/env python3
"""FileTriage - Interactive TUI for reviewing and deleting old files and directories."""

import argparse
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, Static


def human_size(nbytes: int) -> str:
    """Convert bytes to human-readable size string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} PB"


def get_atime(path: Path) -> float:
    """Get access time of a path, returning 0 on error."""
    try:
        return path.stat().st_atime
    except OSError:
        return 0.0


def dir_stats(path: Path) -> tuple[int, int, float]:
    """Return (item_count, total_size, oldest_atime) for a directory's contents."""
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
                atime = st.st_atime
                if atime < oldest:
                    oldest = atime
            except OSError:
                continue
    except OSError:
        pass
    if oldest == float("inf"):
        oldest = get_atime(path)
    return count, total, oldest


def scan_paths(
    roots: list[str], min_age_days: int, warnings: list[str]
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
                        if st.st_atime < cutoff:
                            files.append(
                                {
                                    "path": entry,
                                    "type": "file",
                                    "size": st.st_size,
                                    "atime": st.st_atime,
                                    "extension": entry.suffix or "(none)",
                                }
                            )
                    elif entry.is_dir():
                        count, total, oldest = dir_stats(entry)
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

    # Sort files oldest-first, then append dirs (also oldest-first)
    files.sort(key=lambda x: x["atime"])
    dirs.sort(key=lambda x: x["atime"])
    return files + dirs


# ── Textual Widgets ──────────────────────────────────────────────────────────


class DryRunBanner(Static):
    """Banner shown when dry-run mode is active."""

    def render(self) -> str:
        return "⚠  DRY-RUN MODE — no files will be deleted  ⚠"

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


# ── Summary Screen ───────────────────────────────────────────────────────────


class SummaryScreen(Screen):
    """Final summary screen shown after all items are processed or on quit."""

    BINDINGS = [Binding("q", "quit_app", "Quit"), Binding("escape", "quit_app", "Quit")]

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
                    "(DRY-RUN — nothing was actually deleted)", classes="summary-stat"
                )
            yield Static("")
            yield Static(
                f"Deleted:  {self.deleted}", classes="summary-stat"
            )
            yield Static(
                f"Kept:     {self.kept}", classes="summary-stat"
            )
            yield Static(
                f"Deferred: {self.deferred}", classes="summary-stat"
            )
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
    #empty-msg {
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
        items: list[dict],
        dry_run: bool,
        warnings: list[str],
    ) -> None:
        super().__init__()
        self.queue: list[dict] = list(items)
        self.later_queue: list[dict] = []
        self.dry_run = dry_run
        self.warnings = warnings
        self.current_index = 0
        self.deleted = 0
        self.kept = 0
        self.deferred = 0
        self.total_initial = len(items)
        self.processing_later = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        if self.dry_run:
            yield DryRunBanner()
        yield Label("", id="progress")
        with Vertical(id="main-area"):
            if self.warnings:
                yield WarningPanel("\n".join(f"⚠ {w}" for w in self.warnings))
            yield ItemDisplay("")
            yield ConfirmOverlay()
        yield KeyLegend()

    def on_mount(self) -> None:
        self.title = "FileTriage"
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

        lines: list[str] = []
        path = item["path"]
        lines.append(f"Path: {path}")

        if item["type"] == "file":
            lines.append(f"Type: file")
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
        lines.append(f"Last accessed: {atime_dt:%Y-%m-%d %H:%M}  ({age_days} days ago)")

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
                os.rmdir(path)
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
        if self.confirming:
            return
        item = self.current_item
        if item is None:
            return
        # Non-empty directory requires confirmation
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
        if self.confirming:
            return
        if self.current_item is None:
            return
        self.kept += 1
        self._advance()

    def action_later_item(self) -> None:
        if self.confirming:
            return
        item = self.current_item
        if item is None:
            return
        if not self.processing_later:
            self.later_queue.append(item)
        else:
            # Already in later queue — move to end
            self.later_queue.append(self.later_queue.pop(self.current_index))
            # Don't increment index since we popped current
            self._show_current()
            return
        self.deferred += 1
        self._advance()

    def action_quit_triage(self) -> None:
        if self.confirming:
            return
        # Count remaining items as deferred
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
        nargs="+",
        help="Directories to scan",
    )
    parser.add_argument(
        "--min-age",
        type=int,
        default=30,
        help="Minimum age in days based on last accessed date (default: 30)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate deletions without removing files",
    )

    args = parser.parse_args()

    warnings: list[str] = []
    print(f"Scanning {len(args.paths)} path(s) for items older than {args.min_age} days...")
    items = scan_paths(args.paths, args.min_age, warnings)
    print(f"Found {len(items)} items to review.")

    if not items and not warnings:
        print("Nothing to review. All files are newer than the threshold.")
        sys.exit(0)

    app = FileTriageApp(items=items, dry_run=args.dry_run, warnings=warnings)
    app.run()


if __name__ == "__main__":
    main()
