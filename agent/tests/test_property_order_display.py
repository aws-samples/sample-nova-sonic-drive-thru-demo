# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Property-based tests: the customer's screen always shows the real order.

The order tools are the only writers of the order on screen. Whatever sequence of adds,
removes and cancels the model makes, the screen must match the order that would be placed,
and placing an order must never overwrite an earlier one.

**Validates: Requirements 3.2, 3.3, 3.5, 4.2, 6.1, 11.3**
"""

import uuid

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from agent import order_tools
from agent.tests.support import context, make_session

CATEGORY = "cat"

menus = st.lists(
    st.fixed_dictionaries({
        "item_id": st.text(alphabet=st.characters(whitelist_categories=("Ll",)), min_size=1, max_size=15),
        "name": st.text(min_size=1, max_size=40),
        "price": st.integers(min_value=1, max_value=100_000),
    }),
    min_size=1,
    max_size=4,
    unique_by=lambda item: item["item_id"],
)

# (operation, index into the menu, quantity)
operations = st.lists(
    st.one_of(
        st.tuples(st.just("add"), st.integers(0, 3), st.integers(1, 5)),
        st.tuples(st.just("remove"), st.integers(0, 3), st.integers(1, 5)),
        st.tuples(st.just("cancel"), st.just(0), st.just(0)),
    ),
    min_size=1,
    max_size=8,
)


@pytest.fixture(scope="module")
def tables():
    """One mocked DynamoDB for the whole module: creating tables per example is what made these slow."""
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        menu = ddb.create_table(
            TableName="PropMenu",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"},
                                  {"AttributeName": "SK", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        orders = ddb.create_table(
            TableName="PropOrders",
            KeySchema=[{"AttributeName": "orderId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "orderId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        order_tools.set_tables(menu, orders)
        yield menu, orders


def _start_example(menu_table, menu, session_id="prop-session"):
    """Seed this example's menu and return a new session: an empty order and screen."""
    for item in menu:
        menu_table.put_item(Item={
            "PK": f"CATEGORY#{CATEGORY}", "SK": f"ITEM#{item['item_id']}",
            "name": item["name"], "price": item["price"],
        })
    return make_session(session_id=session_id)


def _assert_screen_matches(session, expected_quantities, prices):
    ui = session.screen
    summary = session.order.get_summary()
    assert ui["orderItems"] == summary["items"]
    assert {i["itemId"]: i["quantity"] for i in ui["orderItems"]} == expected_quantities
    assert ui["orderTotal"] == sum(qty * prices[item_id] for item_id, qty in expected_quantities.items())


@settings(max_examples=100, deadline=None)
@given(menu=menus, ops=operations)
def test_screen_always_shows_the_real_order(tables, menu, ops) -> None:
    """After every add, remove or cancel, the screen shows exactly the order state."""
    menu_table, _ = tables
    session = _start_example(menu_table, menu)
    ctx = context(session)
    prices = {item["item_id"]: item["price"] for item in menu}
    expected: dict[str, int] = {}  # independent model of the order: itemId -> quantity

    for op, index, qty in ops:
        item_id = menu[index % len(menu)]["item_id"]
        if op == "add":
            order_tools.add_to_order(item_id=item_id, category_id=CATEGORY, quantity=qty, tool_context=ctx)
            expected[item_id] = expected.get(item_id, 0) + qty
        elif op == "remove":
            result = order_tools.remove_from_order(item_id=item_id, quantity=qty, tool_context=ctx)
            if item_id in expected:
                expected[item_id] -= qty
                if expected[item_id] <= 0:
                    del expected[item_id]
            else:
                assert "error" in result
        else:
            order_tools.cancel_order(tool_context=ctx)
            expected.clear()
        _assert_screen_matches(session, expected, prices)


@settings(max_examples=100, deadline=None)
@given(menu=menus, quantity=st.integers(min_value=1, max_value=5), session_id=st.text(min_size=1, max_size=50))
def test_placing_an_order_never_overwrites_another(tables, menu, quantity, session_id) -> None:
    """Every placed order adds exactly one record, and the confirmation shows what was placed.

    Across 100 examples the 3-digit spoken order numbers repeat many times, so this
    fails if the spoken number is ever used as the record key again.
    """
    menu_table, orders_table = tables
    session = _start_example(menu_table, menu, session_id)
    ctx = context(session)
    target = menu[0]
    order_tools.add_to_order(item_id=target["item_id"], category_id=CATEGORY, quantity=quantity, tool_context=ctx)
    before = orders_table.scan(Select="COUNT")["Count"]

    result = order_tools.place_order(tool_context=ctx)

    assert orders_table.scan(Select="COUNT")["Count"] == before + 1
    assert result["orderNumber"].isdigit() and len(result["orderNumber"]) == 3
    assert result["total"] == quantity * target["price"]
    ui = session.screen
    assert ui["orderConfirmed"] is True
    assert ui["orderNumber"] == result["orderNumber"]
    assert [(i["itemId"], i["quantity"]) for i in ui["orderItems"]] == [(target["item_id"], quantity)]
    assert ui["orderTotal"] == result["total"]
    for record in orders_table.scan()["Items"]:
        uuid.UUID(record["orderId"])
