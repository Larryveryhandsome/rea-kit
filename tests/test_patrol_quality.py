"""海巡品質（負責人 2026-10-08：「海巡只需要真實的買賣方」）。
用一週存下來的候選貼文逐篇複查後，把錯的樣式寫成合成句子鎖住：留下來的多半是同業刊登、平台新聞、行情文；
漏掉的是在物件底下問價的人、沒寫地區的找房文、「看了三間房子」的人。內容全部改寫過，不是原文。"""
import datetime
import unittest

from core import patrol_keywords as PK
from core.post_facts import TW
from core.post_triage import judge
from web.jobs import daily_brief as DB

NOW = datetime.datetime(2026, 10, 8, 9, 0, tzinfo=TW)
PHONE = "09" + "11" + "-222" + "333"                     # 拆開寫：測試資料不放完整電話樣式


def run(text, *, own=None, handle="someone", intent="buy"):
    return judge(text, county="宜蘭縣", area_term="宜蘭", intent=intent, posted_at=NOW - datetime.timedelta(hours=5),
                 now=NOW, handle=handle, own=own)


class AgentAndNoiseDropped(unittest.TestCase):
    def test_listing_posts(self):
        posts = {
            "文末電話": f"宜蘭買房，真的不用每間都重新裝潢！宜蘭東區質感好宅，近轉運站 合成不動產｜王小明 {PHONE}",
            "詳情私訊": "以前覺得買房就是買一間房子。這不是單純的農舍，而是宜蘭生活宅。詳情私訊我",
            "品牌署名": "368萬在礁溪溫泉旁可以買到什麼？在家就能泡湯。合成不動產｜小明 買屋賣屋，一通電話幫你",
            "給想買房的你": "如果你一直想在宜蘭找一塊地，但總覺得價格太高，這塊可以先存起來，現在只開1.5萬／坪",
            "自稱房仲": "我是宜蘭房仲小柚，在宜蘭做房仲第5年。如果你最近也有想買房但不知道買不買得起的問題",
            "加我line": "698萬2房2廳怎麼買！？直接找我最快，快加我Line ID",
            "替客戶找": "最近接到一個委託：有買方想在宜蘭尋找千坪莊園，預算約1億",
        }
        for name, text in posts.items():
            with self.subTest(name):
                self.assertFalse(run(text).keep, name)

    def test_platform_media_and_agent_accounts(self):
        text = "雙北客移居宜蘭買房潮再起！專家警告外地買方常踩雷，想買房要先看屋況"
        for handle in ("demo_official", "rakuyatw", "housefun_tw", "lailai.house", "best_realty_tw"):
            with self.subTest(handle):
                self.assertFalse(run(text, handle=handle).keep)

    def test_market_commentary(self):
        for text in ("1000萬買房，各縣市大概差多少？Q2 實價登錄均價：宜蘭23.7萬／坪",
                     "快訊：宜蘭鐵路高架加速推進，宜蘭房市未來十年最大題材，受惠的是看懂趨勢的人"):
            with self.subTest(text):
                self.assertFalse(run(text).keep)

    def test_bare_buy_word_is_not_intent(self):
        self.assertFalse(run("宜蘭五結鄉！不錯的規格房間 宜蘭買房 這間就是拿來享受的溫泉宅").keep)


class RealBuyersAndSellersKept(unittest.TestCase):
    def test_inquiry_under_a_listing(self):
        v = run("請問開價，有詳細資訊可參考嗎？謝謝 礁溪玉田電梯農舍，宜蘭縣礁溪鄉，83坪，3580萬",
                own="請問開價，有詳細資訊可參考嗎？謝謝")
        self.assertEqual((v.keep, v.reason), (True, "在問一間物件，可能是買方（點進去看他問哪間）"))
        self.assertFalse(run("想了解報價，謝謝 台中西屯三房", own="想了解報價，謝謝").keep)    # 問的是別的縣市

    def test_seeker_without_area_and_viewer(self):
        v = run("想找一間合法的獨棟農舍或平房，最好一樓平層，要有大庭院讓狗狗跑")
        self.assertTrue(v.keep)
        self.assertIn("沒寫地區", v.reason)
        self.assertTrue(run("朋友在宜蘭買的房子交屋了，結果我自己看了三個房子也被宜蘭房子燒到了").keep)

    def test_reply_in_a_thread_points_to_the_seeker(self):
        v = run("應該蠻多的 請問羅東哪裡有透天要賣的？", own="應該蠻多的")
        self.assertEqual(v.reason, "這串留言裡有人在找房（點進去看原文）")

    def test_owner_sellers(self):
        for text in ("老家在宜蘭羅東的透天想賣掉，賣房要注意什麼？", "我們家在礁溪的土地想賣，有推薦的房仲嗎？",
                     "屋主自售 宜蘭市三房公寓，不經仲介"):
            with self.subTest(text):
                v = run(text, intent="sell")
                self.assertTrue(v.keep, v.reason)
                self.assertIn("屋主想賣", v.reason)
        self.assertFalse(run("很新的華廈這裡有一戶要賣，2房不用700萬，要快", intent="sell").keep)   # 不是自己的房子
        self.assertFalse(run("有沒有switch遊戲片二手想出售？", intent="sell").keep)


class SellerPatrolGroups(unittest.TestCase):
    def test_seller_group_query_and_label(self):
        g = PK.build_groups({"宜蘭縣": ["*"]}, ["sell"], ["住宅"])[0]
        self.assertEqual(g.label, "宜蘭・屋主想賣")
        (q, _accept, recency, pages), = DB.patrol_sources(g)                      # 只搜 Threads、一頁
        self.assertIn("屋主自售", q)
        self.assertEqual((recency, pages), ("w", 1))


class NightlyReview20261015(unittest.TestCase):
    """2026-10-15 夜間複查：3 天留下 12 篇，5 篇誤留。句子都是改寫合成的。"""

    def test_negated_or_ad_style_want_is_not_a_buyer(self):
        for text in ("真的別衝動，如果不想買房就要把同樣的錢拿去投資宜蘭的資產",
                     "宜蘭哪裡有週末打工？另外奉勸想在楊梅買房的人一定要想清楚"):
            with self.subTest(text):
                self.assertFalse(run(text, own="說得對").keep)

    def test_thread_reply_over_policy_text_is_dropped(self):
        text = "第一次買房，我們會幫青年在宜蘭成家，規劃三年修繕補助，縣長候選人政見"
        self.assertFalse(run(text, own="好棒喔").keep)

    def test_other_account_blurb_does_not_count_as_area(self):
        text = ("求屋主！ demoacct's profile picture · 示範房屋《宜蘭、羅東租屋》 (@demoacct) ... "
                "【求租】兩房 地區：台中北屯")
        self.assertFalse(run(text, intent="rent", own="租金多少").keep)
        self.assertTrue(run("【求租】羅東兩房一廳，預算一萬五", intent="rent").keep)


class RentersAndAdviceNoise(unittest.TestCase):
    """2026-10-18 複查（竹北找租客的仲介）：真的求租都留下，房東廣告、政見、稅務文、回憶文、閒聊擋掉。內容改寫過。"""

    def rent(self, text, own=None):
        return judge(text, county="新竹縣", area_term="竹北", intent="rent", posted_at=NOW - datetime.timedelta(hours=5),
                     now=NOW, handle="someone", own=own)

    def test_real_renters_kept(self):
        for text in ("【誠心求租】地區：竹北市 預算：月租8000內 獨立套房 入住時間越快越好",
                     "竹北有沒有兩萬以內的兩房一廳？新豐也可以", "租屋條件：竹北三房整層，月租預算24,000-26,000，要可開伙"):
            with self.subTest(text):
                self.assertTrue(self.rent(text).keep)

    def test_not_renters(self):
        noise = {
            "閒聊": "搬完家發現舊租屋處租金漲了一成，還是先繼續租屋吧，繼續存錢",
            "房東問租金": "竹北高鐵附近房價四千萬，每月租金設在多少適合？",
            "房東廣告": "竹北電梯套房出租，可租補可報稅，拎包入住，有意可和本人查詢",
            "政見": "我的政見是推動寵物友善租屋，讓竹北毛家長租房子不再辛苦，候選人某某",
        }
        for name, text in noise.items():
            with self.subTest(name):
                self.assertFalse(self.rent(text).keep, name)
        ad = self.rent("Line詢問預約 禁菸禁寵請勿詢問 竹北電梯套房出租", own="Line詢問預約 禁菸禁寵請勿詢問")
        self.assertFalse(ad.keep)                                                   # 不是在問物件，是招租

    def test_advice_and_memories(self):
        self.assertFalse(run("家戶合併申報所得稅的制度說明：繼承來的房子要賣，先把繼承登記與遺產稅證明備齊",
                             intent="sell").keep)
        self.assertFalse(run("30多年前我本想在新生北路買房，被爸媽擋下來，現在好後悔").keep)
        self.assertFalse(run("要準備租房買房嗎？我很閒，可以陪你一整天找房，歡迎港澳台").keep)
        self.assertFalse(run("想了解 宜蘭23.7萬／坪 #實價雷達#實價登錄#買房知識", own="想了解").keep)


if __name__ == "__main__":
    unittest.main()
