"""Pure snapshot differences. Observation/publication timestamps are not changes."""
import hashlib
import json
from dataclasses import dataclass

MATERIAL_FIELDS = ("transaction", "city", "area", "title", "price", "property_type", "rooms",
                   "size_ping", "age_years", "floor", "url", "photo_url", "online", "parking", "elevator")


def listing_fingerprint(listing):
    blob = json.dumps({k: listing.get(k) for k in MATERIAL_FIELDS}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FeedDelta:
    new: tuple[dict, ...]
    changed: tuple[dict, ...]
    unchanged: tuple[dict, ...]
    removed_ids: tuple[str, ...]


def diff_listings(previous, current):
    def index(rows):
        out = {}
        for row in rows:
            key = str(row.get("id") or "").strip()
            if not key or key in out:
                raise ValueError("snapshot requires unique non-empty listing ids")
            out[key] = dict(row)
        return out
    old, new = index(previous), index(current)
    added, changed, same = [], [], []
    for key, row in new.items():
        target = added if key not in old else same if listing_fingerprint(old[key]) == listing_fingerprint(row) else changed
        target.append(row)
    return FeedDelta(tuple(added), tuple(changed), tuple(same), tuple(sorted(set(old) - set(new))))
