# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for order_tools using moto to mock DynamoDB.

Tool results are deliberately minimal because Nova Sonic reads them. The customer's screen is
driven by the UI state, so most assertions check what the screen would show.
"""

import uuid

import boto3
import pytest
from moto import mock_aws

from agent import order_tools
from agent.order_state import OrderState
from agent.ui_state_manager import get_ui_state, reset_ui_state

CLASSIC_PRICE = 2900  # fils
COLA_PRICE = 900


@pytest.fixture
def dynamodb_tables():
    """Create mocked DynamoDB menu and orders tables with sample data."""
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")

        menu_table = ddb.create_table(
            TableName="DriveThruMenu",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        orders_table = ddb.create_table(
            TableName="DriveThruOrders",
            KeySchema=[
                {"AttributeName": "orderId", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "orderId", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Seed menu items
        menu_table.put_item(Item={
            "PK": "CATEGORY#burgers", "SK": "ITEM#classic",
            "name": "Classic Burger", "description": "A classic beef burger",
            "price": CLASSIC_PRICE, "imageUrl": "images/classic.jpg",
            "category": "Burgers", "featured": True, "sortOrder": 1,
        })
        menu_table.put_item(Item={
            "PK": "CATEGORY#drinks", "SK": "ITEM#cola",
            "name": "Cola", "description": "Refreshing cola",
            "price": COLA_PRICE, "imageUrl": "images/cola.jpg",
            "category": "Drinks", "featured": True, "sortOrder": 1,
        })

        # Inject mocked tables, a fresh order and a fresh screen
        order_tools.set_tables(menu_table, orders_table)
        order_tools.set_order_state(OrderState())
        reset_ui_state()
        yield menu_table, orders_table


def screen_order():
    """The order as the customer's screen shows it: ([(itemId, quantity), ...], total)."""
    ui = get_ui_state()
    return [(i["itemId"], i["quantity"]) for i in ui["orderItems"]], ui["orderTotal"]


class TestAddToOrder:
    def test_add_valid_item(self, dynamodb_tables):
        result = order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=1)
        assert result == {"status": "added", "item": "Classic Burger", "quantity": 1, "total": CLASSIC_PRICE}
        assert screen_order() == ([("classic", 1)], CLASSIC_PRICE)

    def test_add_increments_existing(self, dynamodb_tables):
        order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=1)
        result = order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=2)
        assert result["total"] == CLASSIC_PRICE * 3
        assert screen_order() == ([("classic", 3)], CLASSIC_PRICE * 3)

    @pytest.mark.parametrize("quantity", [0, -1])
    def test_rejects_non_positive_quantity(self, dynamodb_tables, quantity):
        result = order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=quantity)
        assert "error" in result
        assert screen_order() == ([], 0)

    def test_add_invalid_item(self, dynamodb_tables):
        assert "error" in order_tools.add_to_order(item_id="nonexistent", category_id="burgers", quantity=1)


class TestRemoveFromOrder:
    def test_remove_updates_screen(self, dynamodb_tables):
        order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=2)
        result = order_tools.remove_from_order(item_id="classic", quantity=1)
        assert result == {"status": "removed", "item": "classic", "total": CLASSIC_PRICE, "itemCount": 1}
        assert screen_order() == ([("classic", 1)], CLASSIC_PRICE)

    def test_remove_last_unit_clears_screen(self, dynamodb_tables):
        order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=1)
        order_tools.remove_from_order(item_id="classic", quantity=1)
        assert screen_order() == ([], 0)

    def test_remove_nonexistent_item(self, dynamodb_tables):
        assert "error" in order_tools.remove_from_order(item_id="classic", quantity=1)


class TestGetOrderSummary:
    def test_empty_order(self, dynamodb_tables):
        assert order_tools.get_order_summary() == {"items": [], "total": 0}

    def test_with_items(self, dynamodb_tables):
        order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=1)
        order_tools.add_to_order(item_id="cola", category_id="drinks", quantity=2)
        assert order_tools.get_order_summary() == {
            "items": ["Classic Burger x1", "Cola x2"],
            "total": CLASSIC_PRICE + COLA_PRICE * 2,
        }


class TestPlaceOrder:
    def test_place_order_persists_under_a_uuid(self, dynamodb_tables):
        _, orders_table = dynamodb_tables
        order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=1)
        result = order_tools.place_order(user_id="user-123")

        assert result["status"] == "confirmed"
        assert result["total"] == CLASSIC_PRICE
        assert result["orderNumber"].isdigit() and len(result["orderNumber"]) == 3
        [record] = orders_table.scan()["Items"]
        uuid.UUID(record["orderId"])  # the key is a UUID, not the spoken number
        assert record["orderNumber"] == result["orderNumber"]
        assert record["userId"] == "user-123"

    def test_confirmation_screen_shows_the_placed_order(self, dynamodb_tables):
        order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=1)
        result = order_tools.place_order(user_id="user-123")
        ui = get_ui_state()
        assert ui["orderConfirmed"] is True
        assert ui["orderNumber"] == result["orderNumber"]
        assert screen_order() == ([("classic", 1)], CLASSIC_PRICE)

    def test_repeated_order_numbers_never_overwrite_orders(self, dynamodb_tables, monkeypatch):
        _, orders_table = dynamodb_tables
        monkeypatch.setattr("random.randint", lambda a, b: 427)  # every order gets number 427
        for _ in range(2):
            order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=1)
            order_tools.place_order(user_id="user-123")
        assert orders_table.scan()["Count"] == 2

    def test_place_empty_order_fails(self, dynamodb_tables):
        assert "error" in order_tools.place_order(user_id="user-123")

    def test_place_order_clears_state(self, dynamodb_tables):
        order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=1)
        order_tools.place_order(user_id="user-123")
        assert order_tools.get_order_summary() == {"items": [], "total": 0}


class TestCancelOrder:
    def test_cancel_clears_order_and_screen(self, dynamodb_tables):
        order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=2)
        assert order_tools.cancel_order() == {"status": "cancelled"}
        assert order_tools.get_order_summary() == {"items": [], "total": 0}
        assert screen_order() == ([], 0)

    def test_cancel_empty_order(self, dynamodb_tables):
        assert order_tools.cancel_order() == {"status": "cancelled"}
        assert screen_order() == ([], 0)


class TestCustomBurger:
    def test_order_price_matches_builder_preview(self, dynamodb_tables):
        toppings = ["bacon", "cheddar cheese", "lettuce"]
        expected = order_tools.custom_burger_price(toppings)
        assert expected == 3300 + 600 + 400

        result = order_tools.build_custom_burger(patty="beef patty", toppings=toppings, sauces=["ketchup"])
        assert result["total"] == expected
        ui = get_ui_state()
        assert ui["burgerBuilder"] is None  # the builder closes once the burger is added
        assert ui["orderTotal"] == expected

    def test_unknown_topping_is_rejected(self, dynamodb_tables):
        result = order_tools.build_custom_burger(patty="beef patty", toppings=["gold leaf"])
        assert "error" in result
        assert screen_order() == ([], 0)


class TestUpdateUi:
    """The model may only steer highlighting and the builder; it never writes order or price data."""

    def test_builder_price_is_computed_server_side(self, dynamodb_tables):
        from agent import main

        main.update_ui(burger_builder={
            "active": True, "patty": "beef patty", "toppings": ["bacon", "swiss cheese"],
            "sauces": [], "price": 1,  # a wrong model-supplied price is ignored
        })
        assert get_ui_state()["burgerBuilder"]["price"] == 3300 + 600 + 400

    def test_model_cannot_write_order_or_menu_fields(self):
        from agent import main

        params = set(main.update_ui.tool_spec["inputSchema"]["json"]["properties"])
        assert params == {"highlighted_category", "highlighted_item", "burger_builder"}
