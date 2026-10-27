"""Run a safe, synthetic product walkthrough for local dogfooding."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.csv_listing_source import load_csv
from core.market_scan import MarketScanCriteria, build_alert_queue, match_alert_queue
from core.plan_limits import FreePlanUsage

CSV = """id,transaction,area,price,property_type,rooms,url,listed_at,size_ping,age_years,source
DEMO-001,buy,中央區,1180,公寓,2,https://example.test/DEMO-001,2026-10-01,28,8,synthetic
DEMO-002,buy,東區,1050,公寓,2,https://example.test/DEMO-002,2026-10-01,28,8,synthetic
DEMO-003,buy,中央區,1500,公寓,3,https://example.test/DEMO-003,2026-10-01,42,18,synthetic
"""
NEED = {"transaction": "buy", "preferred_areas": ["中央區"], "budget_max": 1200, "budget_tolerance_pct": 10, "property_type": "公寓", "rooms_min": 2}


def main() -> int:
    previous = load_csv(CSV)
    current = load_csv(CSV.replace("1180,公寓", "1160,公寓").replace("DEMO-002,buy,東區", "DEMO-004,buy,中央區"))
    criteria = MarketScanCriteria(area="中央區", transaction="buy", property_type="公寓", price_max=1200, size_min=20, size_max=35, age_max=12)
    alerts = build_alert_queue(previous, current, criteria)
    matched = match_alert_queue(alerts, NEED)
    usage = FreePlanUsage()
    for item in matched["priority"]:
        usage.record_pairing(item["listing_id"])
    print("rea-kit synthetic self-test")
    print(f"market queue: {len(alerts['queue'])} candidates; unchanged={alerts['unchanged_count']}")
    print(f"buyer matches: {len(matched['priority'])} priority; {len(matched['review'])} review")
    print(f"free usage: {len(usage.pairing_listing_ids)}/100 unique listing pairings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
