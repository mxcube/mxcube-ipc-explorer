"""Interactive TUI for exploring a beamline over mxcubecore.ipc.

DANGER: like mxcube_ipc_explore.py, this uses the debug bypass
(mxcubecore/ipc/debug.py, IPC_FORMAT.md section 7) - the IPCServer you
point it at must have been started with `allow_debug_calls: true` (off by
default). Enabling that means ANY authenticated client can invoke ANY
method on ANY resolvable role with ANY arguments - no whitelist check, no
pydantic validation. Only point this at a local, trusted beamline session.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

import jsonschema
from mxcube_ipc_client import MXCuBEIPCClient
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
    Tree,
)
from textual.widgets.tree import TreeNode

from mxcube_ipc_explorer.json_tree import render_json_tree
from mxcube_ipc_explorer.logging_config import logger
from mxcube_ipc_explorer.schema_template import kwargs_template


class _LogRecord(Message):
    """One formatted line from the `mxcube_ipc_explorer` logger, on its
    way to the Log tab - see _WidgetLogHandler/on_mount.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()


class _WidgetLogHandler(logging.Handler):
    """Mirrors every record the file handler writes into the Log tab's
    RichLog, via Message.post_message() - safe to call from any thread
    (unlike App.call_from_thread(), which errors if called from the
    app's own thread - most log calls here happen from @work(thread=True)
    workers, but some, e.g. "app started"/"quitting", happen from the
    main thread).
    """

    def __init__(self, app: "MXCuBEIPCExplorerApp") -> None:
        super().__init__()
        self._app = app

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
        except Exception:  # noqa: BLE001 - a logging handler must never raise
            text = record.getMessage()
        try:
            self._app.post_message(_LogRecord(text))
        except Exception:  # noqa: BLE001 - ditto
            pass


def _truncate(value: Any, limit: int = 2000) -> str:
    text = repr(value)
    if len(text) > limit:
        text = f"{text[:limit]}... ({len(text)} chars total)"
    return text


def _redact_client_kwargs(client_kwargs: dict) -> dict:
    return {k: ("***" if k == "token" else v) for k, v in client_kwargs.items()}


class MXCuBEIPCExplorerApp(App[None]):
    """Browse roles/methods, call anything, and inspect nested JSON
    results (e.g. the queue tree) - all over the ipc debug bypass.
    """

    CSS = """
    #body {
        height: 1fr;
    }
    #sidebar {
        width: 42;
        border: solid $accent;
    }
    #main {
        border: solid $accent;
    }
    #events {
        height: 12;
        border: solid $accent;
    }
    .title {
        background: $accent;
        color: $text;
        padding: 0 1;
        text-style: bold;
    }
    #roles-tree {
        height: 1fr;
    }
    #methods-list {
        height: 10;
    }
    #result-tree {
        height: 1fr;
    }
    #event-log {
        height: 1fr;
    }
    #events-sidebar {
        width: 42;
    }
    #events-list {
        height: 1fr;
    }
    .call-row {
        height: 3;
    }
    .call-row Input {
        width: 1fr;
    }
    TabPane {
        height: 1fr;
    }
    #app-log {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+enter", "call", "Call"),
    ]

    def __init__(self, client_kwargs: dict, log_file: Optional[str] = None) -> None:
        super().__init__()
        self._client_kwargs = client_kwargs
        self.client: Optional[MXCuBEIPCClient] = None
        self._loaded_roles: set[str] = set()
        self._listening_event: Optional[str] = None
        self._event_handler = None
        self._log_widget_handler: Optional[_WidgetLogHandler] = None
        self._log_file = log_file
        # (role, method) the currently-loaded kwargs schema is for, and
        # the schema itself - see _populate_methods_list/on_list_view_selected
        # and action_call's client-side validation. None/None once the
        # role or method inputs no longer match what was last selected.
        self._current_schema_key: Optional[tuple] = None
        self._current_schema: Optional[dict] = None
        if log_file:
            self.sub_title = f"log: {log_file}"

    # -- layout -------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="explorer-tab"):
            with TabPane("Explorer", id="explorer-tab"):
                with Horizontal(id="body"):
                    with Vertical(id="sidebar"):
                        yield Static("Roles", classes="title")
                        yield Tree("beamline", id="roles-tree")
                        yield Static("Methods", classes="title")
                        yield ListView(id="methods-list")
                    with Vertical(id="main"):
                        yield Static("Call", classes="title")
                        with Horizontal(classes="call-row"):
                            yield Input(placeholder="role, e.g. diffractometer.omega", id="role-input")
                            yield Input(placeholder="method, e.g. get_value", id="method-input")
                        with Horizontal(classes="call-row"):
                            yield Input(placeholder="args JSON, e.g. []", id="args-input", value="[]")
                            yield Input(placeholder="kwargs JSON, e.g. {}", id="kwargs-input", value="{}")
                        with Horizontal(classes="call-row"):
                            yield Button("Call", id="call-button", variant="primary")
                            yield Button("Dump queue", id="dump-queue-button")
                        yield Static("Result", classes="title")
                        yield Tree("(no result yet)", id="result-tree")
                with Horizontal(id="events"):
                    with Vertical(id="events-sidebar"):
                        yield Static("Events (whitelisted)", classes="title")
                        yield ListView(id="events-list")
                    with Vertical():
                        with Horizontal(classes="call-row"):
                            yield Input(
                                placeholder="event name, e.g. diffractometer.omega.valueChanged",
                                id="event-input",
                            )
                            yield Button("Listen", id="listen-button")
                        yield RichLog(id="event-log", wrap=True, markup=True)
            with TabPane("Log", id="log-tab"):
                yield RichLog(id="app-log", wrap=True, markup=False, max_lines=10000)
        yield Footer()

    def on_mount(self) -> None:
        self._attach_log_widget_handler()
        logger.info("app started")
        self.query_one("#roles-tree", Tree).root.data = ""
        self.query_one("#result-tree", Tree).show_root = False
        self.connect_client()

    # -- log tab ----------------------------------------------------------

    def _attach_log_widget_handler(self) -> None:
        handler = _WidgetLogHandler(self)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(message)s")
        )
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        self._log_widget_handler = handler
        if self._log_file:
            self.query_one("#app-log", RichLog).write(f"[dim]log file: {self._log_file}[/dim]")

    def _detach_log_widget_handler(self) -> None:
        if self._log_widget_handler is not None:
            logger.removeHandler(self._log_widget_handler)
            self._log_widget_handler = None

    def on__log_record(self, message: _LogRecord) -> None:
        self.query_one("#app-log", RichLog).write(message.text)

    # -- connecting -----------------------------------------------------

    @work(thread=True)
    def connect_client(self) -> None:
        logger.info("connecting: %s", _truncate(_redact_client_kwargs(self._client_kwargs)))
        try:
            client = MXCuBEIPCClient(**self._client_kwargs)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not raised
            logger.exception("connection failed")
            self.call_from_thread(self._on_connect_error, exc)
            return
        logger.info("connected")
        self.call_from_thread(self._on_connected, client)

    def _on_connect_error(self, exc: Exception) -> None:
        self.notify(f"connection failed: {exc}", severity="error", timeout=10)

    def _on_connected(self, client: MXCuBEIPCClient) -> None:
        self.client = client
        self.notify("connected")
        self._populate_events_list(client.events)
        self._load_role_children(self.query_one("#roles-tree", Tree).root)

    # -- events list (the server's `events:` whitelist, from _describe) --

    def _populate_events_list(self, events: dict) -> None:
        logger.info("whitelisted events: %s", _truncate(events))
        events_list = self.query_one("#events-list", ListView)
        events_list.clear()
        if not events:
            events_list.append(ListItem(Label("(none configured)")))
            return
        for name, info in sorted(events.items()):
            args = info.get("args")
            signature = f"({', '.join(args)})" if args is not None else "(undeclared)"
            item = ListItem(Label(f"{name}{signature}"))
            item.data = {"name": name}  # type: ignore[attr-defined]
            events_list.append(item)

    # -- roles tree (lazy: debug_list_roles per expand) ------------------

    def _load_role_children(self, node: TreeNode) -> None:
        if self.client is None:
            self.notify("not connected yet", severity="warning")
            return
        role_path: str = node.data or ""
        if role_path in self._loaded_roles:
            return
        self._loaded_roles.add(role_path)
        self._fetch_role_children(node, role_path)

    @work(thread=True)
    def _fetch_role_children(self, node: TreeNode, role_path: str) -> None:
        client = self.client
        if client is None:
            return
        logger.info("request: debug_list_roles(role=%r)", role_path)
        try:
            result = client.debug_list_roles(role_path)
        except Exception as exc:
            logger.exception("debug_list_roles(role=%r) failed", role_path)
            self.call_from_thread(self.notify, f"{role_path or '(beamline)'}: {exc}", severity="error")
            return
        logger.info("response: debug_list_roles(role=%r) -> %s", role_path, _truncate(result))
        self.call_from_thread(self._populate_role_children, node, result)

    def _populate_role_children(self, node: TreeNode, result: dict) -> None:
        role_path: str = node.data or ""
        for sub_role in result.get("roles", []):
            child_path = f"{role_path}.{sub_role}" if role_path else sub_role
            node.add(sub_role, data=child_path, allow_expand=True)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        if event.control.id == "roles-tree":
            self._load_role_children(event.node)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if event.control.id != "roles-tree":
            return
        if self.client is None:
            self.notify("not connected yet", severity="warning")
            return
        role_path: str = event.node.data or ""
        self.query_one("#role-input", Input).value = role_path
        self._describe_role(role_path)

    @work(thread=True)
    def _describe_role(self, role_path: str) -> None:
        client = self.client
        if client is None:
            return
        logger.info("request: debug_describe_role(role=%r)", role_path)
        try:
            result = client.debug_describe_role(role_path)
        except Exception as exc:
            logger.exception("debug_describe_role(role=%r) failed", role_path)
            self.call_from_thread(self.notify, f"{role_path or '(beamline)'}: {exc}", severity="error")
            return
        logger.info("response: debug_describe_role(role=%r) -> %s", role_path, _truncate(result))
        self.call_from_thread(self._populate_methods_list, result)

    def _populate_methods_list(self, result: dict) -> None:
        methods_list = self.query_one("#methods-list", ListView)
        methods_list.clear()
        for name, info in sorted(result.get("methods", {}).items()):
            item = ListItem(Label(f"{name}{info.get('signature', '(...)')}"))
            item.data = {"name": name, "schema": info.get("schema")}  # type: ignore[attr-defined]
            methods_list.append(item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "events-list":
            self._on_event_selected(event)
            return
        if event.list_view.id != "methods-list":
            return
        info = getattr(event.item, "data", None)
        if not info:
            return

        method_name = info["name"]
        schema = info["schema"]
        self.query_one("#method-input", Input).value = method_name

        role = self.query_one("#role-input", Input).value.strip()
        self._current_schema_key = (role, method_name)
        self._current_schema = schema

        # Always reset both fields on navigating to a (possibly
        # different) method - leaving over the previous method's
        # args/kwargs is confusing and, worse, easy to send by accident.
        # kwargs becomes a template of the new method's expected fields
        # (its own default, or a placeholder matching its type) when a
        # schema is available, else "{}".
        self.query_one("#args-input", Input).value = "[]"
        self.query_one("#kwargs-input", Input).value = json.dumps(
            kwargs_template(schema)
        )

    def _on_event_selected(self, event: ListView.Selected) -> None:
        info = getattr(event.item, "data", None)
        if not info:
            return
        event_input = self.query_one("#event-input", Input)
        if event_input.disabled:
            self.notify("stop the current listener first", severity="warning")
            return
        event_input.value = info["name"]

    # -- calling ----------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "call-button":
            self.action_call()
        elif event.button.id == "dump-queue-button":
            self.query_one("#role-input", Input).value = "queue_model"
            self.query_one("#method-input", Input).value = "get_queue_dict"
            self.query_one("#args-input", Input).value = "[]"
            # get_queue_dict(self) -> dict takes no arguments.
            self.query_one("#kwargs-input", Input).value = "{}"
            self.action_call()
        elif event.button.id == "listen-button":
            self._toggle_listen()

    def action_call(self) -> None:
        if self.client is None:
            self.notify("not connected yet", severity="warning")
            return

        role = self.query_one("#role-input", Input).value.strip()
        method = self.query_one("#method-input", Input).value.strip()
        if not method:
            self.notify("method is required", severity="warning")
            return

        try:
            args = json.loads(self.query_one("#args-input", Input).value or "[]")
            kwargs = json.loads(self.query_one("#kwargs-input", Input).value or "{}")
        except json.JSONDecodeError as exc:
            logger.exception("invalid args/kwargs JSON for role=%r method=%r", role, method)
            self.notify(f"args/kwargs must be valid JSON: {exc}", severity="error")
            return

        # If a method was picked from the Methods list (not hand-typed)
        # and role/method still match what it was picked for, validate
        # kwargs against its schema locally - before sending anything.
        if self._current_schema_key == (role, method) and self._current_schema:
            try:
                jsonschema.validate(instance=kwargs, schema=self._current_schema)
            except jsonschema.ValidationError as exc:
                logger.error(
                    "local validation failed for role=%r method=%r: %s",
                    role,
                    method,
                    exc.message,
                )
                self.notify(f"kwargs failed validation: {exc.message}", severity="error", timeout=10)
                return

        self._do_call(role, method, args, kwargs)

    @work(thread=True, exclusive=True, group="call")
    def _do_call(self, role: str, method: str, args: list, kwargs: dict) -> None:
        client = self.client
        if client is None:
            return
        logger.info(
            "request: debug_call(role=%r, method=%r, args=%s, kwargs=%s)",
            role,
            method,
            _truncate(args),
            _truncate(kwargs),
        )
        try:
            result = client.debug_call(role, method, args, kwargs)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not raised
            logger.exception("debug_call(role=%r, method=%r) failed", role, method)
            self.call_from_thread(self.notify, str(exc), severity="error", timeout=10)
            return
        logger.info(
            "response: debug_call(role=%r, method=%r) -> %s", role, method, _truncate(result)
        )
        self.call_from_thread(self._show_result, result)

    def _show_result(self, result: Any) -> None:
        render_json_tree(self.query_one("#result-tree", Tree), result)

    # -- events -------------------------------------------------------------

    def _toggle_listen(self) -> None:
        if self.client is None:
            self.notify("not connected yet", severity="warning")
            return

        listen_button = self.query_one("#listen-button", Button)
        event_input = self.query_one("#event-input", Input)

        if self._listening_event is not None:
            logger.info("request: disconnect(event=%r)", self._listening_event)
            self.client.disconnect(self._listening_event, self._event_handler)
            self.query_one("#event-log", RichLog).write(
                f"[dim]stopped listening for {self._listening_event}[/dim]"
            )
            self._listening_event = None
            self._event_handler = None
            listen_button.label = "Listen"
            event_input.disabled = False
            return

        event_name = event_input.value.strip()
        if not event_name:
            self.notify("event name is required", severity="warning")
            return
        if event_name not in self.client.events:
            # Still listen - but the server only ever sends events from
            # its `events:` config, so this one will never arrive.
            self.notify(
                f"{event_name} is not a whitelisted event - it will never arrive",
                severity="warning",
                timeout=10,
            )

        def handler(params: dict) -> None:
            logger.info("event: %s -> %s", event_name, _truncate(params))
            self.call_from_thread(self._append_event_log, event_name, params)

        logger.info("request: connect(event=%r)", event_name)
        self.client.connect(event_name, handler)
        self._listening_event = event_name
        self._event_handler = handler
        listen_button.label = "Stop"
        event_input.disabled = True
        self.query_one("#event-log", RichLog).write(f"[dim]listening for {event_name}...[/dim]")

    def _append_event_log(self, event_name: str, params: dict) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.query_one("#event-log", RichLog).write(f"[{timestamp}] {event_name}: {params}")

    # -- lifecycle ------------------------------------------------------

    def action_quit(self) -> None:
        logger.info("quitting")
        if self.client is not None:
            try:
                self.client.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup on exit
                logger.exception("error closing client on quit")
        self._detach_log_widget_handler()
        self.exit()

    def _handle_exception(self, error: Exception) -> None:
        # Textual's own catch-all for anything unhandled (including a
        # worker's exit_on_error=True default) - always fatal, but this
        # way the traceback survives the process exit instead of only
        # flashing on the alt-screen.
        logger.error("unhandled exception - app exiting", exc_info=error)
        super()._handle_exception(error)
