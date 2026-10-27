"""Compatibility facade; all normalization lives in adapters.csv."""
from adapters.csv import parsing as P
from adapters.csv.listing_source import LISTING_ALIASES, normalize_row
from core.listing_diff import FeedDelta, diff_listings, listing_fingerprint

REQUIRED_COLUMNS = ("id", "transaction", "area", "price", "property_type", "rooms", "url", "listed_at")


def normalize_listing(row, *, source="csv"):
    missing = [key for key in REQUIRED_COLUMNS if row.get(key) is None or str(row[key]).strip() == ""]
    if missing:
        raise ValueError("listing missing required fields: " + ", ".join(missing))
    return normalize_row({k: str(v) if v is not None else "" for k, v in row.items()},
                         {k: k for k in LISTING_ALIASES if k in row}, source=source)


def load_csv(text, *, source="csv"):
    headers, rows = P.read_table(P.decode_bytes(text))
    mapping, _ = P.resolve_mapping(headers, LISTING_ALIASES)
    if not all(k in mapping for k in ("id", "transaction", "area", "price")):
        raise ValueError("CSV missing required columns")
    return [normalize_row(row, mapping, source=source) for _, row in rows]
