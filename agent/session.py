# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""One drive-thru conversation: the order, what the screen shows, and the link to the browser.

A Session outlives any single WebSocket connection. If the connection drops, the browser
reconnects with the same AgentCore session ID (which AgentCore routes to the same microVM),
picks up the same Session, and the customer carries on with their order.

Tools reach the session through the Strands tool context (see `session_of`), so no state
lives in module globals. Tools run in worker threads, in parallel, so every change to the
session's state happens under `session.lock`.

Messages to the browser follow the shape of AG-UI events:
- CUSTOM "menu": the whole menu, once per connection.
- STATE_SNAPSHOT: the whole screen state, with an epoch (one per Session) and a version (one
  per change). The browser ignores a snapshot older than the one it is showing.
- CUSTOM "session_ended": why the server is ending the session, just before it closes.
"""

import asyncio
import json
import logging
import threading
import time
import uuid
from collections import OrderedDict
from decimal import Decimal
from typing import Any, Callable

try:
    from agent.order_state import OrderState
except ModuleNotFoundError:
    from order_state import OrderState

logger = logging.getLogger(__name__)

# Everything the screen shows apart from the menu. Only the tools change it.
EMPTY_SCREEN: dict[str, Any] = {
    "highlightedCategory": None,
    "highlightedItem": None,
    "orderItems": [],
    "orderTotal": 0,
    "orderConfirmed": False,
    "orderNumber": None,
    "burgerBuilder": None,
}


def _json_default(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj == int(obj) else float(obj)
    return str(obj)


class Session:
    """The state of one conversation, and the single path for sending to its browser."""

    def __init__(self, session_id: str, menu: dict):
        self.session_id = session_id
        self.menu = menu  # {"categories": [...], "menuItems": {categoryId: [item, ...]}}
        self.order = OrderState()
        self.screen: dict[str, Any] = {**EMPTY_SCREEN}
        # The build-your-own burger in progress: {"patty", "toppings", "sauces"}, or None.
        # It is kept when the builder is hidden (e.g. to show an item), and shown again when
        # the customer carries on with it.
        self.burger_draft: dict | None = None
        # The conversation so far. Handed to each new agent, so a reconnected conversation
        # continues where it left off.
        self.messages: list = []
        self.epoch = uuid.uuid4().hex  # changes only if the Session is recreated
        self.version = 0
        self.lock = threading.RLock()
        self.last_activity = time.monotonic()
        self._ws = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._send_lock: asyncio.Lock | None = None

    # --- State ---

    @property
    def order_placed(self) -> bool:
        return bool(self.screen["orderConfirmed"])

    def mark_activity(self) -> None:
        self.last_activity = time.monotonic()

    def find_item(self, item_id: str) -> tuple[dict | None, str | None]:
        """Return (menu item, its category ID), or (None, None) if there is no such item."""
        for category_id, items in self.menu.get("menuItems", {}).items():
            for item in items:
                if item["itemId"] == item_id:
                    return item, category_id
        return None, None

    def update_screen(self, **fields) -> None:
        """Change what the screen shows and send the new state to the browser."""
        unknown = set(fields) - set(EMPTY_SCREEN)
        if unknown:
            raise ValueError(f"not screen fields: {sorted(unknown)}")
        with self.lock:
            self.screen.update(fields)
            self.version += 1
            # Posted while holding the lock, so snapshots are sent in version order
            self.post(self.snapshot_event())

    def snapshot_event(self) -> dict:
        with self.lock:
            return {
                "type": "STATE_SNAPSHOT",
                "epoch": self.epoch,
                "version": self.version,
                "snapshot": json.loads(json.dumps(self.screen, default=_json_default)),  # a deep copy
            }

    def menu_event(self) -> dict:
        return {"type": "CUSTOM", "name": "menu", "value": self.menu}

    # --- Connection ---

    def attach(self, websocket, loop: asyncio.AbstractEventLoop):
        """Make `websocket` the connection this session talks to. Returns the one it replaces."""
        with self.lock:
            previous = self._ws
            self._ws, self._loop, self._send_lock = websocket, loop, asyncio.Lock()
        self.mark_activity()
        return previous

    def detach(self, websocket) -> None:
        """Forget `websocket`, unless another connection has already replaced it."""
        with self.lock:
            if self._ws is websocket:
                self._ws, self._loop, self._send_lock = None, None, None

    def is_attached(self, websocket) -> bool:
        return self._ws is websocket

    async def send(self, event: dict, websocket=None) -> None:
        """Send an event to the browser. Every write to the socket goes through here.

        With `websocket`, the event is dropped unless that connection is still the current
        one, so an agent that is shutting down can't talk into its replacement's connection.
        """
        ws, lock = self._ws, self._send_lock
        if ws is None or lock is None or (websocket is not None and ws is not websocket):
            return
        text = json.dumps(event, default=_json_default)
        async with lock:  # one frame at a time: concurrent writes can interleave
            await ws.send_text(text)

    def post(self, event: dict) -> None:
        """Queue an event for the browser from any thread (tools run in worker threads)."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        coro = self.send(event)
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:  # the loop closed meanwhile: the browser gets the state on reconnect
            coro.close()
            return
        future.add_done_callback(_log_send_failure)


def _log_send_failure(future) -> None:
    if not future.cancelled() and future.exception() is not None:
        logger.warning("failed to send to browser: %s", future.exception())


def session_of(tool_context) -> Session:
    """The session a tool call belongs to (passed to the agent as invocation_state)."""
    return tool_context.invocation_state["session"]


# --- Sessions in this process ---
# AgentCore gives each runtime session its own microVM, so normally there is one. Locally,
# many can share a process; keep the most recent few so a reconnect finds its session.
MAX_SESSIONS = 32
_sessions: "OrderedDict[str, Session]" = OrderedDict()
_sessions_lock = threading.Lock()


def open_session(session_id: str, load_menu: Callable[[], dict]) -> tuple[Session, bool]:
    """Return (session, resumed): the existing session for this ID, or a new one."""
    with _sessions_lock:
        session = _sessions.get(session_id)
        if session is not None:
            _sessions.move_to_end(session_id)
            return session, True
    session = Session(session_id, load_menu())  # load outside the lock: it's a DynamoDB scan
    with _sessions_lock:
        session = _sessions.setdefault(session_id, session)
        _sessions.move_to_end(session_id)
        while len(_sessions) > MAX_SESSIONS:
            _sessions.popitem(last=False)
    return session, False


def close_session(session_id: str) -> None:
    """Forget a finished session, so the same ID would start a new order."""
    with _sessions_lock:
        _sessions.pop(session_id, None)
