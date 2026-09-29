# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Menu data, and the tools that show parts of the menu on the customer's screen."""

import os
from decimal import Decimal

import boto3
from strands import ToolContext, tool

try:
    from agent.session import session_of
except ModuleNotFoundError:
    from session import session_of


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

    return _convert(result)

_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
_dynamodb = boto3.resource("dynamodb", region_name=_REGION)
_table = _dynamodb.Table(os.environ.get("MENU_TABLE_NAME", "DriveThruMenu"))


def set_table(table) -> None:
    global _table
    _table = table


def get_table():
    return _table


@tool
def get_categories() -> dict:
    """Returns all menu categories."""
    response = get_table().scan(
        FilterExpression="SK = :sk",
        ExpressionAttributeValues={":sk": "METADATA"},
    )
    categories = []
    for item in response.get("Items", []):
        pk = item.get("PK", "")
        category_id = pk.replace("CATEGORY#", "") if pk.startswith("CATEGORY#") else pk
        categories.append({
            "categoryId": category_id,
            "name": str(item.get("name", "")),
            "sortOrder": int(item.get("sortOrder", 0)),
        })
    categories.sort(key=lambda c: c["sortOrder"])
    result = {"categories": categories}
    return _sanitize_result(result)


@tool
def get_items_by_category(category_id: str) -> dict:
    """Returns all menu items in a given category."""
    response = get_table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
        ExpressionAttributeValues={":pk": f"CATEGORY#{category_id}", ":sk_prefix": "ITEM#"},
    )
    items = []
    for item in response.get("Items", []):
        sk = item.get("SK", "")
        item_id = sk.replace("ITEM#", "") if sk.startswith("ITEM#") else sk
        items.append({
            "itemId": item_id,
            "name": str(item.get("name", "")),
            "description": str(item.get("description", "")),
            "price": int(item.get("price", 0)),
            "imageUrl": str(item.get("imageUrl", "")),
            "category": str(item.get("category", "")),
            "featured": bool(item.get("featured", False)),
            "sortOrder": int(item.get("sortOrder", 0)),
        })
    items.sort(key=lambda i: i["sortOrder"])
    result = {"items": items}
    return _sanitize_result(result)


@tool
def get_item_details(item_id: str, category_id: str) -> dict:
    """Returns full details for a specific menu item."""
    response = get_table().get_item(Key={"PK": f"CATEGORY#{category_id}", "SK": f"ITEM#{item_id}"})
    item = response.get("Item")
    if not item:
        return {"error": f"Item '{item_id}' not found in category '{category_id}'."}
    result = {
        "itemId": item_id,
        "categoryId": category_id,
        "name": item.get("name", ""),
        "description": item.get("description", ""),
        "price": int(item.get("price", 0)),
        "imageUrl": item.get("imageUrl", ""),
        "category": item.get("category", ""),
        "featured": bool(item.get("featured", False)),
        "sortOrder": int(item.get("sortOrder", 0)),
    }
    return _sanitize_result(result)


@tool
def get_recommendations() -> dict:
    """Returns a list of featured/popular menu items."""
    response = get_table().scan(
        FilterExpression="featured = :f AND begins_with(SK, :sk_prefix)",
        ExpressionAttributeValues={":f": True, ":sk_prefix": "ITEM#"},
    )
    items = []
    for item in response.get("Items", []):
        pk = item.get("PK", "")
        sk = item.get("SK", "")
        category_id = pk.replace("CATEGORY#", "") if pk.startswith("CATEGORY#") else pk
        item_id = sk.replace("ITEM#", "") if sk.startswith("ITEM#") else sk
        items.append({
            "itemId": item_id, "categoryId": category_id,
            "name": str(item.get("name", "")), "description": str(item.get("description", "")),
            "price": int(item.get("price", 0)), "imageUrl": str(item.get("imageUrl", "")),
            "category": str(item.get("category", "")), "featured": True,
            "sortOrder": int(item.get("sortOrder", 0)),
        })
    items.sort(key=lambda i: i["sortOrder"])
    return _sanitize_result({"items": items})


def load_menu_data() -> dict:
    """The whole menu, as the screen shows it: {"categories": [...], "menuItems": {categoryId: [...]}}.

    Loaded once per conversation. The server sends it to the screen and lists it in the
    agent's instructions, so the agent never has to fetch it.
    """
    categories = get_categories()["categories"]
    menu_items = {}
    for category in categories:
        category_id = category["categoryId"]
        menu_items[category_id] = [
            {**item, "categoryId": category_id}
            for item in get_items_by_category(category_id=category_id)["items"]
        ]
    return {"categories": categories, "menuItems": menu_items}


@tool(context=True)
def show_item(item_id: str, tool_context: ToolContext) -> dict:
    """Show a menu item's picture and details on the customer's screen, and return its details.

    Use it when the customer asks about an item, or when you describe or suggest one. When the
    customer orders an item, just add it to the order instead.

    Args:
        item_id: The item's exact itemId from the menu, e.g. "classic-burger".
    """
    session = session_of(tool_context)
    item, category_id = session.find_item(item_id)
    if item is None:
        return {"error": f"There is no item '{item_id}'. Use an exact itemId from the menu."}
    # The item's popup replaces the burger builder on screen; the burger draft is kept.
    session.update_screen(highlightedItem=item_id, highlightedCategory=category_id, burgerBuilder=None)
    return _sanitize_result({"name": item["name"], "description": item["description"], "price": item["price"]})


@tool(context=True)
def show_category(category_id: str, tool_context: ToolContext) -> dict:
    """Scroll the customer's screen to a menu category, and return the items in it.

    Use it when the customer asks what's in a category, e.g. "what drinks do you have?".

    Args:
        category_id: The category's exact categoryId from the menu, e.g. "drinks".
    """
    session = session_of(tool_context)
    items = session.menu.get("menuItems", {}).get(category_id)
    if items is None:
        return {"error": f"There is no category '{category_id}'. Use an exact categoryId from the menu."}
    session.update_screen(highlightedCategory=category_id, highlightedItem=None, burgerBuilder=None)
    return _sanitize_result({
        "items": [{"itemId": i["itemId"], "name": i["name"], "price": i["price"]} for i in items],
    })
