"""Deterministic, data-only listing matching for the public product.

This module deliberately has no network, CRM, messaging, or tenant storage
dependencies. An adapter or MCP server supplies normalized dictionaries; this
module only validates, filters, scores, and explains the result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping
from urllib.parse import urlsplit
from core.property_schema import area_matches, canonical_type


@dataclass(frozen=True)
class MatchResult:
    listing_id: str
    bucket: str
    score: int
    reasons: tuple[str, ...] = field(default_factory=tuple)
    missing: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "listing_id": self.listing_id,
            "bucket": self.bucket,
            "score": self.score,
            "reasons": list(self.reasons),
            "missing": list(self.missing),
        }


def _text(value: Any) -> str:
    return str(value).strip().casefold() if value is not None else ""


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _areas(need: Mapping[str, Any]) -> tuple[str, ...]:
    values = need.get("preferred_areas", need.get("areas", ()))
    if isinstance(values, str):
        values = (values,)
    if not isinstance(values, (list, tuple, set)):
        return ()
    return tuple(_text(v) for v in values if _text(v))


def validate_need_card(need: Mapping[str, Any]) -> tuple[str, ...]:
    """Return missing/invalid fields without guessing defaults."""
    errors: list[str] = []
    if _text(need.get("transaction")) not in {"buy", "rent"}:
        errors.append("transaction must be buy or rent")
    if not _areas(need):
        errors.append("preferred_areas is required")
    budget = _number(need.get("budget_max"))
    if budget is None or budget <= 0:
        errors.append("budget_max must be a positive finite number")
    for key in ("budget_min", "rooms_min", "size_min", "size_max", "age_max"):
        if need.get(key) is not None:
            number = _number(need[key])
            if number is None or number < 0:
                errors.append(key + " must be a non-negative finite number")
    for lo, hi in (("budget_min", "budget_max"), ("size_min", "size_max")):
        if _number(need.get(lo)) is not None and _number(need.get(hi)) is not None:
            if _number(need[lo]) > _number(need[hi]):
                errors.append(lo + " exceeds " + hi)
    for key in ("parking", "elevator"):
        if need.get(key, "any") not in ("any", "required", "preferred"):
            errors.append(key + " must be any, required or preferred")
    tolerance = _number(need.get("budget_tolerance_pct", 0))
    if tolerance is None or tolerance < 0 or tolerance > 100:
        errors.append("budget_tolerance_pct must be between 0 and 100")
    rooms = _number(need.get("rooms_min"))
    if rooms is not None and rooms < 0:
        errors.append("rooms_min cannot be negative")
    return tuple(errors)


def match_listings(need: Mapping[str, Any], listings: list[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Return explainable priority/review/rejected buckets.

    Hard filters are transaction, area, budget, and explicit property type.
    Missing listing fields go to review instead of being treated as a match.
    The score is intentionally small and transparent: preferred-area fit (10),
    room fit (10), and complete evidence (5).
    """
    errors = validate_need_card(need)
    if errors:
        raise ValueError("invalid need card: " + "; ".join(errors))

    transaction = _text(need["transaction"])
    areas = set(_areas(need))
    max_budget = _number(need["budget_max"])
    tolerance = _number(need.get("budget_tolerance_pct", 0)) or 0
    tolerated_budget = max_budget * (1 + tolerance / 100)
    required_type = canonical_type(need.get("property_type"))
    rooms_min = _number(need.get("rooms_min"))
    output: dict[str, list[dict[str, Any]]] = {"priority": [], "review": [], "rejected": []}

    for listing in listings:
        listing_id = str(listing.get("id") or "").strip() or "<missing-id>"
        reasons: list[str] = []
        missing: list[str] = []
        hard_fail: list[str] = []

        if listing_id == "<missing-id>":
            missing.append("id")
        if listing.get("online") is False:
            hard_fail.append("listing offline")
        if not _text(listing.get("transaction")):
            missing.append("transaction")
        elif _text(listing.get("transaction")) != transaction:
            hard_fail.append("transaction mismatch")
        area = _text(listing.get("area"))
        if not area:
            missing.append("area")
        elif not any(area_matches(area, requested) for requested in areas):
            hard_fail.append("area mismatch")

        price = _number(listing.get("price"))
        if price is None or price <= 0:
            missing.append("price")
        elif price > tolerated_budget:
            hard_fail.append("over budget tolerance")
        elif _number(need.get("budget_min")) is not None and price < _number(need["budget_min"]):
            hard_fail.append("below budget minimum")

        listing_type = canonical_type(listing.get("property_type"))
        if required_type and not listing_type:
            missing.append("property_type")
        elif required_type and listing_type != required_type and listing_type not in ALSO_OK.get(required_type, ()):
            hard_fail.append("property type mismatch")

        rooms = _number(listing.get("rooms"))
        if rooms_min is not None and rooms is None:
            missing.append("rooms")
        elif rooms_min is not None and rooms < rooms_min:
            hard_fail.append("rooms below minimum")

        for field, lower, upper in (("size_ping", "size_min", "size_max"), ("age_years", None, "age_max")):
            lo, hi = _number(need.get(lower)), _number(need.get(upper))
            if lo is None and hi is None:
                continue
            value = _number(listing.get(field))
            if value is None or value < 0:
                missing.append(field)
            elif (lo is not None and value < lo) or (hi is not None and value > hi):
                hard_fail.append(field + " outside required range")
        preferred_score = 0
        for feature in ("parking", "elevator"):
            policy, value = need.get(feature, "any"), listing.get(feature)
            if policy == "required":
                if value is False:
                    hard_fail.append(feature + " required")
                elif value is not True:
                    missing.append(feature)
            elif policy == "preferred" and value is True:
                preferred_score += 5
                reasons.append(feature + " preference met")

        try:
            url = urlsplit(str(listing.get("url") or ""))
            valid_url = url.scheme in {"http", "https"} and bool(url.hostname) and not url.username
        except ValueError:
            valid_url = False
        if not valid_url:
            missing.append("url")

        if hard_fail:
            bucket = "rejected"
            reasons.extend(hard_fail)
        elif missing:
            bucket = "review"
            reasons.append("needs supplied fields before sending")
        else:
            bucket = "priority"
            score = 25 + preferred_score
            if any(area_matches(area, requested) for requested in areas):
                score += 10
                reasons.append("preferred area")
            if rooms_min is not None and rooms == rooms_min:
                score += 10
                reasons.append("meets room target")
            score += 5
            reasons.append("complete evidence")
            if price is not None and price > max_budget:
                # 容忍範圍內但超預算：照樣列，但排在預算內的後面，理由寫清楚（實務經驗：超預算的常被排第一）
                score -= 30
                reasons.append(f"over budget by {price - max_budget:g}")
            output[bucket].append(MatchResult(listing_id, bucket, score, tuple(reasons), tuple(missing)).as_dict())
            continue

        score = 0
        if bucket == "review":
            reasons.extend(f"missing {item}" for item in missing)
            score = 5
        output[bucket].append(MatchResult(listing_id, bucket, score, tuple(reasons), tuple(missing)).as_dict())

    # 同分要有固定的先後：新上架的先、屋齡新的先（實務經驗：同分只靠編號排，某些物件永遠排在最後）
    by_id = {str(x.get("id") or "").strip(): x for x in listings}

    def age(item: dict[str, Any]) -> float:
        value = _number(by_id.get(item["listing_id"], {}).get("age_years"))
        return value if value is not None else math.inf

    for rows in output.values():              # 穩定排序由次要到主要：編號 → 屋齡 → 上架日（新的先）→ 分數
        rows.sort(key=lambda item: item["listing_id"])
        rows.sort(key=age)
        rows.sort(key=lambda item: str(by_id.get(item["listing_id"], {}).get("listed_at") or ""), reverse=True)
        rows.sort(key=lambda item: -item["score"])
    return output


# 客人要的型態可以接受的其他寫法（審查：透天客人配不到別墅，每日新物件卻當成同一種）
ALSO_OK = {"透天": ("別墅",)}
