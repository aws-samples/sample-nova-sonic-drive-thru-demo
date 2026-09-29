# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for order_tools using moto to mock DynamoDB.

Tool results are deliberately minimal because Nova Sonic reads them. The customer's screen is
driven by the session's screen state, so most assertions check what the screen would show.
"""

import uuid

import boto3
import pytest
from moto import mock_aws

from agent import menu_tools, order_tools
from agent.tests.support import context, make_session, screen_order

CLASSIC_PRICE = 2900  # fils
COLA_PRICE = 900

MENU = {
    "categories": [
        {"categoryId": "burgers", "name": "Burgers", "sortOrder": 1},
        {"categoryId": "drinks", "name": "Drinks", "sortOrder": 2},
    ],
    "menuItems": {
        "burgers": [{"itemId": "classic", "categoryId": "burgers", "name": "Classic Burger",
                     "description": "A classic beef burger", "price": CLASSIC_PRICE}],
        "drinks": [{"itemId": "cola", "categoryId": "drinks", "name": "Cola",
                    "description": "Refreshing cola", "price": COLA_PRICE}],
    },
}


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

        order_tools.set_tables(menu_table, orders_table)
        yield menu_table, orders_table


@pytest.fixture
def session():
    return make_session(MENU, session_id="session-abc")


def add(session, item_id, category_id, quantity=1, **kwargs):
    return order_tools.add_to_order(item_id=item_id, category_id=category_id, quantity=quantity,
                                    tool_context=context(session), **kwargs)


class TestAddToOrder:
    def test_add_valid_item(self, dynamodb_tables, session):
        result = add(session, "classic", "burgers")
        assert result == {"status": "added", "item": "Classic Burger", "quantity": 1, "total": CLASSIC_PRICE}
        assert screen_order(session) == ([("classic", 1)], CLASSIC_PRICE)

    def test_add_increments_existing(self, dynamodb_tables, session):
        add(session, "classic", "burgers", 1)
        result = add(session, "classic", "burgers", 2)
        assert result["total"] == CLASSIC_PRICE * 3
        assert screen_order(session) == ([("classic", 3)], CLASSIC_PRICE * 3)

    @pytest.mark.parametrize("quantity", [0, -1])
    def test_rejects_non_positive_quantity(self, dynamodb_tables, session, quantity):
        assert "error" in add(session, "classic", "burgers", quantity)
        assert screen_order(session) == ([], 0)

    def test_add_invalid_item(self, dynamodb_tables, session):
        assert "error" in add(session, "nonexistent", "burgers")

    def test_sessions_have_separate_orders(self, dynamodb_tables):
        """Orders used to live in a module global, shared by every connection in the process."""
        first, second = make_session(MENU, "first"), make_session(MENU, "second")
        add(first, "classic", "burgers")
        add(second, "cola", "drinks", 2)
        assert screen_order(first) == ([("classic", 1)], CLASSIC_PRICE)
        assert screen_order(second) == ([("cola", 2)], COLA_PRICE * 2)


class TestRemoveFromOrder:
    def test_remove_updates_screen(self, dynamodb_tables, session):
        add(session, "classic", "burgers", 2)
        result = order_tools.remove_from_order(item_id="classic", quantity=1, tool_context=context(session))
        assert result == {"status": "removed", "item": "classic", "total": CLASSIC_PRICE, "itemCount": 1}
        assert screen_order(session) == ([("classic", 1)], CLASSIC_PRICE)

    def test_remove_last_unit_clears_screen(self, dynamodb_tables, session):
        add(session, "classic", "burgers")
        order_tools.remove_from_order(item_id="classic", quantity=1, tool_context=context(session))
        assert screen_order(session) == ([], 0)

    def test_remove_nonexistent_item(self, dynamodb_tables, session):
        assert "error" in order_tools.remove_from_order(item_id="classic", quantity=1, tool_context=context(session))


class TestGetOrderSummary:
    def test_empty_order(self, dynamodb_tables, session):
        assert order_tools.get_order_summary(tool_context=context(session)) == {"items": [], "total": 0}

    def test_with_items(self, dynamodb_tables, session):
        add(session, "classic", "burgers")
        add(session, "cola", "drinks", 2)
        assert order_tools.get_order_summary(tool_context=context(session)) == {
            "items": ["Classic Burger x1", "Cola x2"],
            "total": CLASSIC_PRICE + COLA_PRICE * 2,
        }


class TestPlaceOrder:
    def place(self, session):
        return order_tools.place_order(tool_context=context(session))

    def test_place_order_persists_under_a_uuid(self, dynamodb_tables, session):
        _, orders_table = dynamodb_tables
        add(session, "classic", "burgers")
        result = self.place(session)

        assert result["status"] == "confirmed"
        assert result["total"] == CLASSIC_PRICE
        assert result["orderNumber"].isdigit() and len(result["orderNumber"]) == 3
        [record] = orders_table.scan()["Items"]
        uuid.UUID(record["orderId"])  # the key is a UUID, not the spoken number
        assert record["orderNumber"] == result["orderNumber"]
        assert record["sessionId"] == "session-abc"

    def test_confirmation_screen_shows_the_placed_order(self, dynamodb_tables, session):
        add(session, "classic", "burgers")
        result = self.place(session)
        assert session.screen["orderConfirmed"] is True
        assert session.order_placed
        assert session.screen["orderNumber"] == result["orderNumber"]
        assert screen_order(session) == ([("classic", 1)], CLASSIC_PRICE)

    def test_repeated_order_numbers_never_overwrite_orders(self, dynamodb_tables, monkeypatch):
        _, orders_table = dynamodb_tables
        monkeypatch.setattr("random.randint", lambda a, b: 427)  # every order gets number 427
        for _ in range(2):
            session = make_session(MENU)
            add(session, "classic", "burgers")
            self.place(session)
        assert orders_table.scan()["Count"] == 2

    def test_place_empty_order_fails(self, dynamodb_tables, session):
        assert "error" in self.place(session)

    def test_placing_twice_saves_one_order(self, dynamodb_tables, session):
        _, orders_table = dynamodb_tables
        add(session, "classic", "burgers")
        self.place(session)
        assert "error" in self.place(session)
        assert orders_table.scan()["Count"] == 1

    def test_place_order_clears_state(self, dynamodb_tables, session):
        add(session, "classic", "burgers")
        self.place(session)
        assert order_tools.get_order_summary(tool_context=context(session)) == {"items": [], "total": 0}


class TestItemPopupLifecycle:
    """The screen is voice-driven: nobody can tap a popup closed, so the server closes it."""

    def _show(self, session, item_id):
        menu_tools.show_item(item_id=item_id, tool_context=context(session))
        assert session.screen["highlightedItem"] == item_id

    def test_ordering_closes_the_item_popup(self, dynamodb_tables, session):
        self._show(session, "classic")
        add(session, "classic", "burgers")
        assert session.screen["highlightedItem"] is None

    def test_removing_and_cancelling_close_the_item_popup(self, dynamodb_tables, session):
        add(session, "classic", "burgers", 2)
        self._show(session, "cola")
        order_tools.remove_from_order(item_id="classic", quantity=1, tool_context=context(session))
        assert session.screen["highlightedItem"] is None
        self._show(session, "cola")
        order_tools.cancel_order(tool_context=context(session))
        assert session.screen["highlightedItem"] is None

    def test_opening_the_builder_closes_the_item_popup(self, dynamodb_tables, session):
        self._show(session, "classic")
        order_tools.update_custom_burger(tool_context=context(session))
        assert session.screen["highlightedItem"] is None


class TestCancelOrder:
    def test_cancel_clears_order_and_screen(self, dynamodb_tables, session):
        add(session, "classic", "burgers", 2)
        assert order_tools.cancel_order(tool_context=context(session)) == {"status": "cancelled"}
        assert order_tools.get_order_summary(tool_context=context(session)) == {"items": [], "total": 0}
        assert screen_order(session) == ([], 0)

    def test_cancel_empty_order(self, dynamodb_tables, session):
        assert order_tools.cancel_order(tool_context=context(session)) == {"status": "cancelled"}
        assert screen_order(session) == ([], 0)


class TestCustomBurger:
    def update(self, session, **kwargs):
        return order_tools.update_custom_burger(tool_context=context(session), **kwargs)

    def confirm(self, session, **kwargs):
        return order_tools.confirm_custom_burger(tool_context=context(session), **kwargs)

    def test_builder_opens_empty_and_is_priced_by_the_server(self, dynamodb_tables, session):
        assert self.update(session) == {"patty": None, "toppings": [], "sauces": [], "price": 3300}
        assert session.screen["burgerBuilder"] == {
            "active": True, "patty": None, "toppings": [], "sauces": [], "price": 3300,
        }

    def test_choices_build_up_step_by_step(self, dynamodb_tables, session):
        self.update(session, patty="Beef Patty")
        self.update(session, add_toppings=["bacon", "swiss cheese"])
        self.update(session, add_sauces=["mayo"], add_toppings=["bacon"])  # bacon again: no double charge
        result = self.update(session, remove_toppings=["swiss cheese"], add_toppings=["lettuce"])
        assert result == {"patty": "beef patty", "toppings": ["bacon", "lettuce"], "sauces": ["mayo"],
                          "price": 3300 + 600}
        assert session.screen["burgerBuilder"]["price"] == 3300 + 600

    def test_confirm_adds_the_burger_at_the_builder_price(self, dynamodb_tables, session):
        self.update(session, patty="beef patty", add_toppings=["bacon", "cheddar cheese", "lettuce"],
                    add_sauces=["ketchup"])
        preview = session.screen["burgerBuilder"]["price"]
        assert preview == 3300 + 600 + 400

        result = self.confirm(session)
        assert result["price"] == preview
        assert result["total"] == preview
        assert session.screen["burgerBuilder"] is None  # the builder closes once the burger is added
        assert session.burger_draft is None
        [line] = session.screen["orderItems"]
        assert line["name"] == "Custom Burger"
        assert line["unitPrice"] == preview

    def test_confirm_needs_a_patty(self, dynamodb_tables, session):
        assert "error" in self.confirm(session)  # nothing started
        self.update(session, add_toppings=["bacon"])
        assert "error" in self.confirm(session)
        assert screen_order(session) == ([], 0)

    def test_unknown_choices_are_rejected_without_changing_the_burger(self, dynamodb_tables, session):
        self.update(session, patty="chicken patty")
        assert "error" in self.update(session, add_toppings=["gold leaf"])
        assert "error" in self.update(session, add_sauces=["bacon"])  # a topping is not a sauce
        assert "error" in self.update(session, patty="tofu patty")
        assert session.burger_draft == {"patty": "chicken patty", "toppings": [], "sauces": []}

    def test_showing_an_item_hides_the_builder_but_keeps_the_burger(self, dynamodb_tables, session):
        self.update(session, patty="beef patty", add_toppings=["bacon"])
        menu_tools.show_item(item_id="cola", tool_context=context(session))
        assert session.screen["burgerBuilder"] is None
        result = self.update(session, add_sauces=["bbq sauce"])  # carrying on reopens it
        assert result["toppings"] == ["bacon"]
        assert session.screen["burgerBuilder"]["active"] is True

    def test_cancel_throws_the_burger_away(self, dynamodb_tables, session):
        self.update(session, patty="beef patty")
        assert order_tools.cancel_custom_burger(tool_context=context(session)) == {"status": "cancelled"}
        assert session.burger_draft is None
        assert session.screen["burgerBuilder"] is None
        assert self.update(session)["patty"] is None  # a new burger starts from scratch


class TestToolSchemas:
    """What the model can see and set. The session is injected and never part of a schema."""

    ALL_TOOLS = [
        order_tools.add_to_order, order_tools.remove_from_order, order_tools.get_order_summary,
        order_tools.place_order, order_tools.cancel_order, order_tools.update_custom_burger,
        order_tools.confirm_custom_burger, order_tools.cancel_custom_burger,
        menu_tools.show_item, menu_tools.show_category, menu_tools.get_recommendations,
    ]

    @staticmethod
    def params(tool):
        return set(tool.tool_spec["inputSchema"]["json"]["properties"])

    def test_no_tool_exposes_its_context(self):
        for tool in self.ALL_TOOLS:
            assert "tool_context" not in self.params(tool), tool.tool_name

    def test_model_cannot_supply_who_placed_the_order(self):
        """The model used to fill in user_id and invented values like 'user123'."""
        assert self.params(order_tools.place_order) == set()

    def test_model_never_sets_a_price(self):
        for tool in self.ALL_TOOLS:
            assert not {"price", "total", "unit_price"} & self.params(tool), tool.tool_name
