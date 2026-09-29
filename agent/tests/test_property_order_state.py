# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Property-based tests for OrderState.

Property 5: add_to_order correctly updates order state
**Validates: Requirements 3.2, 3.3**

Property 6: remove_from_order correctly reduces order state
**Validates: Requirements 3.5**
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from agent.order_state import OrderState, MAX_QUANTITY_PER_ITEM


# Strategy for generating a valid item entry
item_ids = st.text(min_size=1, max_size=20)
item_names = st.text(min_size=1, max_size=50)
quantities = st.integers(min_value=1, max_value=MAX_QUANTITY_PER_ITEM)
unit_prices = st.integers(min_value=1, max_value=100_000)


@settings(max_examples=100)
@given(
    item_id=item_ids,
    name=item_names,
    quantity=quantities,
    unit_price=unit_prices,
)
def test_add_new_item_updates_quantity_and_total(
    item_id: str, name: str, quantity: int, unit_price: int
) -> None:
    """Adding a new item sets its quantity and increases total by quantity * unitPrice.

    **Validates: Requirements 3.2, 3.3**
    """
    state = OrderState()
    total_before = state.get_total()

    state.add_item(item_id, name, quantity, unit_price)

    assert state.items[item_id].quantity == quantity
    assert state.get_total() == total_before + quantity * unit_price


@settings(max_examples=100)
@given(
    item_id=item_ids,
    name=item_names,
    initial_qty=st.integers(min_value=1, max_value=MAX_QUANTITY_PER_ITEM // 2),
    add_qty=st.integers(min_value=1, max_value=MAX_QUANTITY_PER_ITEM // 2),
    unit_price=unit_prices,
)
def test_add_existing_item_increments_quantity_and_total(
    item_id: str, name: str, initial_qty: int, add_qty: int, unit_price: int
) -> None:
    """Adding to an existing item increments quantity and increases total correctly.

    **Validates: Requirements 3.2, 3.3**
    """
    state = OrderState()
    state.add_item(item_id, name, initial_qty, unit_price)

    qty_before = state.items[item_id].quantity
    total_before = state.get_total()

    state.add_item(item_id, name, add_qty, unit_price)

    assert state.items[item_id].quantity == qty_before + add_qty
    assert state.get_total() == total_before + add_qty * unit_price


# ---------------------------------------------------------------------------
# Property 6: remove_from_order correctly reduces order state
# ---------------------------------------------------------------------------

# Strategy: generate a list of distinct order items, then pick one to remove
order_line = st.fixed_dictionaries(
    {
        "item_id": item_ids,
        "name": item_names,
        "quantity": st.integers(min_value=1, max_value=MAX_QUANTITY_PER_ITEM),
        "unit_price": unit_prices,
    }
)


@st.composite
def order_with_removal(draw: st.DrawFn):
    """Generate an OrderState with at least one item and a removal request.

    Returns (OrderState, item_id_to_remove, removal_quantity).
    """
    # Generate 1-5 distinct items
    items = draw(
        st.lists(order_line, min_size=1, max_size=5, unique_by=lambda x: x["item_id"])
    )

    state = OrderState()
    for item in items:
        state.add_item(
            item["item_id"], item["name"], item["quantity"], item["unit_price"]
        )

    # Pick a random item to remove
    target = draw(st.sampled_from(items))
    target_qty = target["quantity"]

    # Choose removal quantity: either partial (< current qty) or full (>= current qty)
    remove_qty = draw(st.integers(min_value=1, max_value=target_qty))

    return state, target["item_id"], remove_qty, target_qty, target["unit_price"]


@settings(max_examples=100)
@given(data=order_with_removal())
def test_remove_item_partial_reduces_quantity_and_total(data):
    """Partial removal reduces quantity and decreases total by removal_qty * unit_price.

    **Validates: Requirements 3.5**
    """
    state, item_id, remove_qty, original_qty, unit_price = data

    total_before = state.get_total()
    qty_before = state.items[item_id].quantity

    result = state.remove_item(item_id, remove_qty)

    assert result is True

    expected_new_qty = qty_before - remove_qty
    if expected_new_qty > 0:
        # Item still present with reduced quantity
        assert item_id in state.items
        assert state.items[item_id].quantity == expected_new_qty
    else:
        # Item fully removed
        assert item_id not in state.items

    assert state.get_total() == total_before - remove_qty * unit_price


@settings(max_examples=100)
@given(
    item_id=item_ids,
    name=item_names,
    quantity=quantities,
    unit_price=unit_prices,
)
def test_remove_item_full_deletes_item_and_decreases_total(
    item_id: str, name: str, quantity: int, unit_price: int
):
    """Removing the exact quantity of an item deletes it and decreases total to zero for that item.

    **Validates: Requirements 3.5**
    """
    state = OrderState()
    state.add_item(item_id, name, quantity, unit_price)

    total_before = state.get_total()

    result = state.remove_item(item_id, quantity)

    assert result is True
    assert item_id not in state.items
    assert state.get_total() == total_before - quantity * unit_price


# ---------------------------------------------------------------------------
# Property 7: cancel_order clears all items
# ---------------------------------------------------------------------------


@st.composite
def random_order_state(draw: st.DrawFn):
    """Generate an OrderState with 0-5 random items."""
    items = draw(
        st.lists(order_line, min_size=0, max_size=5, unique_by=lambda x: x["item_id"])
    )
    state = OrderState()
    for item in items:
        state.add_item(
            item["item_id"], item["name"], item["quantity"], item["unit_price"]
        )
    return state


@settings(max_examples=100)
@given(state=random_order_state())
def test_cancel_clears_all_items(state: OrderState) -> None:
    """Cancelling any order (empty or non-empty) results in zero items and zero total.

    **Validates: Requirements 4.4**
    """
    state.cancel()

    assert len(state.items) == 0
    assert state.get_total() == 0


# ---------------------------------------------------------------------------
# Property 9: place_order produces a complete order record
# ---------------------------------------------------------------------------

user_ids = st.text(min_size=1, max_size=50)


@st.composite
def non_empty_order_state(draw: st.DrawFn):
    """Generate an OrderState with 1-5 random items (non-empty)."""
    items = draw(
        st.lists(order_line, min_size=1, max_size=5, unique_by=lambda x: x["item_id"])
    )
    state = OrderState()
    for item in items:
        state.add_item(
            item["item_id"], item["name"], item["quantity"], item["unit_price"]
        )
    return state


@settings(max_examples=100)
@given(state=non_empty_order_state(), user_id=user_ids)
def test_place_order_produces_complete_order_record(
    state: OrderState, user_id: str
) -> None:
    """place_order returns a record with UUID, items, total, sessionId, timestamp, and status.

    **Validates: Requirements 6.1, 6.3**
    """
    import uuid
    from datetime import datetime

    # Snapshot the expected items and total before placing
    expected_items = [
        {
            "itemId": item.item_id,
            "name": item.name,
            "quantity": item.quantity,
            "unitPrice": item.unit_price,
        }
        for item in state.items.values()
    ]
    expected_total = sum(i["quantity"] * i["unitPrice"] for i in expected_items)

    record = state.place_order(user_id)

    # 1. Non-empty order number that is a valid UUID
    assert record["orderId"]
    uuid.UUID(record["orderId"])  # raises ValueError if invalid

    # 2. All item details match the current order state
    assert record["items"] == expected_items

    # 3. Total matches sum of quantity * unitPrice
    assert record["total"] == expected_total

    # 4. sessionId records the voice session the order came from
    assert record["sessionId"] == user_id

    # 5. Valid ISO 8601 timestamp
    assert record["createdAt"]
    datetime.fromisoformat(record["createdAt"])  # raises ValueError if invalid

    # 6. Status is "confirmed"
    assert record["status"] == "confirmed"
