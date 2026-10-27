"""海巡貼文判斷（純規則、零 I/O）：這篇是不是「在你的地區、真的想買（想租）的人，或真的想賣的屋主」。

負責人 2026-10-02 實測回報：找到跟買房不相關的（感情、政治、股票配息、房價心得）、彰化的、宜蘭租屋的、
同業廣告（一串 #房仲 標籤、成交交屋文）。2026-10-08：「海巡只需要真實的買賣方」。
用一週存下來的候選貼文逐篇複查（負責人電腦裡的資料庫，不進 repo）：留下來的 10 篇只有 1～2 篇是真的買方，
其他是同業刊登文（文末電話、「詳情私訊我」、「品牌｜經紀人」署名）、平台官方帳號的房市新聞、行情文；
反而漏掉「想找一間獨棟農舍…」（沒寫地區）、在別人物件下面問「請問開價」的人。所以改成：
  1. 先擋帳號：媒體、平台、名稱帶 house／realty 的同業帳號。
  2. 作者自己的話（標題）是在問某間物件（請問開價、想了解報價、還在嗎）→ 可能的買方，點進去看他問哪間。
  3. 同業／廣告記號一個就擋（電話、LINE 連結、經紀人、證號、加盟店、「品牌｜」署名、詳情私訊、留言索取資料）。
     屋主自售（寫明屋主自售、不經仲介）例外：那是真的賣方。
  4. 新聞、行情、政策文擋掉（兩個以上新聞字眼，又沒有第一人稱想買）。
  5. 一定要有「明確的想買／想找」講法（想買、在找、求購、預算、哪裡有人在賣、買哪裡好嗎）；
     單純出現「買房」兩個字（標籤、廣告標題、「給想買房的你」）不算。
  6. 屋主自己想賣（我家／老家／繼承的房子想賣、自售）→ 標「屋主想賣（開發機會）」。
  7. 地區：寫了別的縣市就不給；完全沒寫地區、但想買得很明確 → 給，標「沒寫地區，點進去確認」
     （搜尋本來就限定了地區，只是摘要沒帶到）。
寧可漏放、不要亂給（把同業當客戶最傷）。每一篇都回「留／不留」與一句理由，理由記進資料庫，之後拿來調。
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

from core.patrol_keywords import DO_NOT_CONTACT, SELLER_SIGNALS, STRONG_SELLER, county_term, district_term
from core.tw_districts import COUNTIES, DISTRICTS

MAX_AGE = datetime.timedelta(hours=72)            # 負責人：海巡有效時間鎖定 3 天以內

OBJ = r"(房子|房屋|房|屋|透天|公寓|大樓|華廈|別墅|套房|雅房|整層|預售屋?|新成屋|中古屋|社區|土地|農地|建地|地|店面|廠房|辦公室|農舍|平房)"
# 明確想買／想找（不含單純「買房」兩個字）
WANT = r"(想|要|想要|打算|準備|計畫|計劃|預計|考慮|希望|需要|開始|正在|在|還在|一直在|急)"
STRONG_BUY = re.compile(
    WANT + r"\s*(在\S{0,12})?\s*(買|購|購買|找|入手|物色)\s*(一間|一棟|一塊|一個|間|棟|塊|個|適合的|合適的)?\S{0,6}?" + OBJ
    + r"|求購|徵屋|誠徵房子|徵求\S{0,6}" + OBJ
    # 買方問哪裡有人在賣（「請問羅東哪裡有透天要賣的？」）
    + r"|(哪裡|哪邊|哪裏|有沒有|有人|誰|求)\S{0,10}" + OBJ + r"\S{0,4}(要賣|在賣|出售|釋出|賣嗎|可以買|推薦)"
    # 問買哪裡、買哪種好不好（「宜蘭買透天好還是買大樓好？」）
    + r"|(買|購)(一間|間|個)?\s*" + OBJ + r"\S{0,14}?(好還是|還是|好嗎|值得嗎|划算嗎|可以嗎|好不好|\?|？)"
    + r"|預算\S{0,6}\d+\s*(萬|千萬)"
    + r"|(推薦|介紹)\S{0,8}(社區|建案|區域|地段)\S{0,8}(嗎|？|\?)"
    + r"|(自己|我|我們)\S{0,3}看了\S{0,4}(幾|[一二三四五六七八九十\d]+)\S{0,2}(間|個|棟)?(房子|房|物件)|被\S{0,8}(房子|房價)?燒到|也想(買|找)(房|屋)"
    + r"|(第一次|首次)買房|(首購|換屋)\S{0,10}(請益|求助|建議|推薦|該|嗎|？|\?)")
# 「給想買房的你」「想買房的人一定要看」是廣告寫法，不是作者自己要買
AD_TARGET = re.compile(r"(想|要|準備)(在\S{0,8})?(買|找)\S{0,3}(房|屋)\S{0,2}的(你|妳|人|朋友|族|大家)|給(想|要)(買|找)"
                       r"|如果(你|妳|您)\S{0,6}(想|有|也)\S{0,30}")
# 2026-10-18 複查（竹北找租客）：「還是先繼續租屋吧」「每月租金設多少適合」「有細單位出租」都被當成想租 →
# 要有明確在找的講法；單純出現租屋、租金、月租不算
RENT_INTENT = re.compile(
    r"(想|要|打算|準備|需要|在找|想找|急|徵|求|誠心求)\s*(在\S{0,12})?\s*(租|承租)\s*" + OBJ + r"?"
    r"|求租|徵租|找租|租屋需求|租屋條件|想找\S{0,12}(租|套房|整層|雅房)|(有沒有|有無)\S{0,12}(出租|要租|可以租)"
    r"|(有沒有|有無)\S{0,16}(以內|以下)|預算\S{0,10}\d|預計\S{0,4}入住|入住時間")
RENT_CONTEXT = re.compile(r"租|套房|雅房|整層|房一廳|房兩廳")
HOUSING = re.compile(OBJ + r"|坪|房價|房貸|頭期|房租|住處")
# 已經買好的（「我們也在宜蘭買房了～希望某某早日找到合適的房子」是留言，不是買方）
DONE_BUYING = re.compile(r"買房了|買了房|已經買|剛買|交屋了|入厝|搬新家了")
WANT_TO = re.compile(WANT + r"\s*(在\S{0,12})?\s*(買|找)")
REPLY_TO_SEEKER = re.compile(r"早日找到|找到合適|找到喜歡|祝\S{0,6}找到|找房加油")
# 屋主自己想賣（開發機會）
OWNER_SELL = re.compile(
    r"(我|我家|我們家|家裡|自家|爸媽|父母|阿公|阿嬤|老家|繼承)\S{0,14}" + OBJ + r"\S{0,10}(想賣|要賣|賣掉|出售|脫手|處理掉)"
    + r"|" + WANT + r"\s*把\S{0,12}" + OBJ + r"\S{0,4}(賣掉|賣了|出售|脫手)"
    + r"|(我|我們|我家|家裡|自己|本人)\S{0,4}(想|要|打算|準備|考慮|想要)\s*(賣|出售)\s*(掉)?\S{0,6}" + OBJ
    + r"|房子賣不掉|賣房(該|要)?(注意|找誰|怎麼|流程)|屋主自售|自售|屋主直售")
FSBO = re.compile(r"屋主自售|自售|屋主直售|免仲介費")
ASKS_FOR_AGENT = re.compile(r"(推薦|介紹|找|有沒有|認識)\S{0,6}(房仲|仲介)|(房仲|仲介)\S{0,6}(推薦|介紹)")
ASKING = re.compile(r"嗎|？|\?|請問|推薦|求|有沒有|有人|建議|哪裡|哪一區|怎麼|該不該|好嗎|適合")
# 在別人的物件貼文底下問價（作者自己的話很短、是問句、沒有價格坪數）
INQUIRY = re.compile(r"請問|想問|想了解|想詢問|詢問|還在嗎|還有嗎|可以看|能看|怎麼賣|多少錢|開價多少|報價|詳細資訊|詳細資料|"
                     r"可以私訊|私訊你|地址在|在哪裡")
AGENT_STORY = ("交屋", "成交", "促成", "陪著買方", "陪買方", "買方", "賣方", "屋主委託", "帶看", "斡旋", "簽約",
               "服務過", "幫客戶", "我的客戶", "物件推薦", "歡迎私訊", "歡迎來電", "房仲日常")
HASHTAG = re.compile(r"#\S")
NOT_SELLER = re.compile(r"(房仲|仲介)\s*(勿擾|免|不要|勿)|不要(房仲|仲介)|請(房仲|仲介)")
PHONE = re.compile(r"(?<!\d)(09\d{2}[-\s]?\d{3}[-\s]?\d{3}|0\d{1,2}-\d{6,8})(?!\d)")
# 同業／廣告記號：一個就算（2026-10-08 複查：刊登文多半文末附電話、LINE、「品牌｜經紀人」署名、「詳情私訊我」）
AGENT_MARK = re.compile(
    r"line\.me|lin\.ee|加\s*line|加賴|加LINE|經紀人|營業員|證號|經紀業|加盟店|直營店|不動產(有限|經紀|仲介)|房屋仲介|"
    r"(房屋|不動產|地產)\s*[｜|]|詳情私訊|私訊我|歡迎私訊|留言\S{0,8}(資料|傳給|發給|給你|給您)|賞屋|看屋專線|預約看屋|"
    r"買屋賣屋|買房賣房|賣屋買屋|一通電話|交給我|我幫你(找|賣)|為您(挑選|服務)|您好，我是|服務專線|開價\s*\d|售價\s*\d|"
    r"總價\s*\d|只開\s*\d|\d+(\.\d+)?\s*萬\s*[/／]\s*坪|單價\s*\d|"
    r"我是\S{0,10}(房仲|仲介|經紀人|業務)|做房仲|當房仲|房仲第\S{1,3}年|身為房仲|加我\s*line|line\s*id|"
    r"陪你\S{0,4}(找房|看房)|帶你看房|"
    r"接到\S{0,8}委託|有買方(想|在|要)|我的買方|客戶(想|在|要)找|幫客戶找|替客戶找", re.I)
# 帳號：媒體、平台、名字就寫明是賣房的
MEDIA_HANDLE = re.compile(r"official|news|media|magazine|press|(^|[._])tv([._]|$)", re.I)
PLATFORM_HANDLE = re.compile(r"rakuya|housefun|591|sinyi|hbhousing|twhg|cthouse|etwarm|century21|myhousing|"
                             r"ettoday|udn|ltn|setn|tvbs|ctwant|businesstoday|storm|cnyes|moneydj|meta\.ai", re.I)
AGENT_HANDLE = re.compile(r"house|realt|estate|property|broker|fangchan|dichan|budongchan", re.I)
NEWS_WORDS = ("政見", "候選人", "參選", "議員", "立委", "縣長", "市長", "選舉", "申報", "所得稅", "遺產稅", "稅率",
              "制度", "央行", "專家", "鬆綁", "管制", "房市", "建商", "政策", "利率", "記者", "報導", "槓桿", "打房",
              "降息", "升息", "房價指數", "央行理監事", "限貸", "成交量", "實價登錄", "均價", "快訊", "題材",
              "受惠", "趨勢", "預售", "漲幅", "行情", "內政部", "統計", "季度", "Q1", "Q2", "Q3", "Q4")
FIRST_PERSON = re.compile(r"(我|我們|本人|小弟|小妹|我家|家裡)\S{0,6}" + WANT + r"?\s*(買|找|看|賣|租)")


def _area_terms():
    out = {}
    for county in COUNTIES:
        terms = {county_term(county), county}
        terms |= {district_term(county, d) for d in DISTRICTS[county]}
        out[county] = {t for t in terms if len(t) >= 2}
    return out


AREA_TERMS = _area_terms()
# 同名的鄉鎮（大同、信義、中山…）會出現在不只一個縣市；用來排除「別的縣市」時不算數
_SHARED = {t for t in set().union(*AREA_TERMS.values()) if sum(t in v for v in AREA_TERMS.values()) > 1}


@dataclass(frozen=True)
class Verdict:
    keep: bool
    reason: str


# 「如果不想買房…」「沒打算買房」是反話，不是想買（2026-10-15 夜間複查）
NOT_WANT = re.compile(r"(不|沒|沒有|別|不用)\s*(想要?|要|打算|準備|考慮)\s*(在\S{0,12})?\s*(買|購|找)"
                      # 以前想買（「30 多年前我本想在某路買房」是回憶，不是現在要買）
                      r"|(年前|以前|當年|當初|那時候?|曾經)\S{0,10}(本想|本來想|想|要|打算)\s*(在\S{0,12})?\s*(買|購|找|租)")
# 搜尋摘要常夾著別的帳號（「某某's profile picture · 某某租屋公司 (@帳號)」），那段不是作者的話，不拿來判斷地區
PROFILE_REF = re.compile(r"\S+'s profile picture\s*·\s*[^()]{0,40}\(@[\w.]+\)")
# 政見、補助、選舉文：留言串裡的「第一次買房」多半是這種（2026-10-15 夜間複查）
POLITICS = ("補助", "候選人", "政見", "參選", "議員", "縣長", "市長", "立委", "選民", "選戰")


def _wants_to_buy(text: str) -> bool:
    return bool(STRONG_BUY.search(NOT_WANT.sub(" ", AD_TARGET.sub(" ", text))))


def _owner_selling(text: str) -> bool:
    return bool(OWNER_SELL.search(text))


def _inquiry(own: str) -> bool:
    """作者自己的話是在問一間物件：短、是問句或詢問、沒有價格坪數（有價格的是刊登文的標題）。"""
    own = (own or "").strip()
    if not own or len(own) > 40 or re.search(r"\d+\s*(萬|坪)|[｜|]|#|預約|請勿|禁|line|👇|出租|招租", own, re.I):
        return False
    return bool(INQUIRY.search(own)) and not AGENT_MARK.search(own) and not PHONE.search(own)


def judge(text: str, *, county: str, area_term: str, intent: str, posted_at: datetime.datetime | None,
          now: datetime.datetime, handle: str | None = None, own: str | None = None) -> Verdict:
    """intent：buy／rent／sell。posted_at 解不出來就不給（無法確認在 3 天內）。
    handle：發文帳號；own：作者自己的話（搜尋結果的標題，摘要常混著原貼文或相關貼文）。"""
    text = PROFILE_REF.sub(" ", text)
    if posted_at is None:
        return Verdict(False, "看不出發文時間")
    if now - posted_at > MAX_AGE:
        return Verdict(False, "超過 3 天")
    if now - posted_at < -datetime.timedelta(hours=1):
        return Verdict(False, "發文時間異常")
    if any(w in text for w in DO_NOT_CONTACT) and not FSBO.search(text):
        return Verdict(False, "對方寫了勿擾")
    if handle and MEDIA_HANDLE.search(handle):
        return Verdict(False, "媒體／官方帳號")
    if handle and PLATFORM_HANDLE.search(handle):
        return Verdict(False, "房屋平台／媒體帳號")
    if handle and AGENT_HANDLE.search(handle):
        return Verdict(False, "帳號名稱是賣房的（同業）")
    mine = AREA_TERMS[county] if area_term in (county_term(county), county) else {area_term}
    others = [c for c, terms in AREA_TERMS.items() if c != county and any(t in text for t in terms - _SHARED)]
    in_area = any(t in text for t in mine)
    # 在別人物件底下問價：看作者自己的話（標題），摘要裡的刊登內容是別人的
    news = sum(1 for w in NEWS_WORDS if w in text) >= 2 and not FIRST_PERSON.search(text)
    if intent in ("buy", "rent") and _inquiry(own or "") and not _wants_to_buy(own or "") \
            and len(HASHTAG.findall(text)) < 3 and not news:
        if not in_area:
            return Verdict(False, f"問的是{county_term(others[0])}的物件" if others else "看不出問的是哪裡的物件")
        return Verdict(True, "在問一間物件，可能是買方（點進去看他問哪間）")
    cleaned = NOT_SELLER.sub("", text)
    seller = _owner_selling(cleaned)
    fsbo = bool(FSBO.search(cleaned))
    if len(HASHTAG.findall(text)) >= 3:
        return Verdict(False, "一串標籤，多半是同業廣告")
    if AGENT_MARK.search(cleaned) and not (fsbo and not re.search(r"經紀人|營業員|證號|加盟店|直營店", cleaned)):
        return Verdict(False, "同業刊登或廣告（有電話、LINE、經紀人署名等）")
    if PHONE.search(cleaned) and not fsbo:
        return Verdict(False, "同業刊登或廣告（有電話、LINE、經紀人署名等）")
    if any(w in cleaned for w in STRONG_SELLER):
        return Verdict(False, "同業／廣告用語")
    if sum(1 for w in AGENT_STORY if w in cleaned) >= 2:
        return Verdict(False, "像同業的文")
    if not HOUSING.search(text):
        return Verdict(False, "跟房子無關")
    buy = _wants_to_buy(cleaned)
    rent = bool(RENT_INTENT.search(NOT_WANT.sub(" ", cleaned))) and bool(RENT_CONTEXT.search(cleaned))
    if sum(1 for w in NEWS_WORDS if w in text) >= 2 and not FIRST_PERSON.search(text):
        return Verdict(False, "新聞／行情文，不是買賣方")
    if others and not in_area:
        return Verdict(False, f"講的是{county_term(others[0])}")
    if DONE_BUYING.search(text) and not WANT_TO.search(text) and not buy:
        # 已經買好的人（多半是留言）；但留言在祝福別人找房 → 原文那個人才是買方，點進去看
        if REPLY_TO_SEEKER.search(text) and in_area:
            return Verdict(True, "留言提到有人在找房（點進去看原文）")
        return Verdict(False, "已經買好了，不是買方")
    # 屋主自己想賣 → 開發機會（不管這組是找買方還是找屋主）
    if seller and not buy:
        if not in_area:
            return Verdict(False, "屋主想賣，但看不出在哪裡")
        return Verdict(True, "屋主想賣（開發機會）" + ("，在找房仲" if ASKS_FOR_AGENT.search(text) else ""))
    if intent == "sell":
        return Verdict(False, "看不出是屋主要賣")
    if intent == "buy" and not buy:
        return Verdict(False, "找租屋，不是買房" if rent else "看不出真的要買房")
    if intent == "rent" and not rent:
        return Verdict(False, "要買房，不是找租屋" if buy else "看不出要租房")
    if sum(1 for w in SELLER_SIGNALS if w in cleaned) >= 3:
        return Verdict(False, "像刊登文（出售、開價、委託…）")
    label = "想" + ("買" if intent == "buy" else "租") + ("，在問推薦" if ASKING.search(text) else "")
    o = (own or "").strip()
    if intent == "buy" and o and len(o) <= 30 and not _wants_to_buy(o) and not ASKING.search(o):
        # 標題是回覆的人說的話，想買的是原貼文的人；證據最弱，摘要夾著新聞、政見就不給
        if any(w in text for w in NEWS_WORDS + POLITICS):
            return Verdict(False, "留言串，摘要是新聞或政見，看不出有人要買")
        label = "這串留言裡有人在找房（點進去看原文）"
    if not in_area:
        return Verdict(True, label + "（沒寫地區，點進去確認）")
    return Verdict(True, label)
