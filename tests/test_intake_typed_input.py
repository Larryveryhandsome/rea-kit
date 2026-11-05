"""新增買方：打字的區域、點選的預算按鈕都要收得下（2026-11-05 上線品質複查）。純邏輯、合成資料。"""
import unittest

from adapters.line import customer_intake as CI


class TypedAreaTests(unittest.TestCase):
    def test_full_county_name_wins_over_two_char_prefix(self):
        # 以前「新竹縣」被「新竹」市搶走 → 「新竹市沒有縣竹北市這個區」
        self.assertEqual(CI._typed_areas("新竹縣竹北市"), ["新竹縣竹北市"])
        self.assertEqual(CI._typed_areas("嘉義縣"), ["嘉義縣"])
        self.assertEqual(CI._typed_areas("嘉義縣民雄鄉"), ["嘉義縣民雄鄉"])

    def test_district_with_county_prefix_stays_in_same_county(self):
        self.assertEqual(CI._typed_areas("桃園市中壢區、桃園區"), ["桃園市中壢區", "桃園市桃園區"])
        self.assertEqual(CI._typed_areas("苗栗縣 苗栗市"), ["苗栗縣", "苗栗縣苗栗市"])

    def test_short_forms_still_work(self):
        self.assertEqual(CI._typed_areas("台中西屯區"), ["台中市西屯區"])
        self.assertEqual(CI._typed_areas("台中市西屯"), ["台中市西屯區"])
        self.assertEqual(CI._typed_areas("台中市西屯區 南屯區"), ["台中市西屯區", "台中市南屯區"])
        self.assertEqual(CI._typed_areas("新竹竹北市"), ["新竹縣竹北市"])          # 兩字簡寫挑區名對得上的縣市
        self.assertEqual(CI._typed_areas("新竹東區"), ["新竹市東區"])
        self.assertEqual(CI._typed_areas("台北市大安區、新北市板橋區"), ["台北市大安區", "新北市板橋區"])

    def test_unknown_district_still_rejected(self):
        with self.assertRaises(CI.IntakeError):
            CI._typed_areas("台中市不存在區")
        with self.assertRaises(CI.IntakeError):
            CI._typed_areas("西屯區")                                             # 沒縣市


class BudgetButtonTests(unittest.TestCase):
    def test_every_offered_budget_button_is_accepted(self):
        # 以前租屋的「6萬以上」按鈕永遠被擋（預算要有上限）
        for tx, buttons in (("buy", CI.BUY_BUDGETS), ("rent", CI.RENT_BUDGETS)):
            for b in buttons:
                draft = {"step": "budget", "need": {"transaction": tx}}
                CI.advance(draft, b)
                self.assertNotEqual(draft["step"], "budget", f"{tx} {b}")
                self.assertIsNotNone(draft["need"].get("budget_max"), f"{tx} {b}")


if __name__ == "__main__":
    unittest.main()
