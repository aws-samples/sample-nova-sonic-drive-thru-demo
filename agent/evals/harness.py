# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Runs one scripted conversation against the real model, with the agent's real tools and prompt.

The customer's turns are sent as text (Nova Sonic takes text input as the user speaking), with
silence streamed as audio in between, as the browser's microphone does. DynamoDB is replaced by
an in-memory table seeded from data/menu_items.json, so the only AWS call is to Bedrock.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from strands.bidi import BidiAgent

from agent import main, menu_tools, order_tools, session as sessions

logger = logging.getLogger(__name__)

MENU_DATA = Path(__file__).resolve().parents[2] / "data" / "menu_items.json"
SILENCE = bytes(1280)  # 40 ms of 16 kHz 16-bit mono audio, as the browser sends
# The agent has finished a turn once it has been quiet (no audio, transcript or tool use) this long
QUIET_SECONDS = 2.5
TURN_TIMEOUT_SECONDS = 45


class MemoryTable:
    """The DynamoDB calls the tools make, on rows kept in memory."""

    def __init__(self, rows: list[dict]):
        self.rows = [json.loads(json.dumps(r), parse_float=Decimal) for r in rows]

    def get_item(self, Key):
        for row in self.rows:
            if row["PK"] == Key["PK"] and row["SK"] == Key["SK"]:
                return {"Item": row}
        return {}

    def put_item(self, Item):
        self.rows.append(Item)

    def query(self, KeyConditionExpression, ExpressionAttributeValues):
        pk, prefix = ExpressionAttributeValues[":pk"], ExpressionAttributeValues[":sk_prefix"]
        return {"Items": [r for r in self.rows if r.get("PK") == pk and str(r.get("SK", "")).startswith(prefix)]}

    def scan(self, FilterExpression, ExpressionAttributeValues):
        values = ExpressionAttributeValues
        if ":sk" in values:  # get_categories
            return {"Items": [r for r in self.rows if r.get("SK") == values[":sk"]]}
        # get_recommendations: featured items
        return {"Items": [r for r in self.rows if r.get("featured") is True
                          and str(r.get("SK", "")).startswith(values[":sk_prefix"])]}


def use_memory_tables() -> MemoryTable:
    """Point the tools at in-memory tables. Returns the orders table, to inspect placed orders."""
    menu = MemoryTable(json.loads(MENU_DATA.read_text(encoding="utf-8")))
    orders = MemoryTable([])
    menu_tools.set_table(menu)
    order_tools.set_tables(menu, orders)
    return orders


@dataclass
class Conversation:
    """What happened: the tools the agent called, what it said, and the session it left."""

    session: sessions.Session
    tool_calls: list[dict] = field(default_factory=list)  # {"name", "input"}
    agent_said: list[str] = field(default_factory=list)
    error: BaseException | None = None
    ended: bool = False  # the agent ended the conversation itself

    def called(self, name: str) -> list[dict]:
        return [c["input"] for c in self.tool_calls if c["name"] == name]

    def order(self) -> dict[str, dict]:
        """The order on screen, by item ID."""
        return {i["itemId"]: i for i in self.session.screen["orderItems"]}


async def converse(turns: list[str], session_id: str) -> Conversation:
    """Greet a new customer, then say each turn once the agent has finished its reply."""
    session = sessions.Session(session_id, menu_tools.load_menu_data())
    conversation = Conversation(session)
    agent = BidiAgent(
        model=main._new_model(), tools=main.TOOLS,
        system_prompt=main.build_system_prompt(session), messages=session.messages,
    )
    pending = asyncio.Queue()
    pending.put_nowait(main.GREETING_CUE)
    last_activity = [time.monotonic()]

    async def receive():
        try:
            return pending.get_nowait()
        except asyncio.QueueEmpty:
            await asyncio.sleep(0.04)
            return main.audio_input_event(SILENCE)

    async def send(event):
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        if kind in ("bidi_audio_delta", "bidi_transcript_delta", "bidi_tool_use_blocks"):
            last_activity[0] = time.monotonic()
        if kind == "bidi_tool_use_blocks":
            conversation.tool_calls += [{"name": t["name"], "input": t.get("input") or {}} for t in event["tool_uses"]]
        elif kind == "bidi_transcript_block" and event.get("role") == "assistant":
            conversation.agent_said.append(str(event.get("transcript", "")))

    async def wait_for_reply():
        started = time.monotonic()
        await asyncio.sleep(1.0)  # let the reply start
        while time.monotonic() - last_activity[0] < QUIET_SECONDS:
            if time.monotonic() - started > TURN_TIMEOUT_SECONDS:
                raise TimeoutError("the agent never went quiet")
            await asyncio.sleep(0.2)

    run = asyncio.create_task(agent.run(inputs=[receive], outputs=[send], invocation_state={"session": session}))
    try:
        for turn in [None, *turns]:  # None: the greeting, already queued
            if turn is not None:
                last_activity[0] = time.monotonic()
                pending.put_nowait(turn)
            waiter = asyncio.create_task(wait_for_reply())
            done, _ = await asyncio.wait({waiter, run}, return_when=asyncio.FIRST_COMPLETED)
            if run in done:
                waiter.cancel()
                conversation.ended = run.exception() is None
                conversation.error = run.exception()
                break
            waiter.result()
    except Exception as error:  # noqa: BLE001 - reported per scenario
        conversation.error = error
    finally:
        if not run.done():
            run.cancel()
            await asyncio.gather(run, return_exceptions=True)
    return conversation
