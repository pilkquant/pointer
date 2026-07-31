"""Core utilities."""

from __future__ import annotations
from typing import Sequence
import hashlib
import json


def hash_data(data: str) -> str:
    """Hash a string using SHA-256."""
    return hashlib.sha256(data.encode()).hexdigest()


def serialize(obj: dict) -> str:
    """Serialize a dict to JSON."""
    return json.dumps(obj, sort_keys=True)


def process_items(items: Sequence[str]) -> list[str]:
    """Process a sequence of items."""
    return [item.upper() for item in items if item]
