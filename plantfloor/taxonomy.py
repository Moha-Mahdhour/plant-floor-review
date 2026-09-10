"""Event types and how each one counts.

This is the single definition shared by the annotation schema, the merger,
the report, and the dashboard. A test checks that prompts/schema.json and
app/index.html agree with it, so the categories cannot drift apart again.

Categories follow lean practice:
  value      the station is doing productive work
  necessary  non-value-adding but unavoidable (changeovers, moving carts)
  neutral    planned absence (breaks)
  loss       time the plant loses and could win back
"""
from __future__ import annotations

EVENT_TYPES: dict[str, str] = {
    "work": "value",
    "changeover": "necessary",
    "transport": "necessary",
    "break": "neutral",
    "idle": "loss",
    "unmanned": "loss",
    "queue_buildup": "loss",
    "blockage": "loss",
    "starvation": "loss",
    "machine_stop": "loss",
    "rework": "loss",
    "search": "loss",
    "customer_wait": "loss",
    "safety": "loss",
    "unknown": "loss",
}

LOSS_TYPES = frozenset(t for t, c in EVENT_TYPES.items() if c == "loss")
COVERAGE_STATES = ("clear", "partial", "obscured", "unusable")
FALLBACK_TYPE = "unknown"


def category(event_type: str) -> str:
    return EVENT_TYPES.get(event_type, EVENT_TYPES[FALLBACK_TYPE])


def is_loss(event_type: str) -> bool:
    return category(event_type) == "loss"
