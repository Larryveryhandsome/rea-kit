"""客戶／物件匯入的防呆（2026-11-05 上線品質複查）。合成資料、不連網。"""
import tempfile
import unittest

from adapters.csv import parsing as P
from adapters.csv.customer_source import CsvCustomerSource
from adapters.storage import TenantStore

import test_customer_intake as support

T = "tenant-a"


class CustomerImportHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cs = CsvCustomerSource(TenantStore(self.tmp.name))

    def test_phone_in_label_is_not_stored(self):
        rep = self.cs.import_customers(T, "客戶編號,稱呼,買或租,需求區域,預算(萬)\r\n"
                                          "A001,合成客戶 02-0000-0000,買,台中市西屯區,1200\r\n")
        self.assertEqual(rep.new_ids, ["A001"])
        self.assertIsNone(self.cs.get(T, "A001")["label"])
        self.assertIn("電話", rep.errors[0]["reason"])

    def test_budget_min_above_max_is_reported(self):
        rep = self.cs.import_customers(T, "客戶編號,買或租,需求區域,預算下限,預算上限\r\n"
                                          "A001,買,台中市西屯區,1500,1200\r\n")
        self.assertEqual(rep.rows_ok, 0)
        self.assertIn("預算下限", rep.errors[0]["reason"])


class DateParsingTests(unittest.TestCase):
    def test_impossible_dates_give_chinese_error(self):
        for s in ("2026/02/30", "115/13/01"):
            with self.assertRaises(ValueError) as cm:
                P.parse_date(s)
            self.assertIn("日期不存在", str(cm.exception))
        self.assertEqual(P.parse_date("115/10/01"), "2026-10-01")



class EditCsvCustomerWithoutLabelTests(unittest.TestCase):
    setUp = support.CustomerIntakeTests.setUp
    tearDown = support.CustomerIntakeTests.tearDown
    send = support.CustomerIntakeTests.send

    def test_edit_need_of_customer_imported_without_label(self):
        self.customers.import_customers("tenant-a", "客戶編號,買或租,需求區域,預算(萬)\r\nA001,買,台中市西屯區,1200\r\n")
        for t in ["修改需求 A001", "買", "台中市西屯區", "800-1500", "不限", "不限", "不限", "不限", "不限", "不限"]:
            reply = self.send(t)
        self.assertNotIn("None", reply["text"])
        self.send("確認儲存")
        self.assertNotEqual(self.customers.get("tenant-a", "A001")["label"], "None")


if __name__ == "__main__":
    unittest.main()
