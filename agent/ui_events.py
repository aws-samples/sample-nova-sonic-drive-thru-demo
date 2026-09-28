# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Helper module for constructing UI_Event dicts.

UI_Events are structured JSON messages sent by the agent over the WebSocket
alongside audio frames, instructing the frontend to update its visual state.
"""


def order_update_event(order_summary: dict) -> dict:
    """Construct an order_update UI_Event.

    Args:
        order_summary: Dict with 'items' list and 'total' price in fils (1/100 AED).

    Returns:
        UI_Event dict with type 'order_update'.
    """
    return {
        "type": "order_update",
        "payload": {
            "items": order_summary.get("items", []),
            "total": order_summary.get("total", 0),
        },
    }


def order_confirmed_event(order_record: dict) -> dict:
    """Construct an order_confirmed UI_Event.

    Args:
        order_record: Dict with orderId, items, total, and createdAt.

    Returns:
        UI_Event dict with type 'order_confirmed'.
    """
    return {
        "type": "order_confirmed",
        "payload": {
            "orderNumber": order_record.get("orderId", ""),
            "items": order_record.get("items", []),
            "total": order_record.get("total", 0),
            "timestamp": order_record.get("createdAt", ""),
        },
    }


def highlight_category_event(category_id: str, category_name: str) -> dict:
    """Construct a highlight_category UI_Event.

    Args:
        category_id: The category identifier.
        category_name: The display name of the category.

    Returns:
        UI_Event dict with type 'highlight_category'.
    """
    return {
        "type": "highlight_category",
        "payload": {
            "categoryId": category_id,
            "categoryName": category_name,
        },
    }


def browse_category_event(category_id: str, category_name: str) -> dict:
    """Construct a browse_category UI_Event.

    Args:
        category_id: The category identifier.
        category_name: The display name of the category.

    Returns:
        UI_Event dict with type 'browse_category'.
    """
    return {
        "type": "browse_category",
        "payload": {
            "categoryId": category_id,
            "categoryName": category_name,
        },
    }


def highlight_item_event(item_id: str, item_name: str) -> dict:
    """Construct a highlight_item UI_Event.

    Args:
        item_id: The item identifier.
        item_name: The display name of the item.

    Returns:
        UI_Event dict with type 'highlight_item'.
    """
    return {
        "type": "highlight_item",
        "payload": {
            "itemId": item_id,
            "itemName": item_name,
        },
    }


def show_item_detail_event(item_data: dict) -> dict:
    """Construct a show_item_detail UI_Event that opens the item detail modal.

    Args:
        item_data: Dict with item details (itemId, name, description, price, etc.)

    Returns:
        UI_Event dict with type 'show_item_detail'.
    """
    return {
        "type": "show_item_detail",
        "payload": {
            "itemId": item_data.get("itemId", ""),
            "categoryId": item_data.get("categoryId", ""),
            "name": item_data.get("name", ""),
            "description": item_data.get("description", ""),
            "price": item_data.get("price", 0),
            "imageUrl": item_data.get("imageUrl", ""),
            "category": item_data.get("category", ""),
        },
    }
