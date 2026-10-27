"""adapters/csv：物件與客戶 CSV 匯入（欄位對映、單位、online 旗標、租戶隔離、資料最小化）。全合成資料。"""
import datetime
import pathlib
import tempfile
import unittest

from adapters.csv import parsing as P
from adapters.csv.customer_source import CsvCustomerSource, parse_budget
from adapters.csv.listing_source import CsvListingSource
from adapters.line.fake_api import synthetic_line_id
from adapters.storage import TenantStore

FIX = pathlib.Path(__file__).resolve().parent / "fixtures"
LISTINGS = (FIX / "listings_synthetic.csv").read_bytes()
CUSTOMERS = (FIX / "customers_synthetic.csv").read_bytes()


class Clock:
    def __init__(self, dt):
        self.dt = dt

    def __call__(self):
        return self.dt


class ParsingTests(unittest.TestCase):
    def test_price_units(self):
        self.assertEqual(P.parse_price("1,280萬", transaction="buy"), 1280)
        self.assertEqual(P.parse_price("12800000", transaction="buy"), 1280)
        self.assertEqual(P.parse_price("1280", transaction="buy", header="總價(元)"), 1280)
        self.assertEqual(P.parse_price("1.2萬", transaction="rent"), 12000)
        self.assertEqual(P.parse_price("18000", transaction="rent", header="預算(萬)"), 18000)
        self.assertEqual(P.parse_price("1.5", transaction="rent"), 15000)

    def test_dates_including_roc(self):
        self.assertEqual(P.parse_date("115/09/28"), "2026-09-28")
        self.assertEqual(P.parse_date("民國115年9月28日"), "2026-09-28")
        self.assertEqual(P.parse_date("2026/9/3"), "2026-09-03")
        with self.assertRaises(ValueError):
            P.parse_date("下週")

    def test_property_types_follow_moi_names(self):
        self.assertEqual(P.parse_property_type("住宅大樓(11層含以上有電梯)"), "電梯大樓")
        self.assertEqual(P.parse_property_type("華廈(10層含以下有電梯)"), "華廈")
        self.assertEqual(P.parse_property_type("透天厝"), "透天")
        self.assertEqual(P.parse_property_type("套房(1房1廳1衛)"), "套房")
        self.assertIsNone(P.parse_property_type("其他"))

    def test_online_flag(self):
        self.assertTrue(P.parse_online("銷售中"))
        self.assertFalse(P.parse_online("已成交"))
        self.assertFalse(P.parse_online("未上架"))
        self.assertFalse(P.parse_online("停止刊登"))
        self.assertIsNone(P.parse_online(""))
        self.assertIsNone(P.parse_online("unknown"))

    def test_area_normalization(self):
        self.assertEqual(P.normalize_area("臺中市西屯區"), ("台中市", "台中市西屯區"))
        self.assertEqual(P.normalize_area("西屯區", city="臺中市"), ("台中市", "台中市西屯區"))
        self.assertEqual(P.normalize_area("東區", default_city="新竹市"), ("新竹市", "新竹市東區"))

    def test_header_aliases_ignore_units_in_brackets(self):
        mp, unmapped = P.resolve_mapping(["物件編號", "總價（萬）", "怪欄位"], {"id": ("物件編號",), "price": ("總價",)})
        self.assertEqual(mp, {"id": "物件編號", "price": "總價（萬）"})
        self.assertEqual(unmapped, ["怪欄位"])

    def test_big5_csv_is_decoded(self):
        text = "物件編號,區域\nS-1,中央區\n"
        self.assertEqual(P.decode_bytes(text.encode("cp950")), text)

    def test_budget_range(self):
        self.assertEqual(parse_budget("900-1000萬", transaction="buy"), (900, 1000))
        self.assertEqual(parse_budget("1200", transaction="buy"), (None, 1200))


class ListingSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TenantStore(self.tmp.name)
        self.clock = Clock(datetime.datetime(2026, 10, 1, 9, 0))
        self.src = CsvListingSource(self.store, now=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def test_import_normalizes_and_reports(self):
        rep = self.src.import_csv("t1", LISTINGS)
        self.assertEqual(rep.rows_total, 8)
        self.assertEqual(rep.rows_ok, 7)
        self.assertEqual(rep.errors, [{"line": 9, "reason": "缺區域"}])
        self.assertEqual(rep.ignored_sensitive_columns, ["地址", "備註"])
        s101 = self.src.get("t1", "S-101")
        self.assertEqual(s101["area"], "示範市中央區")
        self.assertEqual(s101["price"], 1180)
        self.assertEqual(s101["rooms"], 3)
        self.assertEqual(s101["listed_at"], "2026-09-28")
        self.assertEqual(s101["property_type"], "電梯大樓")
        self.assertNotIn("地址", str(self.store.read_json("t1", "listings", "snapshot.json")))
        self.assertNotIn("合成路", str(self.store.read_json("t1", "listings", "snapshot.json")))
        r201 = self.src.get("t1", "R-201")
        self.assertEqual((r201["transaction"], r201["price"], r201["rooms"]), ("rent", 12000, 0))
        self.assertEqual(self.src.get("t1", "S-106")["age_years"], 0)

    def test_online_flag_and_public_url(self):
        self.src.import_csv("t1", LISTINGS)
        active = [x["id"] for x in self.src.list_active("t1")]
        self.assertNotIn("S-104", active)
        self.assertIsNone(self.src.public_url("t1", "S-104"))
        self.assertEqual(self.src.public_url("t1", "S-101"), "https://example.test/l/S-101")
        self.assertTrue(self.src.mark_online("t1", "S-101", False))
        self.assertIsNone(self.src.public_url("t1", "S-101"))

    def test_reimport_diff_and_removed_marked_offline(self):
        self.src.import_csv("t1", LISTINGS)
        self.clock.dt = datetime.datetime(2026, 10, 2, 9, 0)
        text = LISTINGS.decode("utf-8")
        text = text.replace(",1180,", ",1150,")                                  # S-101 降價
        text = "\n".join(ln for ln in text.splitlines() if not ln.startswith("S-102"))   # S-102 不在新檔
        rep = self.src.import_csv("t1", text.encode("utf-8"))
        self.assertEqual(rep.changed_ids, ["S-101"])
        self.assertEqual(rep.removed_ids, ["S-102"])
        self.assertEqual(rep.new_ids, [])
        self.assertFalse(self.src.get("t1", "S-102")["online"])
        changes = self.src.changes_since("t1", "2026-10-01T23:59:59")
        self.assertEqual({(c["id"], c["kind"]) for c in changes}, {("S-101", "changed"), ("S-102", "removed")})
        self.assertIn("price", next(c for c in changes if c["id"] == "S-101")["fields"])

    def test_tenants_are_isolated(self):
        self.src.import_csv("t1", LISTINGS)
        self.assertEqual(self.src.list_all("t2"), [])
        self.assertIsNone(self.src.get("t2", "S-101"))

    def test_manual_mapping_and_default_transaction(self):
        csv_text = "編號X,所在,金額\nQ-1,示範市中央區,999\n"
        with self.assertRaises(ValueError):
            self.src.import_csv("t1", csv_text)
        rep = self.src.import_csv("t1", csv_text, mapping={"id": "編號X", "area": "所在", "price": "金額"},
                                  default_transaction="buy")
        self.assertEqual(rep.rows_ok, 1)
        self.assertEqual(self.src.get("t1", "Q-1")["price"], 999)

    def test_sensitive_column_cannot_be_mapped(self):
        with self.assertRaises(ValueError):
            self.src.import_csv("t1", LISTINGS, mapping={"title": "地址"})

    def test_delete_all(self):
        self.src.import_csv("t1", LISTINGS)
        self.src.delete_all("t1")
        self.assertEqual(self.src.list_all("t1"), [])


class CustomerSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TenantStore(self.tmp.name)
        self.clock = Clock(datetime.datetime(2026, 10, 1, 9, 0))
        self.src = CsvCustomerSource(self.store, now=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def test_import_builds_need_cards_without_sensitive_columns(self):
        rep = self.src.import_customers("t1", CUSTOMERS, default_city="示範市")
        self.assertEqual(rep.rows_ok, 5)
        self.assertEqual(rep.ignored_sensitive_columns, ["電話", "備註"])
        reasons = {e["line"]: e["reason"] for e in rep.errors}
        self.assertIn("LINE ID 格式不對", reasons[3])
        self.assertEqual(reasons[7], "缺客戶編號")
        card = self.src.get_need_card("t1", "A001")
        self.assertEqual(card["need_card"]["preferred_areas"], ["示範市中央區"])
        self.assertEqual(card["need_card"]["budget_max"], 1200)
        self.assertEqual(card["need_card"]["budget_tolerance_pct"], 10)
        self.assertEqual(card["need_card"]["property_type"], "電梯大樓")
        self.assertEqual(card["missing"], [])
        self.assertFalse(card["can_push"])                 # 還沒綁 LINE 群
        a002 = self.src.get_need_card("t1", "A002")["need_card"]
        self.assertEqual((a002["budget_min"], a002["budget_max"]), (900, 1000))
        self.assertEqual(a002["preferred_areas"], ["示範市河濱區", "示範市中央區"])
        self.assertEqual(self.src.get_need_card("t1", "A003")["need_card"]["budget_max"], 15000)
        self.assertEqual(self.src.get_need_card("t1", "A005")["missing"], ["preferred_areas"])
        self.assertEqual([c["customer_id"] for c in self.src.list_customers("t1")], ["A001", "A002", "A003", "A005"])
        self.assertNotIn("000-000", str(self.store.read_json("t1", "customers", "customers.json")))

    def test_bind_target_and_reimport_keeps_binding_and_bumps_version(self):
        self.src.import_customers("t1", CUSTOMERS, default_city="示範市")
        gid = synthetic_line_id("C", "a001")
        self.src.bind_line_target("t1", "A001", gid, members=3)
        self.assertTrue(self.src.get_need_card("t1", "A001")["can_push"])
        rep = self.src.import_customers("t1", CUSTOMERS.decode("utf-8").replace("A001,合成客戶甲,買,中央區,1200",
                                                                              "A001,合成客戶甲,買,中央區,1300"),
                                        default_city="示範市")
        self.assertIn("A001", rep.changed_ids)
        a001 = self.src.get("t1", "A001")
        self.assertEqual(a001["line_target"], gid)
        self.assertEqual(a001["need_card"]["version"], 2)
        self.assertEqual(a001["need_card"]["budget_max"], 1300)

    def test_bad_target_is_refused(self):
        self.src.import_customers("t1", CUSTOMERS, default_city="示範市")
        with self.assertRaises(ValueError):
            self.src.bind_line_target("t1", "A001", "not-a-line-id")

    def test_export_roundtrip_and_delete(self):
        self.src.import_customers("t1", CUSTOMERS, default_city="示範市")
        out = self.src.export("t1")
        self.assertTrue(out.startswith("customer_id,label,status"))
        other = CsvCustomerSource(TenantStore(self.tmp.name + "-copy"), now=self.clock)
        rep = other.import_customers("t9", out)
        self.assertEqual(rep.rows_ok, 5)
        self.assertEqual(other.get("t9", "A002")["need_card"]["budget_min"], 900)
        self.src.delete_all("t1")
        self.assertEqual(self.src.list_customers("t1", active_only=False), [])

    def test_import_groups_from_line_events(self):
        gid = synthetic_line_id("C", "joined")
        active = self.src.import_groups("t1", [{"type": "join", "timestamp": 5,
                                                 "source": {"type": "group", "groupId": gid}}])
        self.assertEqual(active, [gid])


if __name__ == "__main__":
    unittest.main()
