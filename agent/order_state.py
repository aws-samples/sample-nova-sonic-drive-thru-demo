# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""In-memory order state management for drive-thru voice ordering agent."""

import html
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

# --- Input validation constants ---
MAX_SPECIAL_INSTRUCTIONS_LENGTH = 500
MAX_QUANTITY_PER_ITEM = 99
# Allow letters, numbers, spaces, and common punctuation for food instructions
SPECIAL_INSTRUCTIONS_PATTERN = re.compile(r"^[a-zA-Z0-9\s.,!?'\-/()]+$")


def sanitize_special_instructions(instructions: str) -> str:
    """Sanitize special instructions to prevent injection attacks.

    - Truncates to MAX_SPECIAL_INSTRUCTIONS_LENGTH
    - HTML-encodes to prevent stored XSS
    - Strips characters that don't match the allowed pattern
    """
    if not instructions:
        return ""
    # Truncate
    instructions = instructions[:MAX_SPECIAL_INSTRUCTIONS_LENGTH]
    # Strip disallowed characters
    if not SPECIAL_INSTRUCTIONS_PATTERN.match(instructions):
        instructions = re.sub(r"[^a-zA-Z0-9\s.,!?'\-/()]", "", instructions)
    # HTML-encode as defense-in-depth against XSS if rendered in a web context
    instructions = html.escape(instructions, quote=True)
    return instructions.strip()


@dataclass
class OrderLineItem:
    """A single line item in an order."""

    item_id: str
    name: str
    quantity: int
    unit_price: int  # fils (1/100 AED)
    special_instructions: str = ""


@dataclass
class OrderState:
    """Manages in-memory order state during a voice session.

    All prices are in fils (integers, 100 fils = 1 AED) to avoid floating-point issues.
    """

    items: dict[str, OrderLineItem] = field(default_factory=dict)

    def add_item(self, item_id: str, name: str, quantity: int, unit_price: int, special_instructions: str = "") -> None:
        """Add an item or increment its quantity if already present."""
        if quantity < 1:
            raise ValueError("Quantity must be >= 1")
        if quantity > MAX_QUANTITY_PER_ITEM:
            raise ValueError(f"Quantity must be <= {MAX_QUANTITY_PER_ITEM}")
        # Sanitize special instructions to prevent injection
        special_instructions = sanitize_special_instructions(special_instructions)
        if item_id in self.items:
            new_qty = self.items[item_id].quantity + quantity
            if new_qty > MAX_QUANTITY_PER_ITEM:
                raise ValueError(f"Total quantity for item cannot exceed {MAX_QUANTITY_PER_ITEM}")
            self.items[item_id].quantity = new_qty
            if special_instructions:
                self.items[item_id].special_instructions = special_instructions
        else:
            self.items[item_id] = OrderLineItem(
                item_id=item_id,
                name=name,
                quantity=quantity,
                unit_price=unit_price,
                special_instructions=special_instructions,
            )

    def remove_item(self, item_id: str, quantity: int = 1) -> bool:
        """Reduce an item's quantity or remove it entirely.

        Args:
            item_id: Unique menu item identifier.
            quantity: Number to remove (defaults to 1).

        Returns:
            True if the item was found, False otherwise.
        """
        if item_id not in self.items:
            return False
        line = self.items[item_id]
        line.quantity -= quantity
        if line.quantity <= 0:
            del self.items[item_id]
        return True

    def cancel(self) -> None:
        """Clear all items from the order."""
        self.items.clear()

    def get_total(self) -> int:
        """Return the total price in fils."""
        return sum(item.quantity * item.unit_price for item in self.items.values())

    def is_empty(self) -> bool:
        """Return True if the order has no items."""
        return len(self.items) == 0

    def get_summary(self) -> dict:
        """Return a summary dict with items list and total."""
        return {
            "items": [
                {
                    "itemId": item.item_id,
                    "name": item.name,
                    "quantity": item.quantity,
                    "unitPrice": item.unit_price,
                    **({"specialInstructions": item.special_instructions} if item.special_instructions else {}),
                }
                for item in self.items.values()
            ],
            "total": self.get_total(),
        }

    def place_order(self, user_id: str) -> dict:
        """Generate a complete order record for persistence.

        Args:
            user_id: The authenticated user's identifier.

        Returns:
            Dict with orderId (UUID, the database key), orderNumber (short number the
            agent says aloud and the screen shows), userId, items, total, status, and createdAt.
        """
        import random
        return {
            # The key must be unique: records are written with put_item, which overwrites.
            "orderId": str(uuid.uuid4()),
            # Short and easy to say. It repeats across orders by design, so it is never a key.
            "orderNumber": f"{random.randint(100, 999)}",
            "userId": user_id,
            "items": [
                {
                    "itemId": item.item_id,
                    "name": item.name,
                    "quantity": item.quantity,
                    "unitPrice": item.unit_price,
                }
                for item in self.items.values()
            ],
            "total": self.get_total(),
            "status": "confirmed",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
