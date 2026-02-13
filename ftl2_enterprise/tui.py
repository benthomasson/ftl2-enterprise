"""Textual TUI dashboard for ftl2-enterprise.

Interactive dashboard that shows loop status, pending prompts,
and allows submitting new loops and responding to prompts.
Refreshes on a timer — no worker thread needed.
"""

import json

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Header, Static, Input, Button, Select, Label, DataTable

from .db import create_db
from . import store


# --- Modal Screens ---


class SubmitScreen(ModalScreen[int | None]):
    """Modal for submitting a new loop to the worker."""

    DEFAULT_CSS = """
    SubmitScreen {
        align: center middle;
    }

    SubmitScreen > Vertical {
        width: 70;
        height: auto;
        border: thick $background 80%;
        background: $surface;
        padding: 1 2;
    }

    SubmitScreen Label {
        width: 100%;
        margin-top: 1;
    }

    SubmitScreen Input {
        width: 100%;
        margin-bottom: 1;
    }

    SubmitScreen Select {
        width: 100%;
        margin-bottom: 1;
    }

    SubmitScreen #title-label {
        text-style: bold;
        margin-top: 0;
        margin-bottom: 1;
    }

    SubmitScreen #buttons {
        width: 100%;
        height: auto;
        margin-top: 1;
    }

    SubmitScreen #buttons Button {
        margin-right: 1;
    }
    """

    def __init__(self, engine):
        super().__init__()
        self._engine = engine

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Submit New Loop", id="title-label")
            yield Label("Desired state:")
            yield Input(placeholder="e.g. install nginx on all web servers", id="desired-state")
            yield Label("Inventory (optional):")
            yield Input(placeholder="path/to/inventory", id="inventory")
            yield Label("Mode:")
            yield Select(
                [("single", "single"), ("incremental", "incremental"), ("continuous", "continuous")],
                value="single",
                id="mode",
            )
            with Horizontal(id="buttons"):
                yield Button("Submit", id="submit", variant="primary")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed, "#submit")
    def handle_submit(self) -> None:
        desired_state = self.query_one("#desired-state", Input).value.strip()
        if not desired_state:
            self.query_one("#desired-state", Input).focus()
            return

        inventory = self.query_one("#inventory", Input).value.strip() or None
        mode = self.query_one("#mode", Select).value

        loop_id = store.create_loop(
            self._engine,
            name=desired_state[:80],
            desired_state=desired_state,
            mode=mode,
            inventory=inventory,
            interval=60 if mode != "single" else None,
        )
        self.dismiss(loop_id)

    @on(Button.Pressed, "#cancel")
    def handle_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def handle_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "desired-state":
            self.query_one("#inventory", Input).focus()
        elif event.input.id == "inventory":
            self.handle_submit()


class RespondScreen(ModalScreen[bool]):
    """Modal for responding to a pending prompt."""

    DEFAULT_CSS = """
    RespondScreen {
        align: center middle;
    }

    RespondScreen > Vertical {
        width: 70;
        height: auto;
        border: thick $background 80%;
        background: $surface;
        padding: 1 2;
    }

    RespondScreen Label {
        width: 100%;
        margin-top: 1;
    }

    RespondScreen Input {
        width: 100%;
        margin-bottom: 1;
    }

    RespondScreen #title-label {
        text-style: bold;
        margin-top: 0;
    }

    RespondScreen #subtitle-label {
        color: $text-muted;
        margin-bottom: 1;
    }

    RespondScreen #question-label {
        margin-top: 1;
        margin-bottom: 1;
    }

    RespondScreen #options-label {
        color: $accent;
        margin-bottom: 1;
    }

    RespondScreen #buttons {
        width: 100%;
        height: auto;
        margin-top: 1;
    }

    RespondScreen #buttons Button {
        margin-right: 1;
    }
    """

    def __init__(self, engine, prompt_data: dict):
        super().__init__()
        self._engine = engine
        self._prompt_data = prompt_data

    def compose(self) -> ComposeResult:
        prompt_id = self._prompt_data["id"]
        loop_id = self._prompt_data["loop_id"]
        question = self._prompt_data["prompt_text"]

        # Parse options if present
        options_raw = self._prompt_data.get("options")
        options = None
        if options_raw:
            try:
                options = json.loads(options_raw) if isinstance(options_raw, str) else options_raw
            except (json.JSONDecodeError, TypeError):
                pass

        with Vertical():
            yield Label(f"Respond to Prompt #{prompt_id}", id="title-label")
            yield Label(f"Loop #{loop_id}", id="subtitle-label")
            yield Label(question, id="question-label")
            if options:
                yield Label(f"Options: {', '.join(str(o) for o in options)}", id="options-label")
            yield Label("Your response:")
            yield Input(placeholder="Type your response...", id="response")
            with Horizontal(id="buttons"):
                yield Button("Submit", id="submit", variant="primary")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed, "#submit")
    def handle_submit(self) -> None:
        response = self.query_one("#response", Input).value.strip()
        if not response:
            self.query_one("#response", Input).focus()
            return

        store.record_response(self._engine, self._prompt_data["id"], response)
        self.dismiss(True)

    @on(Button.Pressed, "#cancel")
    def handle_cancel(self) -> None:
        self.dismiss(False)

    @on(Input.Submitted, "#response")
    def handle_input_submitted(self) -> None:
        self.handle_submit()


class PickPromptScreen(ModalScreen[dict | None]):
    """Modal for choosing which prompt to respond to when multiple are pending."""

    DEFAULT_CSS = """
    PickPromptScreen {
        align: center middle;
    }

    PickPromptScreen > Vertical {
        width: 70;
        height: auto;
        border: thick $background 80%;
        background: $surface;
        padding: 1 2;
    }

    PickPromptScreen #title-label {
        text-style: bold;
        margin-bottom: 1;
    }

    PickPromptScreen Select {
        width: 100%;
        margin-bottom: 1;
    }

    PickPromptScreen #buttons {
        width: 100%;
        height: auto;
        margin-top: 1;
    }

    PickPromptScreen #buttons Button {
        margin-right: 1;
    }
    """

    def __init__(self, prompts: list[dict]):
        super().__init__()
        self._prompts = {p["id"]: p for p in prompts}

    def compose(self) -> ComposeResult:
        options = []
        for p in self._prompts.values():
            question = p["prompt_text"]
            if len(question) > 50:
                question = question[:50] + "..."
            label = f"#{p['id']} (Loop #{p['loop_id']}): {question}"
            options.append((label, p["id"]))

        with Vertical():
            yield Label("Select a prompt to respond to:", id="title-label")
            yield Select(options, id="prompt-select")
            with Horizontal(id="buttons"):
                yield Button("Select", id="select", variant="primary")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed, "#select")
    def handle_select(self) -> None:
        selected = self.query_one("#prompt-select", Select).value
        if selected is not None and selected in self._prompts:
            self.dismiss(self._prompts[selected])
        else:
            self.dismiss(None)

    @on(Button.Pressed, "#cancel")
    def handle_cancel(self) -> None:
        self.dismiss(None)


class LoopDetailScreen(ModalScreen[None]):
    """Full-screen detail view for a single loop."""

    DEFAULT_CSS = """
    LoopDetailScreen {
        align: center middle;
    }

    LoopDetailScreen > Vertical {
        width: 100%;
        height: 100%;
        background: $surface;
        padding: 1 2;
    }

    LoopDetailScreen #detail-header {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }

    LoopDetailScreen #detail-content {
        height: 1fr;
        overflow-y: auto;
    }

    LoopDetailScreen #detail-bar {
        height: 1;
        dock: bottom;
        background: $primary-background;
        color: $text;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("q", "go_back", "Back", show=False),
    ]

    def __init__(self, engine, loop_id: int):
        super().__init__()
        self._engine = engine
        self._loop_id = loop_id

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("", id="detail-header")
            yield Static("Loading...", id="detail-content")
            yield Static("ESC: back", id="detail-bar")

    def on_mount(self) -> None:
        self._refresh_detail()
        self.set_interval(2.0, self._refresh_detail)

    def action_go_back(self) -> None:
        self.dismiss(None)

    def _refresh_detail(self) -> None:
        loop = store.get_loop(self._engine, self._loop_id)
        if not loop:
            self.query_one("#detail-header", Static).update("Loop not found")
            return

        # Header
        status = loop.get("status", "")
        status_style = {
            "running": "bold green",
            "completed": "blue",
            "failed": "bold red",
            "pending": "yellow",
            "paused": "bold yellow",
        }.get(status, "")

        header_text = Text()
        header_text.append(f"Loop #{loop['id']}", style="bold")
        header_text.append("  ")
        header_text.append(status, style=status_style)
        header_text.append(f"  {loop.get('mode', '')}")
        header_text.append(f"\n{loop.get('desired_state', '')}")

        self.query_one("#detail-header", Static).update(
            Panel(header_text, title="Loop Detail", border_style="dim")
        )

        # Content: iterations and actions
        renderables = []
        iters = store.get_iterations(self._engine, self._loop_id)

        if not iters:
            renderables.append(Text("No iterations yet.", style="dim"))
        else:
            for it in iters:
                iter_n = it["n"]
                converged = bool(it.get("converged"))
                reasoning = it.get("reasoning") or ""

                # Iteration header
                if converged:
                    iter_title = f"Iteration {iter_n + 1} — converged"
                    iter_style = "green"
                else:
                    iter_title = f"Iteration {iter_n + 1}"
                    iter_style = "dim"

                iter_parts = []

                if reasoning:
                    iter_parts.append(Text(f"Reasoning: {reasoning}", style="italic"))

                # Actions table for this iteration
                iter_actions = store.get_actions_for_iteration(self._engine, it["id"])
                if iter_actions:
                    action_table = Table(expand=True, show_header=True, padding=(0, 1))
                    action_table.add_column("Module", width=20)
                    action_table.add_column("Host", width=15)
                    action_table.add_column("Status", width=10)
                    action_table.add_column("RC", width=5, justify="right")
                    action_table.add_column("Output")

                    for a in iter_actions:
                        a_status = a.get("status", "")
                        if a_status == "completed":
                            status_text = Text(a_status, style="green")
                        elif a_status == "failed":
                            status_text = Text(a_status, style="bold red")
                        else:
                            status_text = Text(a_status)

                        rc = str(a["rc"]) if a.get("rc") is not None else ""
                        stdout = (a.get("stdout") or "").strip()
                        stderr = (a.get("stderr") or "").strip()
                        output = stdout or stderr or ""
                        if len(output) > 80:
                            output = output[:80] + "..."

                        action_table.add_row(
                            a.get("module", ""),
                            a.get("host", "") or "",
                            status_text,
                            rc,
                            output,
                        )

                    iter_parts.append(action_table)
                elif not converged:
                    iter_parts.append(Text("No actions", style="dim"))

                if iter_parts:
                    content = Group(*iter_parts)
                else:
                    content = Text("converged", style="green")

                renderables.append(Panel(
                    content,
                    title=iter_title,
                    title_align="left",
                    border_style=iter_style,
                ))

        self.query_one("#detail-content", Static).update(Group(*renderables))

        # Status bar
        total_actions = store.count_actions(self._engine, self._loop_id)
        self.query_one("#detail-bar", Static).update(
            f"{len(iters)} iterations | {total_actions} actions | ESC: back"
        )


# --- Main App ---


class EnterpriseApp(App):
    """Dashboard TUI for ftl2-enterprise loops."""

    TITLE = "ftl2-enterprise"
    CSS = """
    #loops-table {
        height: 1fr;
        border: solid $primary-background;
    }
    #prompts-area {
        height: auto;
        max-height: 30%;
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
        Binding("s", "submit_loop", "Submit", show=True),
        Binding("r", "respond_prompt", "Respond", show=True),
    ]

    def __init__(self, db_path: str):
        super().__init__()
        self._db_path = db_path
        self._engine = create_db(db_path)

    def compose(self) -> ComposeResult:
        yield Header()
        table = DataTable(id="loops-table", cursor_type="row", zebra_stripes=True)
        table.add_columns("ID", "Status", "Mode", "Iters", "Actions", "Created", "Name")
        yield table
        yield Static("", id="prompts-area")
        yield Static("", id="status-bar")

    def on_mount(self) -> None:
        self._refresh_dashboard()
        self.set_interval(2.0, self._refresh_dashboard)

    def action_quit_app(self) -> None:
        self.exit()

    def action_submit_loop(self) -> None:
        def on_submit(loop_id: int | None) -> None:
            if loop_id is not None:
                self.notify(f"Loop #{loop_id} submitted")
                self._refresh_dashboard()

        self.push_screen(SubmitScreen(self._engine), on_submit)

    def action_respond_prompt(self) -> None:
        pending = store.get_pending_prompts(self._engine)
        if not pending:
            self.notify("No pending prompts", severity="warning")
            return

        if len(pending) == 1:
            self._open_respond(pending[0])
        else:
            def on_pick(prompt_data: dict | None) -> None:
                if prompt_data is not None:
                    self._open_respond(prompt_data)

            self.push_screen(PickPromptScreen(pending), on_pick)

    @on(DataTable.RowSelected, "#loops-table")
    def on_loop_selected(self, event: DataTable.RowSelected) -> None:
        try:
            loop_id = int(event.row_key.value)
        except (TypeError, ValueError):
            return
        self.push_screen(LoopDetailScreen(self._engine, loop_id))

    def _open_respond(self, prompt_data: dict) -> None:
        def on_respond(submitted: bool) -> None:
            if submitted:
                self.notify(f"Response sent for prompt #{prompt_data['id']}")
                self._refresh_dashboard()

        self.push_screen(RespondScreen(self._engine, prompt_data), on_respond)

    def _refresh_dashboard(self) -> None:
        all_loops = store.list_loops(self._engine)
        pending_prompts = store.get_pending_prompts(self._engine)

        loops_table = self.query_one("#loops-table", DataTable)
        prompts_area = self.query_one("#prompts-area", Static)
        status_bar = self.query_one("#status-bar", Static)

        # Save cursor position before clearing
        cursor_row = loops_table.cursor_row

        # Update loops table
        loops_table.clear()

        for loop in all_loops:
            status = loop.get("status", "")
            status_styles = {
                "running": "bold green",
                "completed": "blue",
                "failed": "bold red",
                "pending": "yellow",
                "paused": "bold yellow",
            }
            style_status = Text(status, style=status_styles.get(status, ""))

            loop_id = loop["id"]
            iters = store.get_iterations(self._engine, loop_id)
            action_count = store.count_actions(self._engine, loop_id)
            created = (loop.get("created_at") or "")[:19]

            loops_table.add_row(
                str(loop_id),
                style_status,
                loop.get("mode", ""),
                str(len(iters)),
                str(action_count),
                created,
                loop.get("name", ""),
                key=str(loop_id),
            )

        # Restore cursor position
        if all_loops and cursor_row < len(all_loops):
            loops_table.move_cursor(row=cursor_row)

        # Pending prompts
        if pending_prompts:
            prompt_table = Table(
                expand=True,
                title="Pending Prompts",
                title_style="bold yellow",
                border_style="yellow",
            )
            prompt_table.add_column("ID", style="dim", width=5, justify="right")
            prompt_table.add_column("Loop", width=6, justify="right")
            prompt_table.add_column("Question")
            prompt_table.add_column("Created", width=20)

            for p in pending_prompts:
                question = p.get("prompt_text", "")
                if len(question) > 60:
                    question = question[:60] + "..."
                created = (p.get("created_at") or "")[:19]

                prompt_table.add_row(
                    str(p["id"]),
                    str(p["loop_id"]),
                    question,
                    created,
                )

            prompts_area.update(prompt_table)
        else:
            prompts_area.update("")

        # Status bar counts
        running = sum(1 for l in all_loops if l.get("status") == "running")
        completed = sum(1 for l in all_loops if l.get("status") == "completed")
        failed = sum(1 for l in all_loops if l.get("status") == "failed")
        pending_loops = sum(1 for l in all_loops if l.get("status") == "pending")
        paused = sum(1 for l in all_loops if l.get("status") == "paused")
        total = len(all_loops)

        parts = [f"{total} loops"]
        if running:
            parts.append(f"{running} running")
        if pending_loops:
            parts.append(f"{pending_loops} pending")
        if paused:
            parts.append(f"{paused} paused")
        if completed:
            parts.append(f"{completed} completed")
        if failed:
            parts.append(f"{failed} failed")
        if pending_prompts:
            parts.append(f"{len(pending_prompts)} prompts")

        status_bar.update(" | ".join(parts))


def run_tui(db_path: str = "loops.db") -> None:
    """Entry point for TUI mode."""
    app = EnterpriseApp(db_path)
    app.run()
