# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""One drive-thru conversation: the order, what the screen shows, and the link to the browser.

A Session outlives any single WebSocket connection. If the connection drops, the browser
reconnects with the same AgentCore session ID (which AgentCore routes to the same microVM),
picks up the same Session, and the customer carries on with their order.

Tools reach the session through the Strands tool context (see `session_of`), so no state
lives in module globals. Tools run in worker threads, in parallel, so every change to the
session's state happens under `session.lock`.

The messages to the browser are defined in protocol.py: JSON text frames for the menu, screen
state and session events, and binary frames for the agent's voice.
"""

import asyncio
import logging
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Callable

try:
    from agent import protocol
    from agent.order_state import OrderState
except ModuleNotFoundError:
    import protocol
    from order_state import OrderState

logger = logging.getLogger(__name__)

# Everything the screen shows apart from the menu (protocol.ScreenState). Only the tools change it.
EMPTY_SCREEN: dict[str, Any] = protocol.ScreenState().model_dump()


class Session:
    """The state of one conversation, and the single path for sending to its browser."""

    def __init__(self, session_id: str, menu: dict):
        self.session_id = session_id
        # {"categories": [...], "menuItems": {categoryId: [item, ...]}}, checked against the protocol
        self.menu = protocol.Menu.model_validate(menu).model_dump()
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
        """Change what the screen shows and send the new state to the browser.

        Raises ValueError (a pydantic ValidationError) if the new state doesn't fit
        protocol.ScreenState, e.g. an unknown field; the screen is then left as it was.
        """
        with self.lock:
            screen = protocol.ScreenState.model_validate({**self.screen, **fields})
            self.screen = screen.model_dump()
            self.version += 1
            # Posted while holding the lock, so snapshots are sent in version order
            self.post(self._snapshot_event(screen))

    def snapshot_event(self) -> protocol.StateSnapshotEvent:
        with self.lock:
            return self._snapshot_event(protocol.ScreenState.model_validate(self.screen))

    def _snapshot_event(self, screen: protocol.ScreenState) -> protocol.StateSnapshotEvent:
        return protocol.StateSnapshotEvent(epoch=self.epoch, version=self.version, snapshot=screen)

    def menu_event(self) -> protocol.MenuEvent:
        return protocol.MenuEvent(value=protocol.Menu.model_validate(self.menu))

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

    async def send(self, event: protocol.ServerEvent, websocket=None) -> None:
        """Send a message to the browser, as a JSON text frame.

        With `websocket`, the message is dropped unless that connection is still the current
        one, so an agent that is shutting down can't talk into its replacement's connection.
        """
        await self._write(event.model_dump_json(), websocket)

    async def send_audio(self, pcm: bytes, websocket=None) -> None:
        """Send the agent's voice to the browser, as a binary frame of protocol.AUDIO_FORMAT audio."""
        await self._write(pcm, websocket)

    async def _write(self, frame: str | bytes, websocket) -> None:
        """Every write to the socket goes through here."""
        ws, lock = self._ws, self._send_lock
        if ws is None or lock is None or (websocket is not None and ws is not websocket):
            return
        async with lock:  # one frame at a time: concurrent writes can interleave
            if isinstance(frame, bytes):
                await ws.send_bytes(frame)
            else:
                await ws.send_text(frame)

    def post(self, event: protocol.ServerEvent) -> None:
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
