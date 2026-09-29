# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for OrderState and OrderLineItem."""

import uuid
from datetime import datetime

import pytest

from agent.order_state import OrderLineItem, OrderState


class TestOrderLineItem:
    def test_creation(self):
        item = OrderLineItem(item_id="burger-1", name="Cheeseburger", quantity=2, unit_price=599)
        assert item.item_id == "burger-1"
        assert item.name == "Cheeseburger"
        assert item.quantity == 2
        assert item.unit_price == 599


class TestOrderStateAddItem:
    def test_add_new_item(self):
        state = OrderState()
        state.add_item("burger-1", "Cheeseburger", 1, 599)
        assert "burger-1" in state.items
        assert state.items["burger-1"].quantity == 1

    def test_add_increments_existing(self):
        state = OrderState()
        state.add_item("burger-1", "Cheeseburger", 1, 599)
        state.add_item("burger-1", "Cheeseburger", 2, 599)
        assert state.items["burger-1"].quantity == 3

    def test_add_quantity_less_than_one_raises(self):
        state = OrderState()
        with pytest.raises(ValueError, match="Quantity must be >= 1"):
            state.add_item("burger-1", "Cheeseburger", 0, 599)

    def test_add_multiple_different_items(self):
        state = OrderState()
        state.add_item("burger-1", "Cheeseburger", 1, 599)
        state.add_item("fries-1", "Fries", 1, 299)
        assert len(state.items) == 2


class TestOrderStateRemoveItem:
    def test_remove_reduces_quantity(self):
        state = OrderState()
        state.add_item("burger-1", "Cheeseburger", 3, 599)
        result = state.remove_item("burger-1", 1)
        assert result is True
        assert state.items["burger-1"].quantity == 2

    def test_remove_to_zero_deletes_item(self):
        state = OrderState()
        state.add_item("burger-1", "Cheeseburger", 1, 599)
        result = state.remove_item("burger-1", 1)
        assert result is True
        assert "burger-1" not in state.items

    def test_remove_nonexistent_returns_false(self):
        state = OrderState()
        result = state.remove_item("nope")
        assert result is False

    def test_remove_more_than_quantity_deletes(self):
        state = OrderState()
        state.add_item("burger-1", "Cheeseburger", 2, 599)
        result = state.remove_item("burger-1", 5)
        assert result is True
        assert "burger-1" not in state.items


class TestOrderStateCancel:
    def test_cancel_clears_items(self):
        state = OrderState()
        state.add_item("burger-1", "Cheeseburger", 1, 599)
        state.add_item("fries-1", "Fries", 2, 299)
        state.cancel()
        assert state.is_empty()

    def test_cancel_empty_order(self):
        state = OrderState()
        state.cancel()
        assert state.is_empty()


class TestOrderStateTotal:
    def test_total_single_item(self):
        state = OrderState()
        state.add_item("burger-1", "Cheeseburger", 2, 599)
        assert state.get_total() == 1198

    def test_total_multiple_items(self):
        state = OrderState()
        state.add_item("burger-1", "Cheeseburger", 1, 599)
        state.add_item("fries-1", "Fries", 2, 299)
        assert state.get_total() == 599 + 598

    def test_total_empty(self):
        state = OrderState()
        assert state.get_total() == 0


class TestOrderStateSummary:
    def test_summary_structure(self):
        state = OrderState()
        state.add_item("burger-1", "Cheeseburger", 1, 599)
        summary = state.get_summary()
        assert "items" in summary
        assert "total" in summary
        assert len(summary["items"]) == 1
        assert summary["items"][0]["itemId"] == "burger-1"
        assert summary["total"] == 599


class TestOrderStatePlaceOrder:
    def test_place_order_structure(self):
        state = OrderState()
        state.add_item("burger-1", "Cheeseburger", 1, 599)
        record = state.place_order("session-123")
        assert record["sessionId"] == "session-123"
        assert record["status"] == "confirmed"
        assert record["total"] == 599
        assert len(record["items"]) == 1
        # orderId is a valid UUID
        uuid.UUID(record["orderId"])
        # createdAt is valid ISO 8601
        datetime.fromisoformat(record["createdAt"])


class TestOrderStateIsEmpty:
    def test_empty_initially(self):
        state = OrderState()
        assert state.is_empty()

    def test_not_empty_after_add(self):
        state = OrderState()
        state.add_item("burger-1", "Cheeseburger", 1, 599)
        assert not state.is_empty()
