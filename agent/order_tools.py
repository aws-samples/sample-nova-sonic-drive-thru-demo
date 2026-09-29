# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Order management tools for the drive-thru voice ordering agent."""

import json
import logging
import os
from decimal import Decimal

import boto3
from strands import tool

try:
    from agent.order_state import OrderState
    from agent.ui_state_manager import set_ui_state, get_ui_state
except ModuleNotFoundError:
    from order_state import OrderState
    from ui_state_manager import set_ui_state, get_ui_state

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
_order_state = OrderState()


def set_tables(menu_table, orders_table) -> None:
    global _menu_table, _orders_table
    _menu_table = menu_table
    _orders_table = orders_table


def set_order_state(state: OrderState) -> None:
    global _order_state
    _order_state = state


def get_order_state() -> OrderState:
    return _order_state


def _refresh_order_display(**extra_ui_fields) -> None:
    """Show the current order on the customer's screen.

    The order state is the only source for the order items and total on screen. Every tool
    that changes the order calls this, so the display can never drift from what gets placed.
    """
    try:
        summary = _order_state.get_summary()
        current = get_ui_state()
        current["orderItems"] = summary["items"]
        current["orderTotal"] = summary["total"]
        current.update(extra_ui_fields)
        set_ui_state(current)
    except Exception as e:
        logger.warning("failed to refresh order display: %s", e)


@tool
def add_to_order(item_id: str, category_id: str, quantity: int = 1, special_instructions: str = "") -> dict:
    """Adds a menu item to the current order and updates the customer's screen.

    Args:
        item_id: The menu item identifier.
        category_id: The category the item belongs to.
        quantity: Number of items to add (must be >= 1).
        special_instructions: Customer notes like "no pickles" or "extra sauce".
    """
    logger.info("add_to_order: %s %s qty=%s notes=%s", item_id, category_id, quantity, special_instructions)
    if quantity < 1:
        return {"error": "Quantity must be at least 1."}
    response = _menu_table.get_item(Key={"PK": f"CATEGORY#{category_id}", "SK": f"ITEM#{item_id}"})
    menu_item = response.get("Item")
    if not menu_item:
        return {"error": f"Item '{item_id}' not found in category '{category_id}'."}
    _order_state.add_item(item_id, menu_item.get("name", ""), quantity, int(menu_item.get("price", 0)), special_instructions)
    summary = _order_state.get_summary()
    _refresh_order_display()  # don't highlight the item — that opens the details modal

    # Return minimal confirmation to keep tool result small for Nova Sonic
    return _sanitize_result({
        "status": "added",
        "item": str(menu_item.get("name", "")),
        "quantity": quantity,
        "total": summary["total"],
    })


@tool
def remove_from_order(item_id: str, quantity: int = 1) -> dict:
    """Removes a menu item from the current order."""
    if not _order_state.remove_item(item_id, quantity):
        return {"error": f"Item '{item_id}' is not in the current order."}
    summary = _order_state.get_summary()
    _refresh_order_display()
    return _sanitize_result({"status": "removed", "item": item_id, "total": summary["total"], "itemCount": len(summary["items"])})


@tool
def get_order_summary(tool_context=None) -> dict:
    """Returns the current order summary."""
    summary = _order_state.get_summary()
    items_brief = [f"{i['name']} x{i['quantity']}" for i in summary["items"]]
    return _sanitize_result({"items": items_brief, "total": summary["total"]})


@tool
def place_order(user_id: str = "guest") -> dict:
    """Finalizes the order, persists to DynamoDB, returns order number.
    
    Args:
        user_id: The customer identifier. Defaults to "guest".
    """
    if _order_state.is_empty():
        return {"error": "Cannot place an empty order."}
    summary = _order_state.get_summary()
    order_record = _order_state.place_order(user_id)
    _orders_table.put_item(Item=order_record)
    logger.info(
        "ORDER_PLACED: orderId=%s orderNumber=%s userId=%s total=%s itemCount=%s",
        order_record["orderId"],
        order_record["orderNumber"],
        order_record["userId"],
        order_record["total"],
        len(order_record["items"]),
    )
    _order_state.cancel()

    # Show the confirmation screen with exactly the order that was just persisted
    try:
        current = get_ui_state()
        current["orderItems"] = summary["items"]
        current["orderTotal"] = summary["total"]
        current["orderConfirmed"] = True
        current["orderNumber"] = order_record["orderNumber"]
        current["burgerBuilder"] = None
        current["highlightedItem"] = None
        current["highlightedCategory"] = None
        set_ui_state(current)
    except Exception as e:
        logger.warning("place_order: failed to update UI: %s", e)

    return _sanitize_result({"status": "confirmed", "orderNumber": order_record["orderNumber"], "total": order_record["total"]})


@tool
def cancel_order(tool_context=None) -> dict:
    """Clears all items from the current order."""
    logger.info("ORDER_CANCELLED: itemCount=%s", len(_order_state.items))
    _order_state.cancel()
    _refresh_order_display()
    return _sanitize_result({"status": "cancelled"})


# --- Custom Burger Builder ---

# Base price in fils (100 fils = 1 AED), plus per-topping prices.
# Mirrored in frontend App.tsx / BurgerBuilder.tsx and the system prompt in main.py.
_CUSTOM_BURGER_BASE_PRICE = 3300  # AED 33.00 for patty + bun
_TOPPING_PRICES = {
    # Patty options (included in base)
    "beef patty": 0,
    "chicken patty": 0,
    # Cheese (+AED 4.00)
    "american cheese": 400,
    "cheddar cheese": 400,
    "pepper jack cheese": 400,
    "swiss cheese": 400,
    # Premium toppings (+AED 6.00)
    "bacon": 600,
    "avocado": 600,
    "fried egg": 600,
    # Free toppings
    "lettuce": 0,
    "tomato": 0,
    "onion": 0,
    "pickles": 0,
    "jalapeños": 0,
    "mushrooms": 0,
    # Sauces (free)
    "ketchup": 0,
    "mustard": 0,
    "mayo": 0,
    "bbq sauce": 0,
    "chipotle mayo": 0,
    "special sauce": 0,
}


def custom_burger_price(toppings) -> int:
    """Price in fils of a custom burger with the given toppings.

    The single price calculation for custom burgers: used for the builder preview on screen
    and for the item added to the order. Unknown toppings add nothing; build_custom_burger
    rejects them before pricing.
    """
    return _CUSTOM_BURGER_BASE_PRICE + sum(
        _TOPPING_PRICES.get(str(t).lower().strip(), 0) for t in (toppings or [])
    )


@tool
def build_custom_burger(patty: str, toppings: list, sauces: list = None, quantity: int = 1) -> dict:
    """Build a custom burger with chosen patty, toppings, and sauces. Adds it to the order.

    Args:
        patty: The patty type — "beef patty" or "chicken patty".
        toppings: List of toppings. Options: "american cheese", "cheddar cheese",
            "pepper jack cheese", "swiss cheese", "bacon", "avocado", "fried egg",
            "lettuce", "tomato", "onion", "pickles", "jalapeños", "mushrooms".
        sauces: List of sauces. Options: "ketchup", "mustard", "mayo", "bbq sauce",
            "chipotle mayo", "special sauce". Defaults to none.
        quantity: Number of custom burgers (default 1).

    Returns:
        Summary with the custom burger details, price breakdown, and updated order.
    """
    if sauces is None:
        sauces = []
    if quantity < 1:
        return {"error": "Quantity must be at least 1."}

    # Validate patty
    patty = patty.lower().strip()
    if patty not in ("beef patty", "chicken patty"):
        return {"error": f"Invalid patty '{patty}'. Choose 'beef patty' or 'chicken patty'."}

    selected_toppings = []
    for topping in toppings:
        topping = topping.lower().strip()
        if topping not in _TOPPING_PRICES:
            return {"error": f"Unknown topping '{topping}'. Available: {', '.join(sorted(_TOPPING_PRICES.keys()))}"}
        selected_toppings.append(topping)
    total_price = custom_burger_price(selected_toppings)

    selected_sauces = []
    for sauce in sauces:
        sauce = sauce.lower().strip()
        if sauce not in _TOPPING_PRICES:
            return {"error": f"Unknown sauce '{sauce}'. Available: ketchup, mustard, mayo, bbq sauce, chipotle mayo, special sauce."}
        selected_sauces.append(sauce)

    # Build description for the order
    parts = [patty]
    if selected_toppings:
        parts.extend(selected_toppings)
    if selected_sauces:
        parts.extend(selected_sauces)
    description = ", ".join(parts)

    # Use a unique item ID for each custom burger configuration
    import hashlib
    config_hash = hashlib.md5(description.encode()).hexdigest()[:6]
    item_id = f"custom-burger-{config_hash}"
    name = "Custom Burger"

    logger.info("build_custom_burger: %s toppings=%s sauces=%s price=%s", patty, selected_toppings, selected_sauces, total_price)

    _order_state.add_item(item_id, name, quantity, total_price, description)
    summary = _order_state.get_summary()
    _refresh_order_display(burgerBuilder=None, highlightedItem=None)  # close the builder

    return _sanitize_result({
        "status": "added",
        "item": "Custom Burger",
        "patty": patty,
        "toppings": selected_toppings,
        "sauces": selected_sauces,
        "price": f"AED {total_price / 100:.2f}",
        "total": summary["total"],
    })
