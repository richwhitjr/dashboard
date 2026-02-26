"""Shared utility for content-hash-based LLM ranking cache validation."""

import hashlib
import json


def compute_items_hash(items: list[dict]) -> str:
    """Deterministic hash of the items list sent to Gemini.

    Returns a short hex digest that can be stored alongside cached results
    to detect when input data has changed and re-ranking is needed.
    """
    raw = json.dumps(items, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
