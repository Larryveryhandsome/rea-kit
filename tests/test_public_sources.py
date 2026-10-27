import json
import tempfile
import unittest
from pathlib import Path

from adapters.public_page_collector import CollectionStopped, extract_jsonld_records
from adapters.public_source_registry import load_registry, runnable_sources
from core.customer_need_candidates import extract_candidates


class PublicSourceTests(unittest.TestCase):
    def test_registry_requires_explicit_verified_status_for_scheduling(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.json"
            path.write_text(json.dumps([
                {"source_id": "demo", "display_name": "Demo", "kind": "agency",
                 "homepage": "https://example.test", "status": "candidate-unverified", "parser": "jsonld"}
            ]), encoding="utf-8")
            rows = load_registry(path)
            self.assertEqual(runnable_sources(rows), [])

    def test_jsonld_fixture_is_extractable(self):
        html = '<script type="application/ld+json">{"@type":"Product","name":"demo"}</script>'
        self.assertEqual(extract_jsonld_records(html)[0]["name"], "demo")

    def test_chat_batch_creates_review_candidates(self):
        result = extract_candidates([{"external_ref": "chat-1", "text": "想買中央區兩房，預算1500萬"}], known_areas=["中央區"])
        self.assertEqual(result[0]["preferred_areas"], ["中央區"])
        self.assertTrue(result[0]["review_required"])

    def test_collector_stop_type_is_public(self):
        self.assertTrue(issubclass(CollectionStopped, RuntimeError))
