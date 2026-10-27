"""No credentials: LINE form → customer book → weekly in-memory match → fake LINE."""
import datetime
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from adapters.csv.customer_source import CsvCustomerSource
from adapters.ephemeral_listing_source import EphemeralListingSource
from adapters.line.client import LineClient
from adapters.line.fake_api import FakeLineApi, synthetic_line_id
from adapters.line.flex import agent_digest_messages, validate_message
from adapters.line.shared import SharedChannelConfig
from adapters.line.signature import sign
from adapters.storage import TenantStore
from web.jobs.agent_digest import build_digest
from web.line_app import create_app


def main():
    now = datetime.datetime(2026, 10, 1, 9)
    with tempfile.TemporaryDirectory() as temp:
        fake = FakeLineApi(token="demo-token").start()
        try:
            store = TenantStore(temp)
            app = create_app(store=store, channel=SharedChannelConfig("demo-secret", "demo-token"), now=lambda: now,
                             client_factory=lambda token: LineClient(token, api_base=fake.base_url, min_interval=0))
            owner = synthetic_line_id("U", "intake-demo")
            messages = ["綁定 " + app.registry.issue_code("demo"), "新增買方", "合成客戶甲", "買", "台中市西屯區",
                        "800-1500", "公寓", "2", "20-40", "20", "偏好", "不限", "確認儲存"]
            for index, text in enumerate(messages):
                body = json.dumps({"events": [{"type": "message", "webhookEventId": f"demo-{index}",
                    "replyToken": f"reply-{index}", "source": {"type": "user", "userId": owner},
                    "message": {"type": "text", "text": text}}]}).encode()
                assert app.handle(body, sign("demo-secret", body))[0] == 200
            customers = CsvCustomerSource(store)
            assert len(customers.list_customers("demo")) == 1
            source = EphemeralListingSource("demo", [{"id": "Demo-A", "transaction": "buy", "area": "台中市西屯區",
                "price": 1200, "property_type": "公寓", "rooms": 2, "size_ping": 30, "age_years": 12,
                "listed_at": "2026-10-01", "url": "https://example.test/demo-a"}], today=now.date())
            items = build_digest(tenant_id="demo", listings=source, customers=customers, identify_customers=True)
            cards = agent_digest_messages(items, intro="合成七日案件配對")
            assert len(cards) == 1 and not validate_message(cards[0])
            assert app.notify("demo", cards).state == "sent"
            assert len(fake.pushes) == 1 and fake.pushes[0]["to"] == owner
            assert not store.path("demo", "listings").exists()
            assert not store.path("demo", "line", "messages").exists()
            print("PASS: signed bind + guided intake + confirmed customer + seven-day in-memory match + fake agent-only notification")
            print("No real LINE call, website collection, raw chat archive or listing snapshot. Existing push outbox retains message payload.")
            return 0
        finally:
            fake.stop()


if __name__ == "__main__":
    raise SystemExit(main())
