"""Textual TUI dashboard for ftl2-enterprise.

Read-only view of loop state from the SQLite database.
Refreshes on a timer — no worker thread needed.
"""

from rich.table import Table
from rich.text import Text

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, Static

from .db import create_db
from . import store


class EnterpriseApp(App):
    """Dashboard TUI for ftl2-enterprise loops."""

    TITLE = "ftl2-enterprise"
    CSS = """
    #dashboard {
        height: 1fr;
        overflow-y: auto;
    }
    #status-bar {
        height: 1;
        dock: bottom;
        background: $primary-background;
        color: $text;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit_app", "Quit", show=True),
    ]

    def __init__(self, db_path: str):
        super().__init__()
        self._db_path = db_path
        self._engine = create_db(db_path)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Loading...", id="dashboard")
        yield Static("", id="status-bar")

    def on_mount(self) -> None:
        self._refresh_dashboard()
        self.set_interval(2.0, self._refresh_dashboard)

    def action_quit_app(self) -> None:
        self.exit()

    def _refresh_dashboard(self) -> None:
        all_loops = store.list_loops(self._engine)

        dashboard = self.query_one("#dashboard", Static)
        status_bar = self.query_one("#status-bar", Static)

        if not all_loops:
            dashboard.update("No loops found. Run: ftl2-enterprise run <desired_state>")
            status_bar.update("0 loops")
            return

        table = Table(expand=True)
        table.add_column("ID", style="dim", width=5, justify="right")
        table.add_column("Status", width=10)
        table.add_column("Mode", width=12)
        table.add_column("Iters", width=6, justify="right")
        table.add_column("Actions", width=8, justify="right")
        table.add_column("Created", width=20)
        table.add_column("Name")

        for loop in all_loops:
            status = loop.get("status", "")
            if status == "running":
                style_status = Text(status, style="bold green")
            elif status == "completed":
                style_status = Text(status, style="blue")
            elif status == "failed":
                style_status = Text(status, style="bold red")
            elif status == "pending":
                style_status = Text(status, style="yellow")
            else:
                style_status = Text(status)

            loop_id = loop["id"]
            iters = store.get_iterations(self._engine, loop_id)
            action_count = store.count_actions(self._engine, loop_id)
            created = (loop.get("created_at") or "")[:19]

            table.add_row(
                str(loop_id),
                style_status,
                loop.get("mode", ""),
                str(len(iters)),
                str(action_count),
                created,
                loop.get("name", ""),
            )

        dashboard.update(table)

        # Status bar counts
        running = sum(1 for l in all_loops if l.get("status") == "running")
        completed = sum(1 for l in all_loops if l.get("status") == "completed")
        failed = sum(1 for l in all_loops if l.get("status") == "failed")
        pending = sum(1 for l in all_loops if l.get("status") == "pending")
        total = len(all_loops)

        parts = [f"{total} loops"]
        if running:
            parts.append(f"{running} running")
        if pending:
            parts.append(f"{pending} pending")
        if completed:
            parts.append(f"{completed} completed")
        if failed:
            parts.append(f"{failed} failed")

        status_bar.update(" | ".join(parts))


def run_tui(db_path: str = "loops.db") -> None:
    """Entry point for TUI mode."""
    app = EnterpriseApp(db_path)
    app.run()
