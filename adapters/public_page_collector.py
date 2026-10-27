"""Offline extraction helpers. All server collection is disabled pending review."""
import json
from typing import Any


class CollectionStopped(RuntimeError):
    """Collection has not been approved for this release."""


def fetch_public_page(url: str, *, timeout: int = 10) -> str:
    # Deliberately no network imports, approval flag or fallback browser.
    raise CollectionStopped("server collection disabled pending source review and owner approval")


def extract_jsonld_records(html: str) -> list[dict[str, Any]]:
    marker = '<script type="application/ld+json">'
    records = []
    for fragment in html.split(marker)[1:]:
        payload = fragment.split("</script>", 1)[0].strip()
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            continue
        values = value if isinstance(value, list) else [value]
        records.extend(item for item in values if isinstance(item, dict))
    return records
