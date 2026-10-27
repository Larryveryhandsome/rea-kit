"""Registry for public listing sources.

The registry is deliberately metadata-only. A domain is not treated as a
working feed until its robots policy, terms, page shape, and sample response
have been verified. Each source can later select its own parser adapter.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = ("source_id", "display_name", "kind", "homepage", "status", "parser")
ALLOWED_STATUS = {"candidate-unverified", "verified", "paused", "blocked"}


def load_registry(path: str | Path) -> list[dict[str, Any]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("source registry must be a JSON list")
    rows: list[dict[str, Any]] = []
    for row in raw:
        missing = [field for field in REQUIRED_FIELDS if not str(row.get(field, "")).strip()]
        if missing:
            raise ValueError("source missing required fields: " + ", ".join(missing))
        if row["status"] not in ALLOWED_STATUS:
            raise ValueError(f"unknown source status: {row['status']}")
        if not str(row["homepage"]).startswith("https://"):
            raise ValueError("public source homepage must use HTTPS")
        rows.append(dict(row))
    return rows


def runnable_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """No sources may be scheduled in this unapproved release."""
    # Source metadata alone is never runtime authorization.
    return []
