"""Compatibility import facade. Canonical parsing lives in adapters.csv."""
from adapters.csv import parsing as P
from adapters.csv.customer_source import CsvCustomerSource, CUSTOMER_ALIASES
from core.listing_matching import validate_need_card


def normalize_need_card(row, *, source="csv"):
    raw = {k: str(v) if v is not None else "" for k, v in row.items()}
    mapping = {k: k for k in CUSTOMER_ALIASES if k in raw}
    customer = CsvCustomerSource._normalize(raw, mapping, None, 0)
    need = customer["need_card"]
    errors = validate_need_card(need)
    if errors:
        raise ValueError("; ".join(errors))
    consent = raw.get("consent_status") or "pending"
    if consent not in {"tenant-confirmed", "pending", "revoked"}:
        raise ValueError("invalid consent_status")
    return {**need, "customer_id": customer["customer_id"], "source": source,
            "updated_at": raw.get("updated_at", ""), "consent_status": consent}


def load_csv(text, *, source="csv"):
    headers, rows = P.read_table(P.decode_bytes(text))
    mapping, _ = P.resolve_mapping(headers, CUSTOMER_ALIASES)
    return [normalize_need_card({**{k: row.get(h, "") for k, h in mapping.items()},
                                 "consent_status": row.get("consent_status", "pending"),
                                 "updated_at": row.get("updated_at", "")}, source=source)
            for _, row in rows]


def active_need_cards(cards):
    return [dict(card) for card in cards if card.get("consent_status") == "tenant-confirmed"]
