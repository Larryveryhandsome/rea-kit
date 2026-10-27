"""全台行政區字典：22 縣市、368 鄉鎮市區，與配對用的縣市清單一致。"""
import unittest

from core.property_schema import CITIES, area_matches
from core.tw_districts import COUNTIES, DISTRICTS, WHOLE, area_names, is_district

EXPECTED = {"台北市": 12, "新北市": 29, "桃園市": 13, "台中市": 29, "台南市": 37, "高雄市": 38, "基隆市": 7,
            "新竹市": 3, "嘉義市": 2, "新竹縣": 13, "苗栗縣": 18, "彰化縣": 26, "南投縣": 13, "雲林縣": 20,
            "嘉義縣": 18, "屏東縣": 33, "宜蘭縣": 12, "花蓮縣": 13, "台東縣": 16, "澎湖縣": 6, "金門縣": 6,
            "連江縣": 4}


class DistrictTests(unittest.TestCase):
    def test_counts_match_current_administrative_divisions(self):
        self.assertEqual({c: len(d) for c, d in DISTRICTS.items()}, EXPECTED)
        self.assertEqual(sum(EXPECTED.values()), 368)

    def test_same_counties_and_order_as_matching_vocabulary(self):
        self.assertEqual(COUNTIES, CITIES)

    def test_no_duplicates_and_proper_suffixes_and_no_traditional_tai(self):
        for county, names in DISTRICTS.items():
            self.assertEqual(len(names), len(set(names)), county)
            for n in names:
                self.assertTrue(n.endswith(("區", "鄉", "鎮", "市")), n)
                self.assertNotIn("臺", n)

    def test_area_names_feed_matching(self):
        names = area_names({"台中市": ["南屯區", "西屯區"], "彰化縣": [WHOLE]})
        self.assertEqual(names, ["台中市西屯區", "台中市南屯區", "彰化縣"])     # 依字典順序
        self.assertTrue(area_matches("台中市西屯區", names[0]))
        self.assertTrue(area_matches("彰化縣員林市", names[2]))               # 縣市＝全縣市
        self.assertTrue(is_district("台中市", "西屯區"))
        self.assertFalse(is_district("台中市", "員林市"))


if __name__ == "__main__":
    unittest.main()
