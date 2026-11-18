# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""The protocol definition, and the generated schema the browser's types are built from."""

from agent import custom_burger, menu_tools, order_tools, protocol
from agent.tests.support import context, make_session

MENU = {
    "categories": [{"categoryId": "drinks", "name": "Drinks", "sortOrder": 1}],
    "menuItems": {"drinks": [
        {"itemId": "cola", "categoryId": "drinks", "name": "Cola", "description": "Fizzy", "price": 900},
    ]},
}


def test_the_committed_schema_matches_the_models():
    """Regenerate with `python -m agent.protocol`, then `cd frontend && npm run gen:protocol`."""
    assert protocol.SCHEMA_PATH.read_text(encoding="utf-8") == protocol.schema_text(), (
        "frontend/src/protocol/protocol.schema.json is out of date: run `python -m agent.protocol`, "
        "then `npm run gen:protocol` in frontend/"
    )


def test_the_screen_state_the_tools_produce_fits_the_protocol():
    """The tools write the screen; each change is validated against protocol.ScreenState."""
    session = make_session(MENU)
    ctx = context(session)
    menu_tools.show_item(item_id="cola", tool_context=ctx)
    with session.lock:  # what add_to_order does, without its DynamoDB lookup
        session.order.add_item("cola", "Cola", 2, 900, "no ice")
        summary = session.order.get_summary()
        session.update_screen(orderItems=summary["items"], orderTotal=summary["total"])
    order_tools.update_custom_burger(tool_context=ctx, patty="beef patty", add_toppings=["bacon"])
    snapshot = session.snapshot_event()
    assert snapshot.snapshot.orderItems[0].specialInstructions == "no ice"
    assert snapshot.snapshot.burgerBuilder.price == order_tools.custom_burger_price(["bacon"])
    protocol.ServerMessage.model_validate_json(snapshot.model_dump_json())


def test_the_menu_event_carries_the_whole_menu():
    event = make_session(MENU).menu_event().model_dump()
    assert event["type"] == "CUSTOM" and event["name"] == "menu"
    assert event["value"]["menuItems"]["drinks"][0]["price"] == 900


def test_the_screen_gets_the_same_burger_prices_the_tools_charge():
    options = make_session(MENU).menu_event().value.customBurger
    assert options.basePrice == custom_burger.price([])
    for topping in options.toppings:
        assert custom_burger.price([topping.name]) == options.basePrice + topping.price
    assert options.patties == list(order_tools.PATTIES)
    assert options.sauces == list(order_tools.SAUCES)
    assert {t.name for t in options.toppings} == set(order_tools.TOPPINGS)


def test_the_agent_is_told_every_option_and_price():
    text = custom_burger.prompt_text()
    for name in (*custom_burger.PATTIES, *custom_burger.TOPPINGS, *custom_burger.SAUCES):
        assert name in text
    assert "33 dirhams" in text and "+4 dirhams" in text and "+6 dirhams" in text
