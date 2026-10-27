"""仲介的基本資料：品牌、要不要看到自己品牌的物件、分享給客人時的署名。

負責人 2026-10-01：先確認仲介的品牌，找房連結與海巡就能避開他自己品牌（自家物件他本來就熟）；
他要自己品牌的也可以選。署名是仲介自己的資料，分享給客人時附在最後，沒填就不附（不會補上別人的資料）。
"""
import datetime
import re

from adapters.line import drafts
from adapters.line.customer_intake import message

STATE = ("line", "agent_profile.json")
# 清單外的品牌（含加盟體系）選「其他」自己打，存在租戶資料裡
BRANDS = ("信義房屋", "住商不動產", "中信房屋", "東森房屋", "台灣房屋", "21世紀不動產", "太平洋房屋",
          "群義房屋", "大家房屋", "春耕不動產")
OTHER, SOLO = "其他（自己打）", "自營／個人工作室"
INCLUDE, EXCLUDE = "我的品牌也要", "避開我的品牌"
SKIP = "略過"
START_WORDS = {"我的資料", "設定我的資料", "修改我的資料", "我的品牌", "設定品牌"}


def load(store, tenant_id: str) -> dict:
    return (store.read_json(tenant_id, *STATE, default={}) or {}).get("profile") or {}


def describe(profile: dict) -> str:
    if not profile:
        return "還沒設定。"
    own = "—" if not profile.get("brand") else ("要" if profile.get("include_own_brand") else "避開")
    return (f"品牌：{profile.get('brand') or '自營／個人'}\n自己品牌的物件：{own}\n"
            f"分享署名：{profile.get('signature') or '（不附）'}")


def question(draft: dict) -> dict:
    step = draft["step"]
    if step == "brand":
        return message("你在哪個品牌？（找房連結與海巡會先避開你自己品牌的物件）", (*BRANDS, SOLO, OTHER, "取消"))
    if step == "brand_text":
        return message("請打你的品牌名稱（例：XX房屋）。", ("取消",))
    if step == "own":
        return message(f"你自己品牌（{draft['brand']}）的物件要不要也列給你？\n自家物件通常你都熟，預設避開。",
                       (EXCLUDE, INCLUDE, "取消"))
    return message("分享物件給客人時，最後要附的署名？例：林小姐｜XX房屋 中山店\n"
                   "要不要附電話你自己決定；不想附就按略過。", (SKIP, "取消"))


def _text(value: str, limit: int) -> str:
    t = value.strip()
    if not t or len(t) > limit or any(ord(c) < 32 and c != "\n" for c in t):
        raise ValueError(f"最多 {limit} 個字，請重打。")
    return t


def make_profile_handler(store, *, now=datetime.datetime.now):
    def handler(ctx):
        if not ctx.is_owner_dm or not ctx.text:
            return
        text = ctx.text
        with store.lock(ctx.tenant_id, "agent-profile"):
            state = store.read_json(ctx.tenant_id, *STATE, default={}) or {}
            draft = state.get("draft")
            if draft and now().timestamp() - draft.get("started", 0) > drafts.TTL:
                draft = None
            if not draft and text not in START_WORDS:
                return
            eid = ctx.event.get("webhookEventId")
            if eid and eid in state.get("seen", []):
                ctx.reply_text("這則已處理。")
                return
            replies = None
            if text == "取消" and draft:
                draft = None
                replies = [message("已取消，原本的資料不變。\n" + describe(state.get("profile") or {}))]
            elif text in START_WORDS:
                other = drafts.busy(store, ctx.tenant_id, now().timestamp(), exclude="profile")
                if other:
                    replies = [message(f"你還有{other}沒完成，請先完成或輸入取消。")]
                elif text in {"我的資料", "我的品牌"} and state.get("profile") and not draft:
                    replies = [message("你的資料：\n" + describe(state["profile"]), ("修改我的資料", "隱私說明"))]
                else:
                    draft = {"step": "brand", "started": now().timestamp()}
                    replies = [question(draft)]
            else:
                step = draft["step"]
                try:
                    if step == "brand":
                        if text == OTHER:
                            draft["step"] = "brand_text"
                        elif text == SOLO:
                            draft.update(brand=None, include_own_brand=True, step="signature")
                        elif text in BRANDS:
                            draft.update(brand=text, step="own")
                        else:
                            raise ValueError("請點下面的品牌；清單沒有的按「其他」。")
                    elif step == "brand_text":
                        name = _text(text, 20)
                        if re.search(r"\d{6,}|@", name):
                            raise ValueError("品牌名稱不要放電話或 email。")
                        draft.update(brand=name, step="own")
                    elif step == "own":
                        if text not in (INCLUDE, EXCLUDE):
                            raise ValueError("請選要或避開。")
                        draft.update(include_own_brand=(text == INCLUDE), step="signature")
                    else:
                        signature = None if text == SKIP else _text(text, 60)
                        state["profile"] = {"brand": draft.get("brand"),
                                            "include_own_brand": bool(draft.get("include_own_brand")),
                                            "signature": signature, "updated_at": now().isoformat(timespec="seconds")}
                        draft = None
                        replies = [message("✓ 已保存。\n" + describe(state["profile"]),
                                           ("新增物件", "新增買方", "客戶清單", "修改我的資料"))]
                    if draft:
                        replies = [question(draft)]
                except ValueError as e:
                    replies = [message(str(e)), question(draft)]
            state["draft"] = draft
            if eid:
                state["seen"] = (state.get("seen", []) + [eid])[-500:]
            store.write_json(ctx.tenant_id, *STATE, data=state)
            ctx.reply(replies)
    return handler
