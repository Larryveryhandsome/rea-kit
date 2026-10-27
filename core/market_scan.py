"""Region-scoped market scan and alert queue over normalized listings."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from core.listing_diff import FeedDelta, diff_listings
from core.property_schema import area_matches, canonical_type
from core.listing_matching import match_listings


def _text(value: Any) -> str:
    return str(value).strip().casefold() if value is not None else ""


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class MarketScanCriteria:
    area: str
    transaction: str | None = None
    property_type: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    size_min: float | None = None
    size_max: float | None = None
    age_max: float | None = None


def _scope_reasons(listing: Mapping[str, Any], criteria: MarketScanCriteria) -> tuple[list[str], list[str]]:
    rejected: list[str] = []
    missing: list[str] = []
    if not area_matches(listing.get("area"), criteria.area):
        rejected.append("area mismatch")
    if criteria.transaction and _text(listing.get("transaction")) != _text(criteria.transaction):
        rejected.append("transaction mismatch")
    if criteria.property_type:
        value = _text(listing.get("property_type"))
        if not value:
            missing.append("property_type")
        elif canonical_type(value) != canonical_type(criteria.property_type):
            rejected.append("property type mismatch")
    price = _number(listing.get("price"))
    if price is None and (criteria.price_min is not None or criteria.price_max is not None):
        missing.append("price")
    elif price is not None:
        if criteria.price_min is not None and price < criteria.price_min:
            rejected.append("below price range")
        if criteria.price_max is not None and price > criteria.price_max:
            rejected.append("above price range")
    size = _number(listing.get("size_ping"))
    if size is None and (criteria.size_min is not None or criteria.size_max is not None):
        missing.append("size_ping")
    elif size is not None:
        if criteria.size_min is not None and size < criteria.size_min:
            rejected.append("below size range")
        if criteria.size_max is not None and size > criteria.size_max:
            rejected.append("above size range")
    age = _number(listing.get("age_years"))
    if age is None and criteria.age_max is not None:
        missing.append("age_years")
    elif age is not None and criteria.age_max is not None and age > criteria.age_max:
        rejected.append("over age limit")
    return rejected, missing


def scan_snapshot(listings: Iterable[Mapping[str, Any]], criteria: MarketScanCriteria) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {"candidates": [], "review": [], "excluded": []}
    for listing in listings:
        rejected, missing = _scope_reasons(listing, criteria)
        item = {"listing": dict(listing), "reasons": []}
        if rejected:
            item["reasons"] = rejected
            result["excluded"].append(item)
        elif missing:
            item["reasons"] = [f"missing {field}" for field in missing]
            result["review"].append(item)
        else:
            item["reasons"] = ["within requested market scope"]
            result["candidates"].append(item)
    result["candidates"].sort(key=lambda item: _text(item["listing"].get("id")))
    return result


def build_alert_queue(previous: Iterable[Mapping[str, Any]], current: Iterable[Mapping[str, Any]], criteria: MarketScanCriteria) -> dict[str, Any]:
    """Return only new/changed scoped listings plus audit counts."""
    delta: FeedDelta = diff_listings(previous, current)
    eligible = []
    for row in (*delta.new, *delta.changed):
        copy = dict(row)
        copy["change_kind"] = "new" if row in delta.new else "changed"
        eligible.append(copy)
    scoped = scan_snapshot(eligible, criteria)
    return {
        "queue": scoped["candidates"],
        "review": scoped["review"],
        "excluded": scoped["excluded"],
        "unchanged_count": len(delta.unchanged),
        "removed_ids": list(delta.removed_ids),
    }


def match_alert_queue(alert_result: Mapping[str, Any], need: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Match only scoped alert candidates to one buyer need card."""
    listings = [item["listing"] for item in alert_result.get("queue", [])]
    return match_listings(need, listings)
