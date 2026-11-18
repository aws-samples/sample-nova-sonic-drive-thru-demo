# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Order tools for the drive-thru voice ordering agent: the order, and the build-your-own burger.

Each tool works on the conversation's Session (from the tool context) and is the only writer of
the order and prices on screen, so the screen always shows what would be placed.
"""

import hashlib
import json
import logging
import os
from decimal import Decimal

import boto3
from strands import ToolContext, tool

try:
    from agent import custom_burger
    from agent.session import Session, session_of
except ModuleNotFoundError:
    import custom_burger
    from session import Session, session_of

logger = logging.getLogger(__name__)


def _sanitize_result(result: dict) -> dict:
    """Ensure tool result is JSON-serializable with only basic Python types."""
    def _convert(obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj == int(obj) else float(obj)
        if isinstance(obj, dict):
            return {str(k): _convert(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_convert(i) for i in obj]
        if isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        return str(obj)

    sanitized = _convert(result)
    try:
        json.dumps(sanitized)
    except (TypeError, ValueError) as e:
        logger.error("Tool result not JSON-serializable: %s | result: %s", e, sanitized)
        return {"status": "ok"}
    return sanitized

_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
_dynamodb = boto3.resource("dynamodb", region_name=_REGION)
_menu_table = _dynamodb.Table(os.environ.get("MENU_TABLE_NAME", "DriveThruMenu"))
_orders_table = _dynamodb.Table(os.environ.get("ORDERS_TABLE_NAME", "DriveThruOrders"))


def set_tables(menu_table, orders_table) -> None:
    global _menu_table, _orders_table
    _menu_table = menu_table
    _orders_table = orders_table


def _refresh_order_display(session: Session, **extra_screen_fields) -> None:
    """Show the session's current order on the customer's screen.

    The order state is the only source for the order items and total on screen. Every tool
    that changes the order calls this, so the display can never drift from what gets placed.
    It also closes any item popup: the screen is voice-driven, so nobody else will close it,
    and once the order changes the customer has moved on from that item.
    """
    summary = session.order.get_summary()
    session.update_screen(
        orderItems=summary["items"], orderTotal=summary["total"], highlightedItem=None, **extra_screen_fields,
    )


@tool(context=True)
def add_to_order(
    item_id: str, category_id: str, tool_context: ToolContext, quantity: int = 1, special_instructions: str = "",
) -> dict:
    """Adds a menu item to the current order and updates the customer's screen.

    Args:
        item_id: The menu item identifier.
        category_id: The category the item belongs to.
        quantity: Number of items to add (must be >= 1).
        special_instructions: Customer notes like "no pickles" or "extra sauce".
    """
    session = session_of(tool_context)
    logger.info("add_to_order: %s %s qty=%s notes=%s", item_id, category_id, quantity, special_instructions)
    if quantity < 1:
        return {"error": "Quantity must be at least 1."}
    response = _menu_table.get_item(Key={"PK": f"CATEGORY#{category_id}", "SK": f"ITEM#{item_id}"})
    menu_item = response.get("Item")
    if not menu_item:
        return {"error": f"Item '{item_id}' not found in category '{category_id}'."}
    with session.lock:
        session.order.add_item(
            item_id, menu_item.get("name", ""), quantity, int(menu_item.get("price", 0)), special_instructions,
        )
        _refresh_order_display(session)
        total = session.order.get_total()

    # Return minimal confirmation to keep tool result small for Nova Sonic
    return _sanitize_result({
        "status": "added",
        "item": str(menu_item.get("name", "")),
        "quantity": quantity,
        "total": total,
    })


@tool(context=True)
def remove_from_order(item_id: str, tool_context: ToolContext, quantity: int = 1) -> dict:
    """Removes a menu item from the current order."""
    session = session_of(tool_context)
    with session.lock:
        if not session.order.remove_item(item_id, quantity):
            return {"error": f"Item '{item_id}' is not in the current order."}
        _refresh_order_display(session)
        summary = session.order.get_summary()
    return _sanitize_result({"status": "removed", "item": item_id, "total": summary["total"], "itemCount": len(summary["items"])})


@tool(context=True)
def get_order_summary(tool_context: ToolContext) -> dict:
    """Returns the current order summary."""
    summary = session_of(tool_context).order.get_summary()
    items_brief = [f"{i['name']} x{i['quantity']}" for i in summary["items"]]
    return _sanitize_result({"items": items_brief, "total": summary["total"]})


@tool(context=True)
def place_order(tool_context: ToolContext) -> dict:
    """Finalizes the order, persists it, and returns the order number to read to the customer."""
    session = session_of(tool_context)
    # Held throughout, so two calls at once can't both place the same order
    with session.lock:
        if session.order.is_empty():
            return {"error": "Cannot place an empty order."}
        summary = session.order.get_summary()
        order_record = session.order.place_order(session.session_id)
        _orders_table.put_item(Item=order_record)
        logger.info(
            "ORDER_PLACED: orderId=%s orderNumber=%s sessionId=%s total=%s itemCount=%s",
            order_record["orderId"],
            order_record["orderNumber"],
            order_record["sessionId"],
            order_record["total"],
            len(order_record["items"]),
        )
        session.order.cancel()
        session.burger_draft = None
        # Show the confirmation screen with exactly the order that was just persisted
        session.update_screen(
            orderItems=summary["items"], orderTotal=summary["total"], orderConfirmed=True,
            orderNumber=order_record["orderNumber"], burgerBuilder=None, highlightedItem=None,
            highlightedCategory=None,
        )

    return _sanitize_result({"status": "confirmed", "orderNumber": order_record["orderNumber"], "total": order_record["total"]})


@tool(context=True)
def cancel_order(tool_context: ToolContext) -> dict:
    """Clears all items from the current order."""
    session = session_of(tool_context)
    with session.lock:
        logger.info("ORDER_CANCELLED: itemCount=%s", len(session.order.items))
        session.order.cancel()
        _refresh_order_display(session)
    return _sanitize_result({"status": "cancelled"})


# --- Build-your-own burger ---
# The options and prices are defined once, in custom_burger.py.
PATTIES, TOPPINGS, SAUCES = custom_burger.PATTIES, custom_burger.TOPPINGS, custom_burger.SAUCES
custom_burger_price = custom_burger.price


def _normalize(names, allowed: tuple, kind: str) -> tuple[list[str], str | None]:
    """Lower-case and validate names. Returns (names, error message or None)."""
    result = []
    for name in names or []:
        name = str(name).lower().strip()
        if name not in allowed:
            return [], f"Unknown {kind} '{name}'. Options: {', '.join(allowed)}."
        result.append(name)
    return result, None


def _builder_view(draft: dict) -> dict:
    """The burger builder as the screen shows it, priced by the server."""
    return {**draft, "active": True, "price": custom_burger_price(draft["toppings"])}


@tool(context=True)
def update_custom_burger(
    tool_context: ToolContext,
    patty: str | None = None,
    add_toppings: list[str] | None = None,
    remove_toppings: list[str] | None = None,
    add_sauces: list[str] | None = None,
    remove_sauces: list[str] | None = None,
) -> dict:
    """Start or change the customer's build-your-own burger, which is shown on their screen as it's built.

    Call it with no arguments to start, then each time the customer chooses something, passing
    only what changed. The burger so far is kept until it is confirmed or cancelled.

    Args:
        patty: The patty, by its exact name from your instructions, e.g. "beef patty".
        add_toppings: Toppings to add, by their exact names from your instructions, e.g. "cheddar cheese".
        remove_toppings: Toppings to take off.
        add_sauces: Sauces to add, by their exact names from your instructions, e.g. "bbq sauce".
        remove_sauces: Sauces to take off.

    Returns:
        The burger so far and its price in fils.
    """
    session = session_of(tool_context)
    patties, error = _normalize([patty] if patty else [], PATTIES, "patty")
    if error:
        return {"error": error}
    changes = {}
    for key, names, allowed, kind in (
        ("add_toppings", add_toppings, TOPPINGS, "topping"), ("remove_toppings", remove_toppings, TOPPINGS, "topping"),
        ("add_sauces", add_sauces, SAUCES, "sauce"), ("remove_sauces", remove_sauces, SAUCES, "sauce"),
    ):
        changes[key], error = _normalize(names, allowed, kind)
        if error:
            return {"error": error}

    with session.lock:
        draft = session.burger_draft or {"patty": None, "toppings": [], "sauces": []}
        toppings = [t for t in draft["toppings"] if t not in changes["remove_toppings"]]
        toppings += [t for t in changes["add_toppings"] if t not in toppings]
        sauces = [s for s in draft["sauces"] if s not in changes["remove_sauces"]]
        sauces += [s for s in changes["add_sauces"] if s not in sauces]
        draft = {"patty": patties[0] if patties else draft["patty"], "toppings": toppings, "sauces": sauces}
        session.burger_draft = draft
        view = _builder_view(draft)
        session.update_screen(burgerBuilder=view, highlightedItem=None)

    logger.info("update_custom_burger: %s", draft)
    return _sanitize_result({
        "patty": draft["patty"], "toppings": draft["toppings"], "sauces": draft["sauces"], "price": view["price"],
    })


@tool(context=True)
def confirm_custom_burger(tool_context: ToolContext, quantity: int = 1) -> dict:
    """Add the build-your-own burger to the order. Only call it after the customer confirms the burger.

    Args:
        quantity: Number of these burgers (default 1).
    """
    session = session_of(tool_context)
    if quantity < 1:
        return {"error": "Quantity must be at least 1."}
    with session.lock:
        draft = session.burger_draft
        if not draft:
            return {"error": "There is no custom burger in progress. Start one with update_custom_burger."}
        if not draft["patty"]:
            return {"error": "Choose a patty first: beef patty or chicken patty."}
        description = ", ".join([draft["patty"], *draft["toppings"], *draft["sauces"]])
        # The same configuration adds to the same line; a different one gets its own line
        item_id = f"custom-burger-{hashlib.md5(description.encode()).hexdigest()[:6]}"
        price = custom_burger_price(draft["toppings"])
        session.order.add_item(item_id, "Custom Burger", quantity, price, description)
        session.burger_draft = None
        _refresh_order_display(session, burgerBuilder=None)  # close the builder
        total = session.order.get_total()

    logger.info("confirm_custom_burger: %s x%s price=%s", description, quantity, price)
    return _sanitize_result({"status": "added", "item": "Custom Burger", "quantity": quantity, "price": price, "total": total})


@tool(context=True)
def cancel_custom_burger(tool_context: ToolContext) -> dict:
    """Throw away the build-your-own burger in progress and close the builder."""
    session = session_of(tool_context)
    with session.lock:
        session.burger_draft = None
        session.update_screen(burgerBuilder=None)
    return {"status": "cancelled"}
