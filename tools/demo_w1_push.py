# -*- coding: utf-8 -*-
"""W1 示範：合成 CSV → 配對 → 推播閘 → 一張 Flex 物件卡。

    python tools/demo_w1_push.py            本機假 LINE（預設，什麼都不會真的送出）
    python tools/demo_w1_push.py --real     送到「測試用」LINE 官方帳號，收件人＝你自己

--real 需要兩個環境變數（只設在自己電腦，不寫進任何檔案）：
    REA_DEMO_LINE_TOKEN   測試用官方帳號的 channel access token（不要用正在服務客戶的帳號）
    REA_DEMO_OWNER_ID     你自己的 LINE userId（U 開頭 33 碼；在 LINE Developers 後台 Basic settings 看得到）
--real 會用掉該帳號 1 則推播額度。資料全是合成的，配對結果裡「客戶」就是你自己。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from adapters.csv.customer_source import CsvCustomerSource          # noqa: E402
from adapters.csv.listing_source import CsvListingSource            # noqa: E402
from adapters.line.client import LineClient                         # noqa: E402
from adapters.line.credentials import TenantLineConfig, is_line_id  # noqa: E402
from adapters.line.fake_api import FakeLineApi, synthetic_line_id   # noqa: E402
from adapters.line.push_gate import GatePolicy, PushGate            # noqa: E402
from adapters.storage import TenantStore                            # noqa: E402
from web.jobs.new_listing_push import run_new_listing_push          # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true", help="送到測試用 LINE 官方帳號（收件人＝你自己）")
    a = ap.parse_args()

    fake = None
    if a.real:
        token, owner = os.environ.get("REA_DEMO_LINE_TOKEN", ""), os.environ.get("REA_DEMO_OWNER_ID", "")
        if not token or not is_line_id(owner) or not owner.startswith("U"):
            print("✗ --real 需要環境變數 REA_DEMO_LINE_TOKEN 與 REA_DEMO_OWNER_ID（U 開頭的 LINE userId）")
            return 2
        client = LineClient(token)
    else:
        owner = synthetic_line_id("U", "demo-owner")
        fake = FakeLineApi(token="demo-token").start()
        client = LineClient("demo-token", api_base=fake.base_url, min_interval=0)
        token = "demo-token"

    with tempfile.TemporaryDirectory() as tmp:
        store = TenantStore(tmp)
        cfg = TenantLineConfig("demo", "demo-secret", token, owner_user_id=owner)
        listings, customers = CsvListingSource(store), CsvCustomerSource(store)
        rep = listings.import_csv("demo", (FIX / "listings_synthetic.csv").read_bytes())
        customers.import_customers("demo", (FIX / "customers_synthetic.csv").read_bytes(), default_city="示範市")
        print(f"① 物件 CSV：{rep.rows_ok}/{rep.rows_total} 筆匯入，略過欄位 {rep.ignored_sensitive_columns}，"
              f"錯誤 {[(e['line'], e['reason']) for e in rep.errors]}")
        # 示範只推一位客戶：把合成客戶 A001 的推播對象設成你自己（1 對 1，花 1 則額度）
        customers.bind_line_target("demo", "A001", owner)
        gate = PushGate(store, cfg, client, policy=GatePolicy.from_dict({"modes": {"match": "auto"}}))
        run = run_new_listing_push(tenant_id="demo", store=store, listings=listings, customers=customers,
                                   gate=gate, listing_ids=rep.new_ids, max_per_push=3)
        mine = [p for p in run.pushed if p["customer_id"] == "A001"]
        print(f"② 配對＋推播閘：{json.dumps(mine, ensure_ascii=False)}")
        print(f"   本月額度：{gate.budget.summary()['used']}/{gate.budget.summary()['plan_cap']}")
        if fake:
            sent = [p for p in fake.pushes if p["to"] == owner]
            print(f"③ 假 LINE 收到 {len(sent)} 則給你的 Flex：")
            if sent:
                m = sent[0]["messages"][0]
                print("   altText：", m["altText"])
                print("   卡片數：", len(m["contents"].get("contents", [m["contents"]])))
            fake.stop()
        else:
            print("③ 去手機看測試官方帳號，應該收到一張可左右滑的物件卡。")
    return 0 if any(p["state"] == "sent" for p in mine) else 1


if __name__ == "__main__":
    raise SystemExit(main())
