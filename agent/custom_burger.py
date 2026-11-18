# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""The build-your-own burger's options and prices: the one place they are defined.

The order tools price burgers with them, the agent's instructions list them, and the server
sends them to the screen with the menu, so the three can't disagree.
Prices are in fils (100 fils = 1 AED).
"""

try:
    from agent import protocol
except ModuleNotFoundError:
    import protocol

BASE_PRICE = 3300  # AED 33.00 for patty + bun
PATTIES = ("beef patty", "chicken patty")
_TOPPING_PRICES = {
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
}
TOPPINGS = tuple(_TOPPING_PRICES)
SAUCES = ("ketchup", "mustard", "mayo", "bbq sauce", "chipotle mayo", "special sauce")  # all free

OPTIONS = protocol.CustomBurgerOptions(
    basePrice=BASE_PRICE,
    patties=list(PATTIES),
    toppings=[protocol.BurgerTopping(name=name, price=price) for name, price in _TOPPING_PRICES.items()],
    sauces=list(SAUCES),
)


def price(toppings) -> int:
    """Price in fils of a custom burger with the given toppings.

    The single price calculation for custom burgers: used for the builder on screen and for
    the item added to the order. Unknown toppings add nothing; the tools reject them first.
    """
    return BASE_PRICE + sum(_TOPPING_PRICES.get(str(t).lower().strip(), 0) for t in (toppings or []))


def _dirhams(fils: int) -> str:
    return f"{fils // 100}" if fils % 100 == 0 else f"{fils / 100:.2f}"


def prompt_text() -> str:
    """The options and prices, as the agent's instructions list them."""
    by_price: dict[int, list[str]] = {}
    for name, fils in _TOPPING_PRICES.items():
        by_price.setdefault(fils, []).append(name)
    toppings = [f"+{_dirhams(fils)} dirhams: {', '.join(names)}" for fils, names in sorted(by_price.items()) if fils]
    if 0 in by_price:
        toppings.append(f"Free: {', '.join(by_price[0])}")
    return "\n".join([
        f"Base price {_dirhams(BASE_PRICE)} dirhams, with a patty: {' or '.join(PATTIES)}.",
        f"Toppings. {'. '.join(toppings)}.",
        f"Sauces (all free): {', '.join(SAUCES)}.",
    ])
