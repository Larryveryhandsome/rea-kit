"""海巡關鍵字模組：地區詞 × 需求詞組、每日 3 組輪流、跨仲介去重。"""
import datetime
import unittest

from core.patrol_keywords import (DAILY_GROUPS, KEYWORDS, KINDS, PatrolGroup, ambiguous_terms, area_terms,
                                  build_groups, county_term, default_keywords, district_term, merge_queries,
                                  threads_url, todays_groups)
from core.tw_districts import COUNTIES, WHOLE


class PatrolKeywordTests(unittest.TestCase):
    def test_owner_examples(self):
        g = build_groups({"彰化縣": [WHOLE]}, ["buy"], ["住宅"])
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0].queries()[:2], ["彰化 買房", "彰化 找房"])
        d = build_groups({"台北市": ["大同區"]}, ["buy"], ["住宅"])[0]
        self.assertEqual(d.queries()[0], "大同 買房")
        self.assertIn("大同 找房", d.queries())
        self.assertIn("大同", ambiguous_terms())                  # 台北大同區、宜蘭大同鄉

    def test_area_terms(self):
        self.assertEqual(county_term("台北市"), "台北")
        self.assertEqual(district_term("台中市", "西屯區"), "西屯")
        self.assertEqual(district_term("台中市", "東區"), "台中東區")
        self.assertEqual(district_term("高雄市", "那瑪夏區"), "那瑪夏")
        self.assertEqual(district_term("彰化縣", "員林市"), "員林")
        self.assertEqual(area_terms({"台中市": ["西屯區", "南屯區"], "彰化縣": [WHOLE]}),
                         [("西屯", "台中市"), ("南屯", "台中市"), ("彰化", "彰化縣")])

    def test_every_intent_kind_has_keywords_without_duplicates(self):
        for i in ("buy", "rent"):
            for k in KINDS:
                kws = KEYWORDS[(i, k)]
                self.assertGreaterEqual(len(kws), 4, (i, k))
                self.assertEqual(len(kws), len(set(kws)), (i, k))

    def test_daily_cap_and_rotation_covers_everything(self):
        groups = build_groups({c: [WHOLE] for c in COUNTIES}, ["buy"], ["住宅"])
        self.assertEqual(len(groups), 22)
        day0 = datetime.date(2026, 10, 2)
        seen = set()
        for n in range(8):
            today = todays_groups(groups, day0 + datetime.timedelta(days=n))
            self.assertEqual(len(today), DAILY_GROUPS)
            seen.update(g.label for g in today)
        self.assertEqual(seen, {g.label for g in groups})          # 8 天內全部輪過
        self.assertEqual(todays_groups(groups, day0), todays_groups(groups, day0))    # 同一天結果固定

    def test_small_selection_runs_all(self):
        groups = build_groups({"彰化縣": [WHOLE]}, ["buy", "rent"], ["住宅"])
        self.assertEqual([g.label for g in todays_groups(groups, datetime.date(2026, 10, 2))],
                         ["彰化・買住宅", "彰化・租住宅"])

    def test_merge_dedupes_across_agents(self):
        a = build_groups({"彰化縣": [WHOLE]}, ["buy"], ["住宅"])
        b = build_groups({"彰化縣": [WHOLE], "台中市": ["西屯區"]}, ["buy"], ["住宅"])
        merged = merge_queries({"t1": a, "t2": b})
        self.assertEqual(merged["彰化 買房"], ["t1", "t2"])
        self.assertEqual(merged["西屯 買房"], ["t2"])

    def test_rejects_unknown_choices(self):
        with self.assertRaises(ValueError):
            build_groups({"彰化縣": [WHOLE]}, ["lease"], ["住宅"])
        with self.assertRaises(ValueError):
            build_groups({"彰化縣": [WHOLE]}, ["buy"], ["別墅"])

    def test_group_label(self):
        self.assertEqual(PatrolGroup("彰化", "彰化縣", "rent", "廠房").label, "彰化・租廠房")

    def test_chosen_keywords_and_threads_link(self):
        g = build_groups({"彰化縣": [WHOLE]}, ["buy"], ["住宅"], ["換屋", "找房", "想買農舍"])[0]
        self.assertEqual(g.queries(), ["彰化 換屋", "彰化 找房", "彰化 想買農舍"])        # 自己打的詞也用
        url = threads_url("彰化 買房")
        self.assertTrue(url.startswith("https://www.threads.com/search?"))
        self.assertIn("q=%E5%BD%B0%E5%8C%96+%E8%B2%B7%E6%88%BF", url)
        self.assertIn("filter=recent", url)
        self.assertEqual(default_keywords("buy", "住宅")[:2], ("買房", "找房"))


if __name__ == "__main__":
    unittest.main()
