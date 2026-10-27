"""找新買方設定精靈：縣市複選／全台、行政區點選（postback）、確認後才保存。合成資料、本機假 LINE。"""
import datetime
import json
import unittest

import test_customer_intake as support
from adapters.line import area_picker as AP
from adapters.line.flex import validate_message
from adapters.line.prospect_setup import PURPOSE, STATE
from adapters.line.signature import sign
from core.patrol_keywords import KEYWORDS
from core.tw_districts import COUNTIES, DISTRICTS, WHOLE

PKW = KEYWORDS[("buy", "住宅")]


class ProspectSetupTests(unittest.TestCase):
    setUp = support.CustomerIntakeTests.setUp
    tearDown = support.CustomerIntakeTests.tearDown
    send = support.CustomerIntakeTests.send

    def tap(self, op, value="", *, purpose=PURPOSE, eid=None, county=""):
        """模擬點卡片按鈕（postback，不帶 displayText）。回傳這次回覆的全部訊息。county＝按鈕所屬卡片的縣市。"""
        self.count += 1
        body = json.dumps({"events": [{"type": "postback", "webhookEventId": eid or f"pb-{self.count}",
            "replyToken": f"reply-{self.count}", "source": {"type": "user", "userId": self.uid},
            "postback": {"data": AP.data(op, purpose, value, county)}}]}).encode()
        self.assertEqual(self.app.handle(body, sign("test-secret", body))[0], 200)
        hit = [r for r in self.api.replies if r["replyToken"] == f"reply-{self.count}"]
        return hit[0]["messages"] if hit else []

    def state(self, tenant="tenant-a"):
        return self.store.read_json(tenant, *STATE, default={}) or {}

    def idx(self, county, name):
        return str(DISTRICTS[county].index(name))

    def pick_two_counties(self):
        card = self.send("找新買方")
        self.assertEqual(card["type"], "flex")
        self.assertIn("選服務縣市", card["altText"])
        self.assertIn("已選：台中市", self.tap("c", "台中市")[0]["text"])
        self.assertIn("已選：台中市、彰化縣", self.tap("c", "彰化縣")[0]["text"])
        first = self.tap("next")[0]
        self.assertIn("台中市：選區域", first["altText"])
        self.tap("d", self.idx("台中市", "西屯區"))
        self.assertIn("西屯區、南屯區", self.tap("d", self.idx("台中市", "南屯區"))[0]["text"])
        done = self.tap("done")
        self.assertIn("✓ 台中市：西屯區、南屯區", done[0]["text"])
        self.assertIn("彰化縣：選區域", done[-1]["altText"])
        return self.tap("d", WHOLE, county="彰化縣")[-1]               # 全區＝直接下一步

    def test_multi_county_district_picking_saves_only_after_consent(self):
        self.assertIn("還是承租需求", self.pick_two_counties()["text"])
        self.send("買")
        self.assertIn("海巡關鍵字", self.send("住宅")["altText"])
        self.send("關鍵字選好了")
        confirm = self.send("09:00")
        self.assertIn("台中市：西屯區、南屯區；彰化縣：全區", confirm["text"])
        self.assertIn("海巡：共 3 組", confirm["text"])                 # 西屯、南屯、彰化 × 買住宅
        self.assertNotIn("profile", self.state())
        self.send("同意保存設定")
        profile = self.state()["profile"]
        self.assertEqual(profile["cities"], ["台中市", "彰化縣"])
        self.assertEqual(profile["areas"], {"台中市": ["西屯區", "南屯區"], "彰化縣": [WHOLE]})
        self.assertFalse(profile["monitoring_enabled"])
        self.assertEqual(profile["timezone"], "Asia/Taipei")
        self.assertIn("台中市：西屯區、南屯區", self.send("海巡狀態")["text"])
        self.assertEqual(self.api.pushes, [])
        self.assertEqual(self.customers.list_customers("tenant-a"), [])

    def test_whole_taiwan_in_one_tap(self):
        self.send("找新買方")
        replies = self.tap("all")
        self.assertIn("全台", replies[0]["text"])
        self.assertIn("還是承租需求", replies[1]["text"])
        draft = self.state()["draft"]
        self.assertEqual(draft["cities"], list(COUNTIES))
        self.assertTrue(all(draft["areas"][c] == [WHOLE] for c in COUNTIES))

    def test_toggle_off_and_guard_rails(self):
        self.send("找新買方")
        self.tap("c", "台中市")
        self.assertIn("還沒選縣市", self.tap("c", "台中市")[0]["text"])
        self.assertIn("請至少選一個縣市", self.tap("next")[0]["text"])
        self.tap("c", "台北市")
        self.tap("next")
        self.assertIn("還沒選區域", self.tap("done")[0]["text"])
        self.assertEqual(self.state()["draft"]["step"], "area")
        self.tap("c", "台南市")                                   # 縣市步驟以外的縣市按鈕無效，不改資料
        self.assertEqual(self.state()["draft"]["cities"], ["台北市"])
        self.tap("d", "999")                                     # 不存在的序號不改資料
        self.assertEqual(self.state()["draft"]["areas"]["台北市"], [])

    def test_owner_repro_whole_is_set_not_toggle(self):
        """負責人 23:16 實測：點卡片「全區」後又點快速回覆「全區」，舊版互相抵銷變成沒選。"""
        self.send("找新買方")
        self.tap("c", "宜蘭縣")
        self.tap("next")
        replies = self.tap("d", WHOLE, county="宜蘭縣")
        self.assertIn("✓ 宜蘭縣：全區", replies[0]["text"])
        self.assertIn("還是承租需求", replies[-1]["text"])              # 只選一個縣市→直接到下一題
        self.send("全區")                                                # 再按一次也不會取消
        self.tap("d", WHOLE, county="宜蘭縣")
        self.assertEqual(self.state()["draft"]["areas"]["宜蘭縣"], [WHOLE])
        self.assertEqual(self.state()["draft"]["step"], "transaction")

    def test_whole_text_reply_also_advances(self):
        self.send("找新買方")
        self.tap("c", "宜蘭縣")
        self.tap("next")
        self.tap("d", self.idx("宜蘭縣", "羅東鎮"), county="宜蘭縣")
        self.assertIn("✓ 宜蘭縣：全區", self.send("全區")["text"])
        self.assertIn("還是承租需求", self.api.replies[-1]["messages"][-1]["text"])
        self.assertEqual(self.state()["draft"]["areas"]["宜蘭縣"], [WHOLE])   # 全區取代已點的區

    def test_old_card_only_changes_its_own_county(self):
        self.send("找新買方")
        self.tap("c", "宜蘭縣")
        self.tap("c", "彰化縣")
        self.tap("next")
        first, second = self.state()["draft"]["cities"]
        self.tap("d", WHOLE, county=first)                               # 第一個縣市全區→換第二張卡
        note = self.tap("d", "0", county=first)[0]["text"]               # 回頭點第一張卡的第一區
        self.assertIn(f"現在在選 {second}", note)
        areas = self.state()["draft"]["areas"]
        self.assertEqual(areas[first], [DISTRICTS[first][0]])
        self.assertEqual(areas[second], [])                              # 沒有誤改到正在選的縣市
        self.assertIn("已經選好了", self.tap("done", county=first)[0]["text"])
        self.assertEqual(self.state()["draft"]["cursor"], 1)
        self.assertIn("請點選卡片", self.tap("d", "0", county="台南市")[0]["text"])   # 不在名單裡的縣市：不改資料
        self.assertNotIn("台南市", self.state()["draft"]["areas"])

    def test_old_cards_without_county_still_work(self):
        """已經發到手機上的舊卡片沒有 k：照「現在正在選的縣市」處理。"""
        self.send("找新買方")
        self.tap("c", "宜蘭縣")
        self.tap("next")
        self.tap("d", WHOLE)
        self.assertEqual(self.state()["draft"]["step"], "transaction")

    def test_cancel_expiry_and_tenant_isolation(self):
        self.send("找新買方")
        self.tap("c", "台中市")
        self.send("取消")
        self.assertIsNone(self.state()["draft"])
        self.send("找新買方")
        self.tap("all")
        self.dt += datetime.timedelta(minutes=31)
        self.send("買")
        self.assertIsNone(self.state()["draft"])
        self.assertNotIn("profile", self.state())
        self.assertEqual(self.state("tenant-b"), {})

    def test_bad_time_and_duplicate_confirmation(self):
        self.send("找新買方")
        self.tap("all")
        for text in ("租", "住宅", "關鍵字選好了", "25:00"):
            self.send(text)
        self.assertEqual(self.state()["draft"]["step"], "time")
        self.send("18:00")
        self.send("同意保存設定", eid="save-settings")
        before = self.state()["profile"]
        self.send("海巡狀態", eid="save-settings")
        self.assertEqual(before, self.state()["profile"])

    def test_existing_customer_draft_not_consumed(self):
        self.send("新增買方")
        self.assertIn("先輸入取消", self.send("找新買方")["text"])
        self.send("取消")
        self.assertIn("選服務縣市", self.send("找新買方")["altText"])

    def test_clear_profile_and_legacy_profile_display(self):
        self.store.write_json("tenant-a", *STATE, data={"profile": {
            "city": "台中市", "area": "全縣市", "transaction": "買", "kind": "住宅", "time": "09:00"}})
        self.assertIn("台中市／全縣市", self.send("海巡狀態")["text"])
        self.send("清除海巡設定")
        self.assertNotIn("profile", self.state())
        self.assertIn("尚未保存", self.send("海巡狀態")["text"])

    def test_other_purpose_postback_ignored_and_wrong_step_hint(self):
        self.send("找新買方")
        self.tap("all")
        replies = self.tap("c", "台中市")
        self.assertIn("這一步不是選區域", replies[0]["text"])
        before = self.state()["draft"]
        self.assertIn("已經用過了", self.tap("c", "台中市", purpose="intake")[0]["text"])   # 由替買方找房那邊回
        self.assertEqual(self.state()["draft"], before)
        self.send("取消")
        self.assertIn("已經用過了", self.tap("c", "台中市")[0]["text"])                   # 沒草稿的舊卡

    def test_keywords_multi_select_and_todays_patrol(self):
        self.send("找新買方")
        self.tap("all")                                              # 全台 22 縣市 → 22 組
        self.send("買")
        self.send("住宅")
        defaults = self.state()["draft"]["keywords"]
        self.assertEqual(defaults[:2], ["買房", "找房"])
        self.tap("kw", "0")                                          # 取消「買房」
        self.assertIn("已選：找房", self.tap("kw", "4")[0]["text"])    # 「徵屋」本來就勾 → 取消
        self.assertNotIn("買房", self.state()["draft"]["keywords"])
        self.tap("kw", "0")                                          # 再勾回「買房」
        for i in range(12):
            if PKW[i] in self.state()["draft"]["keywords"]:
                self.tap("kw", str(i))
        self.assertIn("至少選一個", self.tap("kwdone")[0]["text"])
        self.tap("kw", "1")
        self.tap("kw", str(PKW.index("換屋")))                        # 找房、換屋
        self.tap("kwdone")
        self.send("09:00")
        self.assertIn("約 8 天輪完", self.api.replies[-1]["messages"][0]["text"])
        self.send("同意保存設定")
        self.assertEqual(self.state()["profile"]["keywords"], ["找房", "換屋"])
        msgs = self.api.replies[-1]["messages"] if self.send("今日海巡") else []
        self.assertIn("今日海巡：3 組", msgs[0]["text"])
        card = msgs[1]
        self.assertEqual(validate_message(card), [])
        bubbles = card["contents"]["contents"]
        self.assertEqual(len(bubbles), 3)
        uris = [b["action"]["uri"] for bub in bubbles for b in bub["footer"]["contents"]]
        self.assertEqual(len(uris), 6)                               # 3 組 × 2 個關鍵字
        self.assertTrue(all(u.startswith("https://www.threads.com/search?") for u in uris))
        self.assertIn("找房", json.dumps(bubbles[0], ensure_ascii=False))

    def test_type_your_own_keywords(self):
        """負責人 2026-10-02：圖卡要能自由選擇關鍵字，或是讓他輸入。"""
        self.send("找新買方")
        self.tap("c", "宜蘭縣")
        self.tap("next")
        self.tap("d", WHOLE, county="宜蘭縣")
        self.send("買")
        self.assertIn("也可以直接打字", json.dumps(self.send("住宅"), ensure_ascii=False))
        self.assertIn("已加入「想買農舍」", self.send("想買農舍")["text"])
        self.assertIn("已移除「想買農舍」", self.send("想買農舍")["text"])
        self.send("找海景透天")
        self.assertIn("1–10 個字", self.send("http://x.test")["text"])
        self.assertIn("1–10 個字", self.send("a" * 11)["text"])
        self.tap("kwdone")
        self.send("09:00")
        self.send("同意保存設定")
        self.assertIn("找海景透天", self.state()["profile"]["keywords"])
        self.assertIn("找海景透天", self.send("海巡狀態")["text"])

    def test_todays_patrol_needs_new_style_profile(self):
        # 圖文選單第一次點「找新買方」（今日海巡）：直接開始設定，不叫他再去點別的
        self.assertIn("先設定一次你的海巡範圍", self.send("今日海巡")["text"])
        self.store.write_json("tenant-a", *STATE, data={"profile": {
            "city": "台中市", "area": "全縣市", "transaction": "買", "kind": "住宅", "time": "09:00"}})
        self.assertIn("先設定一次你的海巡範圍", self.send("今日海巡")["text"])          # 舊版設定也重設一次

    def test_cards_fit_line_limits(self):
        cards = [AP.county_card(COUNTIES[:5], PURPOSE)] + [AP.district_card(c, [], PURPOSE) for c in COUNTIES]
        for card in cards:
            self.assertEqual(validate_message(card), [], card["altText"])
            contents = card["contents"]
            bubbles = contents["contents"] if contents["type"] == "carousel" else [contents]
            for bubble in bubbles:
                self.assertLess(len(json.dumps(bubble, ensure_ascii=False).encode("utf-8")), 10_000, card["altText"])
            for b in bubbles:
                for row in b["body"]["contents"]:
                    for btn in row["contents"]:
                        if btn["type"] == "button":
                            self.assertLessEqual(len(btn["action"]["data"]), 300)
        names = [btn["action"]["label"].lstrip("✓")
                 for b in AP.district_card("高雄市", [], PURPOSE)["contents"]["contents"]
                 for row in b["body"]["contents"] for btn in row["contents"] if btn["type"] == "button"]
        self.assertEqual(names, list(DISTRICTS["高雄市"]))          # 38 區全部在、順序不變，分兩頁


if __name__ == "__main__":
    unittest.main()
