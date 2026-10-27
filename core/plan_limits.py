"""Free-plan usage rules for the first product offer."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

FREE_PAIRING_LIMIT = 100
FREE_MONITOR_DAYS = 7


@dataclass
class FreePlanUsage:
    pairing_listing_ids: set[str] = field(default_factory=set)
    monitor_started_at: datetime | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "FreePlanUsage":
        started = data.get("monitor_started_at")
        parsed = datetime.fromisoformat(started) if isinstance(started, str) and started else None
        return cls(set(str(item) for item in data.get("pairing_listing_ids", [])), parsed)

    def to_mapping(self) -> dict[str, Any]:
        return {"pairing_listing_ids": sorted(self.pairing_listing_ids), "monitor_started_at": self.monitor_started_at.isoformat() if self.monitor_started_at else None}

    def can_pair(self, listing_id: str) -> bool:
        key = str(listing_id).strip()
        return bool(key) and (key in self.pairing_listing_ids or len(self.pairing_listing_ids) < FREE_PAIRING_LIMIT)

    def record_pairing(self, listing_id: str) -> bool:
        if not self.can_pair(listing_id):
            return False
        self.pairing_listing_ids.add(str(listing_id).strip())
        return True

    def start_monitor(self, *, now: datetime | None = None) -> datetime:
        if self.monitor_started_at is None:
            self.monitor_started_at = now or datetime.now(timezone.utc)
        return self.monitor_started_at

    def monitor_active(self, *, now: datetime | None = None) -> bool:
        if self.monitor_started_at is None:
            return False
        current = now or datetime.now(timezone.utc)
        return current < self.monitor_started_at + timedelta(days=FREE_MONITOR_DAYS)
