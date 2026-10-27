---
name: listing-need-matching
description: Use when a real-estate agent provides one or more property records and a buyer/renter need card and asks which listings fit, how to rank them, why a listing was excluded, or which listing should be shown first. Trigger on 配對客需、哪些案子適合、幫我排物件、這批新案配給客戶. Requires supplied listing data; live listing search, inventory refresh, and message delivery belong to a future MCP/tool layer.
---

# 客需 × 物件排序

## SOP

1. Validate that each listing has a stable id, transaction type, price/rent, area, and source timestamp or mark missing.
2. Validate the need card and separate hard constraints from soft preferences.
3. **需求健檢**（見「需求品質旗標」）：先看這張需求卡夠不夠配。沒區域、太空泛、身分對不上的卡不進自動推播池，只產「需求待補」清單。
4. Apply hard filters first: transaction, county/district (including the **exclude list**), budget ceiling, property type, rooms, parking, and explicit exclusions.
5. Score survivors by soft-fit (continuous, not yes/no), freshness, completeness, and evidence quality; show the reason for every score.
6. Rank by score; the top N shown or pushed must be the top N by score, not the order rows were loaded.
7. Put borderline cases (over budget, building inferred from a nickname, missing fields) in a separate review bucket rather than silently including them.
8. Return a review queue. A future tool may turn approved rows into messages, but this Skill never sends them.

## Decision points

- A missing value is not a match and not an automatic fail; label it `需補資料`.
- A budget tolerance such as 10% is usable only when the user or policy explicitly supplies it.
- Do not treat a listing title as proof of rooms, legal use, parking, or floor.
- If two listings tie, prefer higher evidence completeness and newer supplied timestamp, not a fabricated preference.
- If a listing URL is absent, it can be reviewed but cannot be marked ready-to-send.
- A future matching tool must receive tenant scope, filters, and a rate limit; the Skill only defines the request contract.

### 常見錯配（實際配對系統踩過的錯，已改寫成通用規則）

> 原則：**錯配比漏配貴**。推錯東西傷客戶關係，比沒推更難補。

1. **「不要 X」被讀成「只要 X」**：「不要東區」「X 不考慮」「X 可能不太行」「除了 X 都可以」「X 太遠」→ X 進**排除清單**，配對時硬濾掉，X 永遠不能出現在首選。
   - 排除清單一定要真的交給配對步驟；只解析出來、沒傳進去＝沒排除。
   - 切句要涵蓋逗號、頓號、全形直線「｜」、斜線、換行；少一種符號，一個否定詞就會把整串區域一起刪掉，結果變成全縣亂推。
   - 「非常」「嫌惡設施」不是否定詞。
2. **超預算的排第一名**：自住客的價格分不能設計成「越接近上限越高」再加容忍值，否則略超預算的物件會被行銷標籤推到第一。
   - 超過上限的一律排在預算內物件之後，並放進「可補件後審核」，不放「可優先審核」。
   - 自動推播只用嚴格上限；容忍值（例如 5%）只給業務手動查詢用，而且要使用者或政策明確給。
   - 理由要寫「838 萬（略超 38 萬）」，不能寫「838≤800」這種會讓人以為在預算內的字串。
3. **只有「符合／不符合」的二元給分**：要 3 房時 3 房和 8 房同分、要 30 坪時 31 坪和 120 坪同分，硬條件過了就分不出好壞，名次最後由「強打、降價、熱銷」這類行銷標籤決定。
   - 改連續分：離需求越遠分越低，房數、坪數過大也要扣。
   - 行銷標籤只當小加分或同分決勝；「降價」只算這次真的降價，不算一直掛著的舊降價欄位。
   - 缺欄位給中性分並在理由標「資料不全」，不要讓「別人有沒有認真填資料」決定排序。
4. **沒設區域＝全縣（甚至外縣市）亂推**：沒有區域的需求**不進自動推播池**，回「需求不足，先補區域」。縣市是硬閘：客戶沒說可以跨縣市，就不推外縣市物件。業務自己看的報表可以照列全縣，客戶收到的不行。
5. **其他同類錯誤**（逐條擋）：
   - 型態是聯集：客戶同時要店面和透天，兩種都配；「店面」不能吃掉其他型態。「不要農地」不等於「要找地」。
   - 只配買方／租客的需求；屋主、同業、內部群一律不進買方配對。
   - 客戶明講要車位、物件明確無車位 → 淘汰；車位欄位空白 →「需補資料」，不要誤殺。
   - 租賃用月租排序，買賣用總價排序；兩種混在同一批時分組排，單位不同不能混排。
   - 「已推過」紀錄要用非空的客戶代碼當鍵；鍵是空的就不推，否則多位客戶會共用同一份紀錄、互相把物件擋掉。
   - 先濾掉沒有連結的，再取前 N 件；不要先砍名額才發現剩下的都不能送。

### 需求品質旗標（配對前健檢）

| 旗標 | 條件 | 會出什麼事 | 請業務補 |
|---|---|---|---|
| `noBudget` 沒預算 | 買／租需求沒有可用的預算上限 | 價格不卡，什麼價位都推 | 補預算（買賣「萬」、租屋「元／月」） |
| `vague` 太空泛 | 買方沒預算、也沒類型 | 只會推到行銷件，不精準 | 補預算＋類型 |
| `noDistrict` 沒區域 | 沒有任何區域 | 不進自動推播（見上面第 4 條） | 補區域 |
| `weakTop` 最佳一件分數偏低 | 第一名分數低於租戶設定的門檻 | 勉強符合，推出去像亂推 | 問客戶能不能放寬哪一條 |
| `noMatch` 零件 | 0 件符合，而且不是因為需求不足被跳過 | 客戶一直收不到東西 | 需求太窄或庫存沒貨，二選一說清楚 |
| `idMismatch` 身分對不上 | 需求卡的客戶代碼和對話鍵對不起來，或一個名字對到兩張卡 | 把別人的需求套到這位客戶身上 | 先對正代碼；對正前這張卡不配 |

- 身分一律用客戶代碼／對話鍵比，不用暱稱或名字。名字對到、代碼衝突 → 不套用，記警告。
- 健檢報告只列有旗標的需求，分「要業務補的」和「系統自己對正的」兩類；沒有旗標就寫「今天需求都健康」。

### 建案暱稱（社區別名）的四道防線

客戶和物件標題常用建案暱稱。暱稱字典由租戶維護（可從內政部實價登錄公開資料的建案名稱起步，再加租戶自己查證的口語別名），程式裡不寫死任何建案名。

- **客戶主動打出暱稱查詢**：意圖明確，可以用全部別名（含短名）；字典裡有這個案但沒有成交紀錄，要回「有此案，目前沒有成交紀錄」，不要回「查無」。
- **從物件標題自動掛建案**（弱訊號）：寧可不命中，不可假命中，四道防線都要過：
  1. **只用夠長的全名型別名**（預設 4 個字以上）。短名常常是一般詞（樹名、路名）；另有人工黑名單擋已證實會撞的詞。
  2. **最長的先比**：「{建案A}2」要贏「{建案A}」，解決同名前綴的系列案。
  3. **候選建案要有行政區資料**：只有名字、沒有區的空殼紀錄不能命中。假命中回一筆空資料，比不命中更糟。
  4. **行政區要相符，數字要看後面接什麼**：名字後面的數字如果接「房、廳、衛、坪、樓」，那是房數／坪數，不是期別（「{建案A}2房」≠「{建案A}2」）。
- 比對前去掉半形／全形空格；含造字（打不出來的字）的別名跳過。
- 由暱稱推定的建案只能當參考，理由寫「建案由別名推定」，放審核區，不能當硬條件的證據。
- 對客戶顯示起造人時，自然人起造（自地自建）一律顯示「個人起造」，不顯示姓名。

## Checklist

- [ ] Need card version/date is known.
- [ ] 需求健檢已跑；有 `noDistrict`／`vague`／`idMismatch` 的卡沒有進自動推播池。
- [ ] 排除清單已交給配對步驟；被排除的區域沒有出現在任何結果裡。
- [ ] 超預算物件沒有排在預算內物件前面；理由寫「略超 n 萬」。
- [ ] 分數是連續分；行銷標籤只當小加分或同分決勝。
- [ ] 由建案暱稱推定的物件已過四道防線，並放在審核區。
- [ ] Hard filters are applied before scoring.
- [ ] Every exclusion has a reason.
- [ ] Missing fields are visible.
- [ ] Score is explainable, not a black-box number.
- [ ] Ready-to-send requires a supplied, valid link.
- [ ] No fresh inventory or external search is implied.

## Template

```text
需求健檢：{客戶代碼}｜{旗標，或「健康」}｜請補：{…}

配對結果
1. 優先看：{listing_id} — {fit_summary}
   - 符合：
   - 仍需確認：
   - 證據完整度：高／中／低
2. 候選：...

可補件後審核
- {listing_id}: {略超 n 萬／建案由別名推定／車位資料空白…}

淘汰／暫緩
- {listing_id}: {explicit reason，例如「客戶排除 {區}」「外縣市」}

審核前問題：
- ...
外部動作：尚未發送；若要查新案、讀租戶庫存或推播，需 MCP/tool layer。
```

## Output requirements

Return the `需求健檢` line first, then three buckets: `可優先審核`, `可補件後審核`, `不符合/淘汰`. Include a compact scoring explanation and never hide a hard-constraint miss. If there are zero valid survivors, say so plainly and identify the constraint causing the empty set. A need card with `noDistrict`, `vague`, or `idMismatch` gets the health-check line and the questions only — no ready-to-send rows.

## Test cases

**T1 — three listings:** one fits all hard fields, one is 12% over a stated 10% tolerance, one lacks a URL. Expected: first in priority; second excluded for budget; third in review, not ready-to-send.

**T2 — missing evidence:** a title says「平車」but structured parking is blank. Expected: parking is `需補資料`, never a confirmed match.

**T3 — no result:** all supplied listings are rentals while the need card is buy. Expected: empty valid set and a request for buy-side inventory/tool refresh.

**T4 — 排除語意＋沒區域：** 客戶 B01 的需求「全市都可以，但不要東區、北區可能不太行」，預算 1,200 萬；物件有東區、北區、西區各一件，都在預算內。客戶 B02 只寫「想買房」，沒有區域、預算、類型。期望：B01 只剩西區那件，東區、北區淘汰並寫「客戶排除 {區}」；B02 不配對，健檢旗標 `noBudget`、`vague`、`noDistrict`，回「需求不足，先補區域、預算、類型」。

**T5 — 超預算與連續分：** 上限 800 萬（自動推播）；物件 P1 820 萬掛「強打」、P2 790 萬 3 房、P3 760 萬 8 房，客戶要 3 房。期望：P1 不在 `可優先審核`，放 `可補件後審核` 並寫「820 萬（略超 20 萬）」；P2 排在 P3 前面（P3 房數超出太多被扣分）；強打標籤沒有讓 P1 排到第一。

**T6 — 建案暱稱防線：** 字典有「{建案A}」「{建案A}2」（都在 {河濱區}）和一筆沒有行政區的空殼「{建案B}」。物件標題：①「{河濱區} {建案A}2房景觀華廈」②「{建案A}2 高樓層」但物件在 {山腳區} ③「{建案B} 新成屋」。期望：①命中「{建案A}」不是「{建案A}2」（2 後面接「房」）；②行政區不符，不命中；③空殼不命中；命中的那件理由寫「建案由別名推定」並放審核區。

## Acceptance criteria

- Same input yields the same bucket and reasons.
- Hard constraints cannot be overridden by a high soft score.
- An excluded district never appears in any bucket except `不符合/淘汰`; an over-budget listing never ranks above an in-budget one.
- A need card without a district never produces ready-to-send rows.
- A building inferred from a nickname is always labeled and never used as hard-constraint evidence.
- Every recommendation cites supplied fields.
- External search, CRM access, and sending are clearly deferred.
