# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Helpers for calling tools the way the agent does: with a session in the tool context."""

from types import SimpleNamespace

from agent.session import Session


def make_session(menu: dict | None = None, session_id: str = "test-session") -> Session:
    return Session(session_id, menu or {"categories": [], "menuItems": {}})


def context(session: Session) -> SimpleNamespace:
    """A stand-in for the Strands ToolContext: tools only read invocation_state["session"]."""
    return SimpleNamespace(invocation_state={"session": session})


def screen_order(session: Session):
    """The order as the customer's screen shows it: ([(itemId, quantity), ...], total)."""
    return [(i["itemId"], i["quantity"]) for i in session.screen["orderItems"]], session.screen["orderTotal"]
