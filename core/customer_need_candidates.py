"""Batch candidate extraction from tenant-provided chat exports.

The function is intentionally conservative: it creates review candidates from
text supplied by the tenant and never writes back to a chat account. A model
can replace the extraction heuristic later while keeping this review contract.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping


_BUDGET = re.compile(r"(?P<number>\d+(?:\.\d+)?)\s*(?:萬|万)")
_ROOMS = re.compile(r"(?P<number>\d+(?:\.\d+)?)\s*房")


def extract_candidate(record: Mapping[str, Any], *, known_areas: Iterable[str]) -> dict[str, Any]:
    external_ref = str(record.get("external_ref", "")).strip()
    text = str(record.get("text", "")).strip()
    if not external_ref or not text:
        raise ValueError("chat record requires external_ref and text")
    area_matches = [area for area in known_areas if area and area in text]
    budget = _BUDGET.search(text)
    rooms = _ROOMS.search(text)
    transaction = "rent" if any(word in text for word in ("租", "出租", "租屋")) else "buy" if any(word in text for word in ("買", "購屋", "買房")) else ""
    missing = []
    if not transaction:
        missing.append("transaction")
    if not area_matches:
        missing.append("preferred_areas")
    if not budget:
        missing.append("budget_max")
    return {
        "external_ref": external_ref,
        "transaction": transaction,
        "preferred_areas": area_matches,
        "budget_max": float(budget.group("number")) if budget else None,
        "rooms_min": float(rooms.group("number")) if rooms else None,
        "missing": missing,
        "review_required": True,
        "confidence": "review" if missing else "candidate",
    }


def extract_candidates(records: Iterable[Mapping[str, Any]], *, known_areas: Iterable[str]) -> list[dict[str, Any]]:
    return [extract_candidate(record, known_areas=known_areas) for record in records]
