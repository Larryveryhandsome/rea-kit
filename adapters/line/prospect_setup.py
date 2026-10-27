"""找新買方（海巡）設定：只存仲介自己的服務範圍與關鍵字，不收買方個資。

服務範圍用點選卡：縣市可複選（或全台）→ 每個縣市點選行政區（或全區）→ 買／租 → 類別 → 海巡關鍵字（可複選）
→ 摘要時間 → 同意保存。保存後「今日海巡」＝當天最多 3 組（地區×需求）：
  有接搜尋服務 → 直接給最近一天想買／想租的那幾篇貼文本身（patrol_now），每天也會自動推在「今日報告」；
  沒接 → 備案：給 Threads 搜尋連結（負責人 2026-10-02：搜尋關鍵字大家都會，要直接給那一篇文章）。
"""
import datetime
import re

from adapters.line import area_picker as AP, flex
from adapters.line.customer_intake import message
from adapters.line.onboarding import welcome
from core import patrol_keywords as PK

STATE = ("line", "prospect_setup.json")
PURPOSE = "prospect"
KINDS = ("住宅", "土地", "廠房", "商用")
KW_DONE_TEXT = "關鍵字選好了"
CUSTOM_KW = re.compile(r"[一-鿿A-Za-z][一-鿿A-Za-z0-9]{0,9}")     # 中文或英文開頭，1–10 字
MAX_KEYWORDS = 12
TODAY_WORDS = {"今日海巡", "今天海巡", "海巡"}


def _intent(d):
    return "buy" if d.get("transaction") == "買" else "rent"


def keyword_card(draft):
    words = PK.KEYWORDS[(_intent(draft), draft["kind"])]
    chosen = set(draft.get("keywords", []))
    buttons = [AP._button(w, AP.data("kw", PURPOSE, str(i)), w in chosen) for i, w in enumerate(words)]
    done = {"type": "button", "style": "primary", "height": "sm", "color": AP.INK,
            "action": {"type": "postback", "label": KW_DONE_TEXT, "data": AP.data("kwdone", PURPOSE)}}
    terms = PK.area_terms(draft.get("areas") or {})
    example = f"{terms[0][0]} {words[0]}" if terms else words[0]
    custom = [w for w in draft.get("keywords", []) if w not in words]
    note = (f"海巡會在 Threads 找「地區＋關鍵字」的貼文，例：{example}。已先勾常用的，點一下選、再點一次取消；"
            "也可以直接打字加自己的關鍵字（例：想買農地）。" + (("\n你加的：" + "、".join(custom)) if custom else ""))
    bubble = AP._bubble("海巡關鍵字（可複選）", note, AP._grid(buttons), [done])
    return {"type": "flex", "altText": "海巡關鍵字（可複選）", "contents": bubble}


def _groups(d):
    return PK.build_groups(d["areas"], [_intent(d)], [d["kind"]], d.get("keywords"))


def question(draft):
    step = draft["step"]
    if step in ("city", "area"):
        return AP.card(draft, PURPOSE)
    if step == "transaction":
        return message("想找購買需求還是承租需求？", ("買", "租", "取消"))
    if step == "kind":
        return message("主要承接哪類不動產？", (*KINDS, "取消"))
    if step == "keywords":
        return keyword_card(draft)
    if step == "time":
        return message("希望每天幾點收到海巡提醒？台灣時間HH:MM。", ("09:00", "12:00", "18:00", "取消"))
    n = len(_groups(draft))
    rotate = f"，超過的逐日輪流（約 {-(-n // PK.DAILY_GROUPS)} 天輪完）" if n > PK.DAILY_GROUPS else ""
    return message(f"服務範圍：{AP.summary(draft['areas'])}\n需求：{draft['transaction']}／{draft['kind']}\n"
                   f"海巡關鍵字：{'、'.join(draft['keywords'])}\n"
                   f"海巡：共 {n} 組（地區×需求），每天最多 {PK.DAILY_GROUPS} 組{rotate}。\n"
                   f"提醒時間：每天{draft['time']}（台灣時間）\n"
                   "保存後每天自動找想買／想租的貼文推給你，也可以隨時打「今日海巡」。只保存你的服務設定，不收買方個資。是否同意保存？",
                   ("同意保存設定", "取消"))


def patrol_messages(profile, day):
    groups = _groups(profile)
    todays = PK.todays_groups(groups, day)
    bubbles = []
    for g in todays:
        links = [(q[:20], PK.threads_url(q)) for q in g.queries()]
        bubbles.append(flex.links_message(f"海巡：{g.label}", ["點了開 Threads 最新貼文；看到想買／想租的人，直接在 Threads 回他。"],
                                          links)["contents"])
    head = message(f"今日海巡：{len(todays)} 組（你共設定 {len(groups)} 組，每天最多 {PK.DAILY_GROUPS} 組輪流）。\n"
                   "目前是給你搜尋連結，由你自己看、自己回；自動找貼文尚未啟用。", ("海巡狀態", "找新買方"))
    return [head, flex.flex_message("今日海巡連結", flex.carousel(bubbles))]


def _with_hint(reply, hint):
    """題目是文字就加前綴；是點選卡就另外加一則提示文字。"""
    if reply.get("type") == "text":
        reply = dict(reply, text=hint + "\n" + reply["text"])
        return [reply]
    return [message(hint), reply]


def _profile_text(profile):
    if not profile:
        return "\n尚未保存服務設定。"
    if "areas" in profile:
        scope = AP.summary(profile["areas"])
    else:                                       # 舊版只存單一縣市與文字區域
        scope = f"{profile.get('city')}／{profile.get('area')}"
    words = "、".join(profile.get("keywords") or []) or "（預設）"
    return f"\n已保存：{scope}\n{profile['transaction']}／{profile['kind']}／每天{profile['time']}\n海巡關鍵字：{words}"


def make_prospect_handler(store, *, now=datetime.datetime.now, patrol_now=None):
    """patrol_now(tenant_id) → (訊息, commit) 或 None（沒接搜尋服務）；commit 要在回覆送出後才呼叫。"""
    def handler(ctx):
        if not ctx.is_owner_dm:
            return
        pb = AP.parse((ctx.event.get("postback") or {}).get("data")) if ctx.event.get("type") == "postback" else None
        if pb and pb.get("p") != PURPOSE:
            return
        text = ctx.text.strip()
        if not pb and not text:
            return
        with store.lock(ctx.tenant_id, "prospect-setup"):
            state = store.read_json(ctx.tenant_id, *STATE, default={}) or {}
            draft = state.get("draft")
            entry = text.casefold() in {"hi", "hello", "你好", "開始", "功能"}
            command = text in {"找新買方", "海巡設定", "海巡狀態", "清除海巡設定"} or (text in TODAY_WORDS and not draft)
            picker_text = text in AP.TEXT_OPS
            if not draft and not entry and not command and not pb and not picker_text:
                return
            eid = ctx.event.get("webhookEventId")
            if eid and eid in state.get("seen", []):
                ctx.reply_text("這則設定操作已處理，請繼續下一題或查看海巡狀態。")
                return
            replies, after_reply = None, None
            if draft and now().timestamp() - draft["started"] > 1800:
                draft = None
                if not (entry or command or pb or picker_text):
                    # 逾時的草稿不能吃掉下一句話（審查：打「新增買方」只回逾時）→ 清掉草稿，交給別的流程
                    state["draft"] = None
                    store.write_json(ctx.tenant_id, *STATE, data=state)
                    return
                replies = [message("設定草稿已逾30分鐘，請重新開始；已保存設定不變。", ("找新買方",))]
            if entry:
                replies = [welcome(bound=True)]
            elif text in {"找新買方", "海巡設定"}:
                customer = store.read_json(ctx.tenant_id, "line", "customer_intake.json", default={}) or {}
                if customer.get("draft") and now().timestamp()-customer["draft"].get("started", 0) <= 1800:
                    replies = [message("你還有客需草稿，請先輸入取消，再選找新買方。")]
                else:
                    draft = {"step": "city", "cities": [], "areas": {}, "started": now().timestamp()}
                    replies = [question(draft)]
            elif text == "海巡狀態":
                how = ("海巡：每天自動找想買／想租的貼文（Threads＋PTT），推在「今日報告」；13:00、19:00 有新的再加報；"
                       "打「今日海巡」也能馬上找。" if patrol_now
                       else "海巡：自動找貼文還沒接上搜尋服務；先用「今日海巡」的 Threads 搜尋連結。")
                replies = [message(how + _profile_text(state.get("profile")), ("今日海巡", "找新買方", "清除海巡設定"))]
            elif text in TODAY_WORDS and not draft:
                profile = state.get("profile") or {}
                if "areas" not in profile or "kind" not in profile:
                    # 圖文選單的「找新買方」第一次點：直接開始設定（只要一次），不用再點別的
                    draft = {"step": "city", "cities": [], "areas": {}, "started": now().timestamp()}
                    replies = [message("先設定一次你的海巡範圍（只要一次）；設定好之後，點「找新買方」就直接給你貼文。"),
                               question(draft)]
                elif patrol_now is not None and (found := patrol_now(ctx.tenant_id)) is not None:
                    msgs, after_reply = found
                    replies = msgs or [message("今日海巡：最近一天沒找到新的想買／想租貼文（看過的不會重複給）。\n"
                                               "明天的今日報告會再找。", ("海巡狀態", "今日報告"))]
                else:
                    replies = patrol_messages(profile, now().date())
            elif text == "清除海巡設定":
                state.pop("profile", None)
                draft = None
                replies = [message("已清除海巡服務設定及草稿；既有買方資料不變。")]
            elif text == "取消" and draft:
                draft = None
                replies = [message("已取消海巡草稿，已保存設定不變。", ("找新買方", "新增買方"))]
            elif draft and (pb or picker_text) and draft["step"] in ("city", "area"):
                op, value = (pb.get("ap"), pb.get("v", "")) if pb else AP.TEXT_OPS[text]
                note, changed, advanced = AP.apply(draft, op, value, (pb or {}).get("k", ""), finished="transaction")
                if advanced:                                    # 換下一張卡或下一題：先確認、再出題
                    replies = ([message(note)] if note else []) + [question(draft)]
                elif note:
                    replies = [message(note, AP.quick(draft))]
                else:
                    replies = [question(draft)] if changed else _with_hint(question(draft), "請點選卡片上的按鈕。")
            elif draft and draft["step"] == "keywords" and ((pb and pb.get("ap") in ("kw", "kwdone")) or text == KW_DONE_TEXT):
                words = PK.KEYWORDS[(_intent(draft), draft["kind"])]
                chosen = draft.setdefault("keywords", [])
                if pb and pb.get("ap") == "kw":
                    idx = pb.get("v", "")
                    if idx.isdigit() and int(idx) < len(words):
                        w = words[int(idx)]
                        draft["keywords"] = [x for x in words if (x in chosen) != (x == w)]
                        replies = [message(("已選：" + "、".join(draft["keywords"])) if draft["keywords"] else "還沒選關鍵字",
                                           (KW_DONE_TEXT, "取消"))]
                    else:
                        replies = _with_hint(question(draft), "請點卡片上的關鍵字。")
                elif not chosen:
                    replies = [message("至少選一個關鍵字。", (KW_DONE_TEXT, "取消"))]
                else:
                    draft["step"] = "time"
                    replies = [message("✓ 海巡關鍵字：" + "、".join(chosen)), question(draft)]
            elif draft and draft["step"] == "keywords" and text and not pb and text != "取消":
                # 負責人 2026-10-02：關鍵字要能自由選、也能自己打。打字＝新增；同一個詞再打一次＝移除
                word = re.sub(r"\s+", "", text)
                chosen = draft.setdefault("keywords", [])
                if word in chosen:
                    chosen.remove(word)
                    note = f"已移除「{word}」。"
                elif not CUSTOM_KW.fullmatch(word):
                    note = "自己加的關鍵字請打 1–10 個字（中文或英文），不要放電話、網址。"
                elif len(chosen) >= MAX_KEYWORDS:
                    note = f"關鍵字最多 {MAX_KEYWORDS} 個，先點掉幾個再加。"
                else:
                    chosen.append(word)
                    note = f"已加入「{word}」。"
                replies = [message(note + "\n已選：" + ("、".join(chosen) or "（還沒選）"), (KW_DONE_TEXT, "取消"))]
            elif draft and pb:
                replies = _with_hint(question(draft), "這一步不是選區域，請照題目回答，或按取消。")
            elif pb and not replies:                            # 舊卡片：設定已完成或已取消
                replies = [message("這張選區域的卡片已經用過了。", ("找新買方", "海巡狀態"))]
            elif draft:
                step = draft["step"]
                valid = False
                if step == "transaction" and text in {"買", "租"}:
                    draft.update(transaction=text, step="kind")
                    valid = True
                elif step == "kind" and text in KINDS:
                    draft.update(kind=text, step="keywords",
                                 keywords=list(PK.default_keywords(_intent(draft), text)))
                    valid = True
                elif step == "time" and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", text):
                    draft.update(time=text, step="confirm")
                    valid = True
                elif step == "confirm" and text == "同意保存設定":
                    state["profile"] = {"cities": draft["cities"], "areas": draft["areas"],
                                        "transaction": draft["transaction"], "kind": draft["kind"],
                                        "keywords": draft["keywords"], "time": draft["time"],
                                        "timezone": "Asia/Taipei", "source_status": "search_links_only",
                                        "monitoring_enabled": False, "consent_at": now().isoformat()}
                    draft = None
                    replies = [message("設定已保存。打「今日海巡」馬上找想買／想租的貼文；每天也會在你設定的時間自動推。"
                                       if patrol_now else "設定已保存。現在可以打「今日海巡」拿 Threads 搜尋連結。",
                                       ("今日海巡", "海巡狀態", "新增買方"))]
                    valid = True
                if draft:
                    replies = [question(draft)] if valid else _with_hint(question(draft), "請依題目選擇，或按取消。")
            if replies:
                state["draft"] = draft
                if eid:
                    state["seen"] = (state.get("seen", [])+[eid])[-1000:]
                store.write_json(ctx.tenant_id, *STATE, data=state)
                if ctx.reply(replies) and after_reply:
                    after_reply()                          # 送到了才把這些貼文記成看過
    return handler
