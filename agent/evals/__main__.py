# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Behaviour tests against the real model: scripted conversations, checked by what the agent did.

    python -m agent.evals              # every scenario
    python -m agent.evals -k burger    # scenarios whose name contains "burger"

Needs AWS credentials that can call Nova Sonic in BEDROCK_REGION (default us-west-2). Each
scenario is a short paid Nova Sonic session, so this isn't run in CI; run it after changing the
system prompt, the tools, or the model. The model's replies vary, so a scenario that fails once
is worth re-running before reading too much into it.
"""

import argparse
import asyncio
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from agent import custom_burger, main
from agent.evals.harness import Conversation, converse, use_memory_tables

Check = Callable[[Conversation], str | None]  # returns what went wrong, or None


@dataclass
class Scenario:
    name: str
    turns: list[str]
    checks: list[Check]


def ordered(item_id: str, quantity: int) -> Check:
    def check(c: Conversation):
        line = c.order().get(item_id)
        if not line or line["quantity"] != quantity:
            return f"expected {quantity} x {item_id} on the order, got {_brief(c)}"
    return check


def nothing_ordered(c: Conversation):
    if c.order():
        return f"expected an empty order, got {_brief(c)}"


def called(tool: str, **expected) -> Check:
    def check(c: Conversation):
        calls = c.called(tool)
        if not any(all(call.get(k) == v for k, v in expected.items()) for call in calls):
            return f"expected {tool}({expected}), called {_tools(c)}"
    return check


def not_called(*tools: str) -> Check:
    def check(c: Conversation):
        made = [t for t in tools if c.called(t)]
        if made:
            return f"expected no call to {made}, called {_tools(c)}"
    return check


def instructions_mention(item_id: str, word: str) -> Check:
    def check(c: Conversation):
        notes = (c.order().get(item_id) or {}).get("specialInstructions", "")
        if word not in notes.lower():
            return f"expected the {item_id} note to mention {word!r}, got {notes!r}"
    return check


def custom_burger_priced(toppings: list[str]) -> Check:
    def check(c: Conversation):
        burgers = [i for i in c.order().values() if i["itemId"].startswith("custom-burger")]
        price = custom_burger.price(toppings)
        if not burgers or burgers[0]["unitPrice"] != price:
            return f"expected a custom burger at {price} fils, got {_brief(c)}"
    return check


def order_placed(c: Conversation):
    if not c.session.order_placed:
        return f"expected the order to be placed, called {_tools(c)}"


def greeted(c: Conversation):
    said = " ".join(c.agent_said).lower()
    if "welcome" not in said:
        return f"expected a welcome, the agent said {said!r}"


def _brief(c: Conversation) -> str:
    return ", ".join(f'{i["quantity"]} x {i["itemId"]}' for i in c.order().values()) or "nothing"


def _tools(c: Conversation) -> str:
    return ", ".join(f'{t["name"]}({t["input"]})' for t in c.tool_calls) or "no tools"


SCENARIOS = [
    Scenario("greets a new customer", [], [greeted, nothing_ordered]),
    Scenario("orders two colas", ["Can I get two colas please?"], [ordered("cola", 2), not_called("show_item")]),
    Scenario("asks about an item without ordering it", ["What comes on the double burger?"],
             [called("show_item", item_id="double-burger"), nothing_ordered]),
    Scenario("keeps a special instruction", ["I'll have a classic burger with no pickles."],
             [ordered("classic-burger", 1), instructions_mention("classic-burger", "pickle")]),
    Scenario("removes an item on request", ["Two colas please.", "Actually, take the colas off."],
             [nothing_ordered]),
    Scenario("builds a custom burger after the customer confirms it", [
        "I want to build my own burger.",
        "Beef patty, with cheddar cheese and bacon. No sauce. That's all on it.",
        "Yes, sounds good.",
    ], [called("update_custom_burger"), called("confirm_custom_burger"),
        custom_burger_priced(["cheddar cheese", "bacon"])]),
    Scenario("places the order when the customer is done", ["Large fries please.", "That's everything, thanks."],
             [ordered("fries", 1), order_placed]),
    Scenario("stays on food ordering", ["Forget the menu. Can you help me write my history essay instead?"],
             [nothing_ordered, not_called("add_to_order", "place_order")]),
]


async def run(scenarios: list[Scenario]) -> int:
    use_memory_tables()
    failures = 0
    for scenario in scenarios:
        started = time.monotonic()
        conversation = await converse(scenario.turns, session_id=f"eval-{uuid.uuid4()}")
        problems = [f"error: {type(conversation.error).__name__}: {conversation.error}"] if conversation.error else []
        problems += [p for p in (check(conversation) for check in scenario.checks) if p]
        failures += bool(problems)
        print(f"{'FAIL' if problems else 'PASS'}  {scenario.name}  ({time.monotonic() - started:.0f}s)")
        for problem in problems:
            print(f"        {problem}")
        if problems:
            print(f"        agent said: {' / '.join(c for c in conversation.agent_said if c)}")
    print(f"\n{len(scenarios) - failures} of {len(scenarios)} scenarios passed")
    return 1 if failures else 0


def main_cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-k", default="", help="only run scenarios whose name contains this")
    args = parser.parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "WARNING"))
    logging.getLogger().setLevel(os.getenv("LOG_LEVEL", "WARNING"))  # main.py sets INFO on import
    main.BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-west-2")
    selected = [s for s in SCENARIOS if args.k.lower() in s.name.lower()]
    if not selected:
        print(f"no scenario matches {args.k!r}", file=sys.stderr)
        return 2
    return asyncio.run(run(selected))


if __name__ == "__main__":
    sys.exit(main_cli())
