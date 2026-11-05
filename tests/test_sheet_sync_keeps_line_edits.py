"""試算表每日同步不能蓋掉仲介在 LINE 做的事（2026-11-05 上線品質複查）。合成資料、不連網。

1. LINE「新增物件」加的物件，不會因為不在試算表裡就被下架。
2. 試算表那一列沒變時，LINE 改過的需求與「暫停」狀態要保留；試算表真的改了才更新。
"""
import tempfile
import unittest

from adapters.csv.customer_source import CsvCustomerSource
from adapters.csv.listing_source import CsvListingSource
from adapters.storage import TenantStore

T = "tenant-a"
LISTING_SHEET = "物件編號,交易,縣市,區域,總價(萬)\r\nS-001,出售,台中市,西屯區,1180\r\n"
CUSTOMER_SHEET = "客戶編號,稱呼,買或租,需求區域,預算(萬)\r\nA001,合成客戶甲,買,台中市西屯區,1200\r\n"


class SheetSyncKeepsLineEditsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = TenantStore(self.tmp.name)

    def test_line_added_listing_stays_online_after_sheet_sync(self):
        listings = CsvListingSource(self.store)
        rec = listings.save_one(T, {"transaction": "buy", "city": "台中市", "area": "台中市西屯區", "price": 1200,
                                    "property_type": "電梯大樓", "own": True, "source": "line"})
        rep = listings.import_csv(T, LISTING_SHEET, source="gsheet", replace=True)
        self.assertEqual(rep.removed_ids, [])
        self.assertTrue(listings.get(T, rec["id"])["online"])
        # 試算表自己帶進來、後來從試算表刪掉的，照樣下架
        rep = listings.import_csv(T, LISTING_SHEET.replace("S-001", "S-002"), source="gsheet", replace=True)
        self.assertEqual(rep.removed_ids, ["S-001"])
        self.assertTrue(listings.get(T, rec["id"])["online"])

    def test_unchanged_sheet_row_keeps_line_pause_and_need_edits(self):
        customers = CsvCustomerSource(self.store)
        customers.import_customers(T, CUSTOMER_SHEET)
        customers.update_identity(T, "A001", status="paused")
        old = customers.get(T, "A001")
        need = {**old["need_card"], "budget_min": 800, "budget_max": 1500, "parking": "required"}
        customers.save_need(T, label="合成客戶甲", need=need, customer_id="A001",
                            expected_version=old["need_card"].get("version", 1))
        customers.import_customers(T, CUSTOMER_SHEET)                     # 隔天排程同步，試算表沒動
        c = customers.get(T, "A001")
        self.assertEqual(c["status"], "paused")
        self.assertEqual(c["need_card"].get("parking"), "required")
        self.assertEqual((c["need_card"]["budget_min"], c["need_card"]["budget_max"]), (800, 1500))

    def test_changed_sheet_row_still_updates(self):
        customers = CsvCustomerSource(self.store)
        customers.import_customers(T, CUSTOMER_SHEET)
        customers.update_identity(T, "A001", status="paused")
        rep = customers.import_customers(T, CUSTOMER_SHEET.replace("1200", "1300"))
        c = customers.get(T, "A001")
        self.assertEqual(rep.changed_ids, ["A001"])
        self.assertEqual(c["need_card"]["budget_max"], 1300)
        self.assertEqual(c["status"], "paused")                          # 試算表沒有狀態欄：沿用 LINE 設的


if __name__ == "__main__":
    unittest.main()
