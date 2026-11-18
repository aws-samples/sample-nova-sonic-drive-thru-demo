# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""The WebSocket protocol between the agent and the browser: the one definition of it.

Audio travels as binary frames, everything else as JSON text frames:
- Binary frames, both ways: raw audio in AUDIO_FORMAT (16 kHz, mono, 16-bit little-endian
  PCM), with no header. The browser sends only microphone audio; the server sends the
  agent's voice.
- Text frames, server to browser only: one ServerMessage each. The messages follow the
  shape of AG-UI events (https://docs.ag-ui.com):
  - CUSTOM "menu": the whole menu, once per connection.
  - STATE_SNAPSHOT: the whole screen state, with an epoch (one per session) and a version
    (one per change). The browser ignores a snapshot older than the one it is showing.
  - bidi_interruption: stop playing the agent's voice (the customer spoke over it, or the
    model stream restarted).
  - CUSTOM "session_ended": why the server is ending the session, just before it closes.

Field names are camelCase because they are the names on the wire.

The browser's TypeScript types are generated from these models:
    python -m agent.protocol            # writes frontend/src/protocol/protocol.schema.json
    cd frontend && npm run gen:protocol # writes frontend/src/protocol/messages.ts
CI fails if either generated file is out of date.
"""

import json
import sys
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel
from pydantic.json_schema import GenerateJsonSchema, models_json_schema

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "frontend" / "src" / "protocol" / "protocol.schema.json"


class _Model(BaseModel):
    # Unknown fields are a bug on our side, not data to pass through. In the schema, fields
    # with defaults are still required: the server always sends them.
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


Fils = Annotated[int, Field(description="An amount in fils (100 fils = 1 AED).")]


# --- Audio (binary frames) ---

class AudioFormat(_Model):
    """The format of every binary frame, in both directions. Nova Sonic is configured for it."""

    sampleRate: Literal[16000] = 16000
    channels: Literal[1] = 1
    encoding: Literal["pcm_s16le"] = "pcm_s16le"


AUDIO_FORMAT = AudioFormat()
AUDIO_BYTES_PER_SAMPLE = 2


# --- Menu ---

class Category(_Model):
    categoryId: str
    name: str
    sortOrder: int = 0


class MenuItem(_Model):
    itemId: str
    categoryId: str
    name: str
    description: str = ""
    price: Fils
    imageUrl: str = ""
    category: str = ""
    featured: bool = False
    sortOrder: int = 0


class BurgerTopping(_Model):
    name: str
    price: Fils  # added to the base price; 0 for free toppings


class CustomBurgerOptions(_Model):
    """What a build-your-own burger can have, and what it costs (see custom_burger.py)."""

    basePrice: Fils
    patties: list[str]
    toppings: list[BurgerTopping]
    sauces: list[str]  # all free


class Menu(_Model):
    categories: list[Category] = []
    menuItems: dict[str, list[MenuItem]] = {}  # categoryId -> items
    customBurger: CustomBurgerOptions


# --- Screen state ---

class OrderItem(_Model):
    itemId: str
    name: str
    quantity: int
    unitPrice: Fils
    specialInstructions: str = ""


class BurgerBuilder(_Model):
    """The build-your-own burger in progress, priced by the server."""

    active: bool
    patty: str | None
    toppings: list[str]
    sauces: list[str]
    price: Fils  # the running total


class ScreenState(_Model):
    """Everything the screen shows apart from the menu. Only the agent's tools change it."""

    highlightedCategory: str | None = None
    highlightedItem: str | None = None
    orderItems: list[OrderItem] = []
    orderTotal: Fils = 0
    orderConfirmed: bool = False
    orderNumber: str | None = None
    burgerBuilder: BurgerBuilder | None = None


# --- Server messages (text frames) ---

class MenuEvent(_Model):
    type: Literal["CUSTOM"] = "CUSTOM"
    name: Literal["menu"] = "menu"
    value: Menu


class StateSnapshotEvent(_Model):
    type: Literal["STATE_SNAPSHOT"] = "STATE_SNAPSHOT"
    epoch: str
    version: int
    snapshot: ScreenState


SessionEndReason = Literal["order-complete", "idle-timeout", "conversation-ended", "agent-error"]


class SessionEnded(_Model):
    reason: SessionEndReason


class SessionEndedEvent(_Model):
    type: Literal["CUSTOM"] = "CUSTOM"
    name: Literal["session_ended"] = "session_ended"
    value: SessionEnded


class InterruptionEvent(_Model):
    type: Literal["bidi_interruption"] = "bidi_interruption"
    reason: str  # e.g. "user_speech" (from Nova Sonic) or "model_restart"


ServerEvent = MenuEvent | StateSnapshotEvent | SessionEndedEvent | InterruptionEvent


class ServerMessage(RootModel[ServerEvent]):
    """One JSON text frame from the server."""


# --- JSON Schema ---

class _SchemaGenerator(GenerateJsonSchema):
    def field_title_should_be_set(self, schema) -> bool:
        # Models keep their titles (they name the TypeScript types); fields don't need one
        return False


def json_schema() -> dict:
    """The protocol as JSON Schema: ServerMessage at the root, AudioFormat among the definitions."""
    _, schema = models_json_schema(
        [(ServerMessage, "serialization"), (AudioFormat, "serialization")],
        schema_generator=_SchemaGenerator,
    )
    definitions = schema["$defs"]
    root = definitions.pop("ServerMessage")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$comment": "Generated from agent/protocol.py by `python -m agent.protocol`. Do not edit.",
        **root,
        "$defs": definitions,
    }


def schema_text() -> str:
    return json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(schema_text(), encoding="utf-8")
    print(f"wrote {SCHEMA_PATH}", file=sys.stderr)
