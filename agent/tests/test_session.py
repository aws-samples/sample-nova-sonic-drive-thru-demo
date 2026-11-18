# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the Session: screen state, versioned snapshots, and the one send path."""

import asyncio
import json
import threading

import pytest

from agent import menu_tools, session as sessions
from agent.tests.support import context, make_session

MENU = {
    "categories": [{"categoryId": "drinks", "name": "Drinks", "sortOrder": 1}],
    "menuItems": {"drinks": [
        {"itemId": "cola", "categoryId": "drinks", "name": "Cola", "description": "Fizzy", "price": 900},
        {"itemId": "lemonade", "categoryId": "drinks", "name": "Lemonade", "description": "Fresh", "price": 1100},
    ]},
}


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        await asyncio.sleep(0)  # give other senders a chance to interleave, if they could
        self.sent.append(json.loads(text))

    async def send_bytes(self, data):
        await asyncio.sleep(0)
        self.sent.append(data)


class TestScreenState:
    def test_every_change_gets_a_new_version(self):
        session = make_session(MENU)
        assert session.snapshot_event().version == 0
        session.update_screen(highlightedCategory="drinks")
        session.update_screen(highlightedItem="cola")
        snapshot = session.snapshot_event().model_dump()
        assert snapshot["type"] == "STATE_SNAPSHOT"
        assert snapshot["epoch"] == session.epoch
        assert snapshot["version"] == 2
        assert snapshot["snapshot"]["highlightedItem"] == "cola"

    def test_only_screen_fields_can_be_set(self):
        session = make_session(MENU)
        with pytest.raises(ValueError):
            session.update_screen(categories=[])  # the menu is sent separately
        assert session.version == 0

    def test_a_screen_that_does_not_fit_the_protocol_is_rejected_and_nothing_changes(self):
        session = make_session(MENU)
        with pytest.raises(ValueError):
            session.update_screen(highlightedItem="cola", orderItems=[{"itemId": "cola", "quantity": 1}])
        assert session.version == 0
        assert session.screen["highlightedItem"] is None

    def test_snapshot_is_a_copy(self):
        session = make_session(MENU)
        line = {"itemId": "cola", "name": "Cola", "quantity": 1, "unitPrice": 900, "specialInstructions": ""}
        session.update_screen(orderItems=[line])
        snapshot = session.snapshot_event()
        snapshot.snapshot.orderItems.clear()
        assert session.screen["orderItems"] == [line]

    def test_a_new_session_has_a_new_epoch(self):
        assert make_session(MENU).epoch != make_session(MENU).epoch


class TestSending:
    def test_updates_from_many_threads_arrive_whole_and_in_version_order(self):
        """Tools run in parallel worker threads; the browser must still get every snapshot, in order."""
        async def scenario():
            session = make_session(MENU)
            ws = FakeWebSocket()
            session.attach(ws, asyncio.get_running_loop())

            def tool_thread(n):
                for i in range(20):
                    session.update_screen(highlightedItem=f"{n}-{i}")

            await asyncio.gather(*(asyncio.to_thread(tool_thread, n) for n in range(5)))
            for _ in range(200):  # let the posted sends run
                if len(ws.sent) == 100:
                    break
                await asyncio.sleep(0.01)
            return ws.sent

        sent = asyncio.run(scenario())
        versions = [event["version"] for event in sent]
        assert versions == list(range(1, 101))

    def test_send_to_a_replaced_connection_is_dropped(self):
        async def scenario():
            session = make_session(MENU)
            old, new = FakeWebSocket(), FakeWebSocket()
            session.attach(old, asyncio.get_running_loop())
            assert session.attach(new, asyncio.get_running_loop()) is old
            await session.send_audio(b"old", websocket=old)  # the old agent, shutting down
            await session.send_audio(b"new", websocket=new)
            session.detach(old)  # the old connection's cleanup must not detach the new one
            assert session.is_attached(new)
            return old.sent, new.sent

        old_sent, new_sent = asyncio.run(scenario())
        assert old_sent == []
        assert new_sent == [b"new"]

    def test_updates_without_a_connection_are_kept_for_the_next_one(self):
        session = make_session(MENU)
        session.update_screen(highlightedItem="cola")  # e.g. while the browser is reconnecting
        assert session.snapshot_event().snapshot.highlightedItem == "cola"


class TestSessionRegistry:
    @pytest.fixture(autouse=True)
    def clean_registry(self):
        sessions._sessions.clear()
        yield
        sessions._sessions.clear()

    def test_reconnecting_with_the_same_id_resumes_the_session(self):
        first, resumed = sessions.open_session("abc", lambda: MENU)
        assert not resumed
        again, resumed = sessions.open_session("abc", lambda: pytest.fail("menu reloaded on resume"))
        assert resumed and again is first

    def test_a_closed_session_starts_over(self):
        first, _ = sessions.open_session("abc", lambda: MENU)
        sessions.close_session("abc")
        second, resumed = sessions.open_session("abc", lambda: MENU)
        assert not resumed and second is not first

    def test_old_sessions_are_forgotten(self, monkeypatch):
        monkeypatch.setattr(sessions, "MAX_SESSIONS", 2)
        for session_id in ("a", "b", "c"):
            sessions.open_session(session_id, lambda: MENU)
        assert list(sessions._sessions) == ["b", "c"]

    def test_concurrent_opens_share_one_session(self):
        results = []
        barrier = threading.Barrier(4)

        def open_it():
            barrier.wait()
            results.append(sessions.open_session("abc", lambda: MENU)[0])

        threads = [threading.Thread(target=open_it) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len({id(s) for s in results}) == 1


class TestShowTools:
    def test_show_item_opens_its_popup_in_its_category(self):
        session = make_session(MENU)
        result = menu_tools.show_item(item_id="cola", tool_context=context(session))
        assert result == {"name": "Cola", "description": "Fizzy", "price": 900}
        assert session.screen["highlightedItem"] == "cola"
        assert session.screen["highlightedCategory"] == "drinks"

    def test_show_item_rejects_unknown_items(self):
        session = make_session(MENU)
        assert "error" in menu_tools.show_item(item_id="caviar", tool_context=context(session))
        assert session.version == 0

    def test_show_category_scrolls_and_lists_its_items(self):
        session = make_session(MENU)
        session.update_screen(highlightedItem="cola")
        result = menu_tools.show_category(category_id="drinks", tool_context=context(session))
        assert [i["itemId"] for i in result["items"]] == ["cola", "lemonade"]
        assert session.screen["highlightedCategory"] == "drinks"
        assert session.screen["highlightedItem"] is None

    def test_show_category_rejects_unknown_categories(self):
        assert "error" in menu_tools.show_category(category_id="wine", tool_context=context(make_session(MENU)))
