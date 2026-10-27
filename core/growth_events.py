"""Privacy-minimal product growth event contract.

This is an event shape only. Persistence, tenant authentication, and analytics
transport belong to the web/MCP layer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


EVENTS = {
    "landing_view",
    "plugin_open",
    "sample_imported",
    "first_result",
    "share_clicked",
    "monitor_started",
    "paid_conversion",
}


def make_event(event: str, *, session_id: str, surface: str, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build a safe event; reject unknown events and obviously sensitive metadata."""
    if event not in EVENTS:
        raise ValueError(f"unknown event: {event}")
    if not session_id.strip() or not surface.strip():
        raise ValueError("session_id and surface are required")
    safe_metadata = dict(metadata or {})
    forbidden = {"phone", "address", "name", "conversation", "transcript", "deed", "token"}
    leaked = forbidden.intersection(safe_metadata)
    if leaked:
        raise ValueError("sensitive metadata is not allowed: " + ", ".join(sorted(leaked)))
    return {
        "event": event,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "surface": surface,
        "metadata": safe_metadata,
    }
