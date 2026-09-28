# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Property-based tests for menu_tools using moto to mock DynamoDB.

Property 10: get_categories returns all distinct categories
**Validates: Requirements 8.1**

Property 11: get_items_by_category returns only matching items
**Validates: Requirements 8.2**

Property 12: get_item_details returns complete item data
**Validates: Requirements 8.3**

Property 13: get_recommendations returns only featured items
**Validates: Requirements 8.7**
"""

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from agent import menu_tools


# ---------------------------------------------------------------------------
# Strategies for generating random menu data
# ---------------------------------------------------------------------------

# Category IDs: lowercase alpha strings to avoid DynamoDB key issues
category_ids = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",)),
    min_size=1,
    max_size=15,
)

# Human-readable names
names = st.text(min_size=1, max_size=40)

# Descriptions
descriptions = st.text(min_size=0, max_size=100)

# Prices in fils
prices = st.integers(min_value=1, max_value=100_000)

# Image URLs
image_urls = st.text(min_size=1, max_size=60)

# Sort orders
sort_orders = st.integers(min_value=0, max_value=1000)

# Featured flag
featured_flags = st.booleans()

# Item IDs: lowercase alpha strings
item_ids = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",)),
    min_size=1,
    max_size=15,
)


# A single menu item dict (before being written to DynamoDB)
menu_item_strategy = st.fixed_dictionaries(
    {
        "item_id": item_ids,
        "name": names,
        "description": descriptions,
        "price": prices,
        "imageUrl": image_urls,
        "featured": featured_flags,
        "sortOrder": sort_orders,
    }
)


@st.composite
def menu_table_data(draw: st.DrawFn):
    """Generate random menu data: a dict of category_id -> (category_name, [items]).

    Guarantees at least 1 category with at least 1 item.
    """
    num_categories = draw(st.integers(min_value=1, max_value=5))
    cat_ids = draw(
        st.lists(category_ids, min_size=num_categories, max_size=num_categories, unique=True)
    )

    data: dict[str, dict] = {}
    for cid in cat_ids:
        cat_name = draw(names)
        cat_sort = draw(sort_orders)
        items = draw(
            st.lists(menu_item_strategy, min_size=1, max_size=5, unique_by=lambda x: x["item_id"])
        )
        data[cid] = {
            "name": cat_name,
            "sortOrder": cat_sort,
            "items": items,
        }
    return data


def _create_table_and_seed(data: dict) -> "boto3.resource.Table":
    """Create a mocked DynamoDB table and seed it with the given menu data.

    Args:
        data: dict of category_id -> {"name", "sortOrder", "items": [...]}.

    Returns:
        The moto-backed DynamoDB Table resource.
    """
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    table = ddb.create_table(
        TableName="DriveThruMenuProp",
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

    for cat_id, cat_info in data.items():
        # Write category METADATA record
        table.put_item(
            Item={
                "PK": f"CATEGORY#{cat_id}",
                "SK": "METADATA",
                "name": cat_info["name"],
                "sortOrder": cat_info["sortOrder"],
            }
        )
        # Write item records
        for item in cat_info["items"]:
            table.put_item(
                Item={
                    "PK": f"CATEGORY#{cat_id}",
                    "SK": f"ITEM#{item['item_id']}",
                    "name": item["name"],
                    "description": item["description"],
                    "price": item["price"],
                    "imageUrl": item["imageUrl"],
                    "category": cat_info["name"],
                    "featured": item["featured"],
                    "sortOrder": item["sortOrder"],
                }
            )

    return table


# ---------------------------------------------------------------------------
# Property 10: get_categories returns all distinct categories
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(data=menu_table_data())
def test_get_categories_returns_all_distinct_categories(data: dict) -> None:
    """For any menu table with N distinct categories, get_categories returns exactly N,
    and every category present in the table appears in the result.

    **Validates: Requirements 8.1**
    """
    with mock_aws():
        table = _create_table_and_seed(data)
        menu_tools.set_table(table)

        result = menu_tools.get_categories()
        categories = result["categories"]

        # Exactly N categories
        assert len(categories) == len(data)

        # Every seeded category appears in the result
        returned_ids = {c["categoryId"] for c in categories}
        for cat_id in data:
            assert cat_id in returned_ids

        # Every returned category name matches what was seeded
        returned_names = {c["categoryId"]: c["name"] for c in categories}
        for cat_id, cat_info in data.items():
            assert returned_names[cat_id] == cat_info["name"]


# ---------------------------------------------------------------------------
# Property 11: get_items_by_category returns only matching items
# ---------------------------------------------------------------------------


@st.composite
def menu_data_with_target_category(draw: st.DrawFn):
    """Generate menu data and pick one category to query."""
    data = draw(menu_table_data())
    target_cat_id = draw(st.sampled_from(list(data.keys())))
    return data, target_cat_id


@settings(max_examples=100)
@given(data=menu_data_with_target_category())
def test_get_items_by_category_returns_only_matching_items(data) -> None:
    """For any existing category, get_items_by_category returns a non-empty list
    where every item has the requested category, and no items from other categories
    are included.

    **Validates: Requirements 8.2**
    """
    menu_data, target_cat_id = data

    with mock_aws():
        table = _create_table_and_seed(menu_data)
        menu_tools.set_table(table)

        result = menu_tools.get_items_by_category(category_id=target_cat_id)
        items = result["items"]

        expected_items = menu_data[target_cat_id]["items"]
        expected_cat_name = menu_data[target_cat_id]["name"]

        # Non-empty (we guarantee at least 1 item per category)
        assert len(items) > 0

        # Count matches expected
        assert len(items) == len(expected_items)

        # Every returned item has the correct category
        for item in items:
            assert item["category"] == expected_cat_name

        # Every returned item ID is from the expected set
        expected_item_ids = {i["item_id"] for i in expected_items}
        returned_item_ids = {i["itemId"] for i in items}
        assert returned_item_ids == expected_item_ids


# ---------------------------------------------------------------------------
# Property 12: get_item_details returns complete item data
# ---------------------------------------------------------------------------


@st.composite
def menu_data_with_target_item(draw: st.DrawFn):
    """Generate menu data and pick one specific item to query."""
    data = draw(menu_table_data())
    target_cat_id = draw(st.sampled_from(list(data.keys())))
    target_item = draw(st.sampled_from(data[target_cat_id]["items"]))
    return data, target_cat_id, target_item


@settings(max_examples=100)
@given(data=menu_data_with_target_item())
def test_get_item_details_returns_complete_item_data(data) -> None:
    """For any item ID that exists in the menu table, get_item_details returns
    an object containing the item's name, description, price, and imageUrl,
    all matching the stored values.

    **Validates: Requirements 8.3**
    """
    menu_data, target_cat_id, target_item = data

    with mock_aws():
        table = _create_table_and_seed(menu_data)
        menu_tools.set_table(table)

        result = menu_tools.get_item_details(
            item_id=target_item["item_id"],
            category_id=target_cat_id,
        )

        # No error
        assert "error" not in result

        # All fields match stored values
        assert result["name"] == target_item["name"]
        assert result["description"] == target_item["description"]
        assert result["price"] == target_item["price"]
        assert result["imageUrl"] == target_item["imageUrl"]
        assert result["itemId"] == target_item["item_id"]


# ---------------------------------------------------------------------------
# Property 13: get_recommendations returns only featured items
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(data=menu_table_data())
def test_get_recommendations_returns_only_featured_items(data: dict) -> None:
    """For any menu table state, get_recommendations returns a list where every
    item has featured = true, and no non-featured items are included.

    **Validates: Requirements 8.7**
    """
    with mock_aws():
        table = _create_table_and_seed(data)
        menu_tools.set_table(table)

        result = menu_tools.get_recommendations()
        items = result["items"]

        # Every returned item must be featured
        for item in items:
            assert item["featured"] is True

        # Build expected set of (categoryId, itemId) pairs for featured items
        expected_featured: set[tuple[str, str]] = set()
        for cat_id, cat_info in data.items():
            for menu_item in cat_info["items"]:
                if menu_item["featured"]:
                    expected_featured.add((cat_id, menu_item["item_id"]))

        # Build returned set of (categoryId, itemId) pairs
        returned_pairs = {(i["categoryId"], i["itemId"]) for i in items}

        # All featured items are returned, and no non-featured items
        assert returned_pairs == expected_featured
        assert len(items) == len(expected_featured)
