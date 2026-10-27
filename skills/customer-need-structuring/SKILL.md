---
name: customer-need-structuring
description: Use when a real-estate agent pastes a buyer or renter conversation and wants it turned into a reviewable need card, including budget, area, property type, hard constraints, preferences, timing, exclusions, uncertainty, and missing follow-up questions. Trigger on phrases such as 整理客需、幫我看客人要什麼、做需求卡、這個客人適合找什麼房. Do not use it to contact the customer or write to a CRM.
---

# 客戶對話 → 客需卡

## SOP

1. Separate customer statements from agent interpretation and unknowns.
2. Normalize only what the conversation explicitly supports: area, buy/rent, budget, property type, rooms, size, floor, age, parking, timing, and exclusions.
3. Label each field as `hard`, `soft`, `unknown`, or `conflicting`; preserve the customer's wording beside normalized values.
4. Detect whether budget is total price, monthly rent, or unclear. Never convert units without evidence.
5. Produce a concise need card (the 10-field sheet below), a confidence note, and the smallest set of questions that would change matching.
6. 需要客戶本人確認時，產出「客戶自己確認需求」卡片草稿（見下方），交給租戶審核後才可送出。
7. 記下「最後確認日」；超過 30 天沒確認的卡標「待更新」。
8. Mark any CRM write, customer message, group lookup, or calendar action as a future tool call.

## Decision points

- If buy/rent is missing, do not infer from words like「看房」.
- If a range and a ceiling conflict, keep both and ask which is authoritative.
- Treat「最好」「希望」「有就好」as soft unless the customer clearly says it is non-negotiable.
- Relative time such as「明年」「最近」stays relative unless a date is supplied.
- A named building or neighborhood is a candidate alias, not a verified location.
- If the conversation contains multiple people, keep separate cards unless the user confirms they are one household.

## 實戰鐵則（實際配對系統踩過的錯，已改寫成通用規則）

1. **單位**：買賣預算用「萬」、租屋用「元／月」。換算出來月租超過 10 萬、或買賣總價不到 10 萬，幾乎都是誤判 → 標 `conflicting` 並發問，不要照填。
2. **預算只從「預算語境」取數字**：只採「預算、總價、以內、以下、上限、最多、現金、出價」前後的數字。下列數字**不是預算**：
   - 前面有 0 的編號（例：`/001432`、`000658`）
   - 年份（2025、民國 115 年）、日期
   - 「坪」前面的數字（那是坪數）、「單坪」的價格（那是每坪單價，不是總價）
   - 業務或我們貼的物件價格、網址裡的數字
   不要用「全文最大的數字」當預算。取不到就留空。
3. **我們自己說的話不是客戶需求**：介紹、推播文案、物件網址、「幫您推送各類物件（含店面、套房…）」這種句子整句跳過。
4. **排除語意要反過來**：「X 太遠」「X 不考慮」「X 不太行」「不要 X」「除了 X 都可以」→ X 進**排除**，不能出現在首選或可接受。
   - 「非常」「嫌惡設施」不是否定詞。
   - 排除的區域要和首選分開輸出，交給配對時才濾得掉。
5. **型態是聯集不是互斥**：同時提到店面和透天，兩個都列；「不要農地」「非農地（只要農舍）」不是「要找地」。
6. **範圍取下限**：「3~4 房」→ 房數至少 3（不是 34）；「2 房以上 4 房以下」→ 2–4。房數超過 10、坪數帶小數被咬斷（43.578 坪≠578 坪）都要回頭檢查。
7. **方向不要反**：「屋齡 30 年以上」是**下限**不是上限；「我沒要租」「我要買」跟交易別矛盾時，不要硬猜，列衝突。
8. **不確定就留空**：每一欄附原句引文與信心（高／中／低）；沒有原句支持的欄位一律空白，不臆測。
9. **仲介親自填的欄位最優先**：仲介手填 > 本次對話 > 舊紀錄。三者衝突時列成清單讓仲介裁決，不要靜默選一個。

## 10 欄位需求單（配對前要齊）

| # | 欄位 | 怎麼填 |
|---|---|---|
| 1 | 交易型態 | 買／租；沒說就是 `unknown`，不從「看房」推 |
| 2 | 目標總價（定錨） | 客戶想落在附近的價格；「大概、左右、約」通常是這一欄，屬 `soft` |
| 3 | 可接受上限 | 再高就不看；「以內、最多、上限、不要超過」通常是這一欄，屬 `hard`。配對用上限當硬條件、目標總價用來排序 |
| 4 | 區域 | 鄉鎮市區、商圈、地標；首選／可接受／**排除**分開列 |
| 5 | 屋型 | 公寓、華廈、大樓、透天、店面、土地…可多選（聯集） |
| 6 | 坪數 | 註明是權狀坪、室內坪還是土地坪；範圍取下限 |
| 7 | 用途 | 自住、退休、投資、開店… |
| 8 | 特殊條件與地雷 | 不能接受的事，例如不要死巷、不收持分、要完整權狀、只付現不貸款；地雷一律當 `hard` 排除條件 |
| 9 | 客戶背景 | 只記客戶自己說、而且跟找房有關的（首購或換屋、幾個人住、通勤地點）；不記職業收入、身分證件、家人姓名這類配對用不到的個資 |
| 10 | 看屋時段 | 平日／週末／晚上；有具體時間就照原句 |

- 只有一個金額、看不出是目標還是上限 → 兩欄都不填死，標 `conflicting` 並問「這是大概的價位，還是最多到這裡？」。
- 目標總價高於上限 → 標 `conflicting`，不要自己調。
- **30 天更新**：每張卡記「建卡日」和「最後確認日」。超過 30 天沒有跟客戶確認 → 標「待更新」；待更新的卡配到的物件只進審核區，不進自動推播，並提醒業務送一次確認卡。

## 客戶自己確認需求（卡片草稿）

目的：條件由客戶本人確認或更正，不由系統猜。對話與客戶的對應關係還沒驗證時，系統猜的需求可能是**別人的**——送出去既是錯配、也是個資外洩。

- **安全版（預設）**：卡片不帶任何條件值，只請客戶確認目前條件。對話鍵與客戶代碼的對應還沒驗證、或卡片還沒經業務確認時，只能用這一版。
- **帶值版**：對應已驗證、卡片已由業務確認，才把這位客戶自己的條件摘要（區域、預算、房型、買或租）帶給他本人確認；不帶任何其他客戶的資訊，不帶業務內部備註。
- 卡片只發到這位客戶自己的對話；不發到屋主群、內部群或多位客戶同在的群。
- 客戶回覆後：用原句更新欄位、把「最後確認日」改成回覆日期；客戶說「都一樣」也算確認。
- 本 Skill 只產草稿；送出要經租戶審核，並由租戶授權的工具執行。

```text
（安全版）
跟您確認一下找房條件
您目前找房的條件還是原本那樣嗎？
要確認的：區域・預算（大概的價位／最多到多少）・房型・買或租
有任何調整——預算變了、想看別區、房型改了——跟我說一聲，我幫您更新，配到的物件才會準。

（帶值版，對應已驗證才可用）
跟您確認一下找房條件
目前記錄的是：{區域}｜{目標總價}萬左右、最多 {上限}萬｜{屋型}｜{買/租}
還是這樣嗎？有變動直接回覆就好。
```

## Checklist

- [ ] Buy/rent and target transaction are explicit or marked unknown.
- [ ] Budget unit and upper bound are explicit.
- [ ] Area is separated into preferred and acceptable alternatives.
- [ ] Hard constraints are not mixed with preferences.
- [ ] Exclusions and risk flags are preserved.
- [ ] Missing questions are prioritized by matching impact.
- [ ] No customer identity or contact detail is invented.
- [ ] 10 個欄位都有值或標 `unknown`；目標總價與可接受上限分開；地雷列為 hard。
- [ ] 客戶背景只留跟找房有關、客戶自己說的。
- [ ] 最後確認日已記；超過 30 天標「待更新」。
- [ ] 確認卡：對應未驗證時只用安全版；只發給客戶本人的對話；標明需租戶審核。

## Template

```text
客需卡（草稿）
- 交易：
- 區域：首選／可接受／排除／待確認
- 預算：目標總價（定錨）／可接受上限／單位／是否含車位、裝修
- 物件：類型、房數、坪數（權狀／室內／土地）、樓層、屋齡
- 用途：
- 硬條件：
- 地雷（不能接受）：
- 偏好：
- 排除：
- 客戶背景（只記與找房有關、客戶自己說的）：
- 看屋時段：
- 時程：
- 原話依據：
- 信心：高／中／低
- 建卡日：{日期}｜最後確認：{日期}（客戶確認／未確認）｜下次確認：{最後確認＋30 天}
- 待問（按影響排序）：
- 未來工具動作：無；若要寫回 CRM/聯絡客戶，需租戶授權工具
```

## Output requirements

Return the card first, then `判斷依據`, `衝突與缺件`, and `下一步問題`. Keep unknowns visible. Do not produce a listing recommendation until the user confirms the card or explicitly asks for a provisional match.

## Test cases

**T1 — happy path:** 「想在市區找兩房，總價約 1,200，不能沒有電梯，明年才買。」 Expected: area/currency/rooms/elevator/timing extracted; 約 is soft; missing age, parking, and timing month are questions.

**T2 — conflict:** 「預算 900，最多 1,100，但總價不要超過 1,000。」 Expected: preserve the three signals, flag conflict, ask for authoritative ceiling.

**T3 — insufficient:** 「幫我找一間不錯的。」 Expected: no invented card; ask transaction, area, budget, and property type.

**T4 — number traps:** 群組名稱「買／合成先生／溪北 1000 萬一樓自住／001432」，對話「2025 年底前要買，看過一間 43.578 坪的」。 Expected: budget ceiling 1000 萬 only; 001432、2025、43.578 are not budget; size not set to 578.

**T5 — exclusion:** 「全市都可以，但不要東區、北區，南區可能不太行。」 Expected: acceptable = 全市；excluded = 東區、北區、南區；none of them appear as preferred.

**T6 — our own words:** 「（業務）幫您推送各類物件，含店面、套房、農舍。（客戶）我只要兩三房華廈。」 Expected: type = 華廈 only; 店面／套房／農舍 come from the agent's sentence and are ignored.

**T7 — 目標 vs 上限＋地雷：** 「想買房，總價大概 1,000 左右，最多 1,150，不要死巷、不要持分，我們付現不貸款，週末才能看。」 Expected: 交易＝買；目標總價 1,000 萬（soft）、可接受上限 1,150 萬（hard）；地雷＝死巷、持分（hard 排除）；特殊條件＝付現不貸款；看屋時段＝週末；用途、區域、屋型為 `unknown` 並列入待問。

**T8 — 確認卡與 30 天：** 卡片最後確認日是 35 天前；這個對話鍵和客戶代碼的對應還沒驗證。 Expected: 卡片標「待更新」；只產安全版確認卡（不帶任何條件值）；這張卡配到的物件只進審核區；註明送出要租戶審核，本 Skill 沒有送出。

## Acceptance criteria

- Every supplied fact appears once in a normalized field or evidence note.
- No hard/soft field is guessed from tone alone.
- The output can be reviewed and edited before any external write.
- Tool boundary is explicit and no external action is claimed.
- 目標總價與可接受上限永遠分開存；只有上限會被當成硬條件。
- 對應未驗證時，確認卡不會帶出任何條件值。
