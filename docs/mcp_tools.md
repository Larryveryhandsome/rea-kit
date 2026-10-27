# MCP 工具契約 v0.2（給 Skills 用）— 2026-10-01

> Skill 需要即時資料或要做動作時，**只能**透過這些工具；Skill 不自己採集、不自己打 LINE。
> 實作在 `web/mcp_tools.py`（同名函式），測試在 `tests/test_mcp_tools.py`。**改契約先改這份文件，再改實作**；改了要把版本號 +0.1 並在 §6 記一行。

## 0. 共通規則

| 規則 | 內容 |
|---|---|
| 租戶範圍 | 由連線身分決定（MCP server 放進 `ToolContext`）。**工具參數裡沒有 `tenant_id`**，Skill 指定不了別的租戶。 |
| 唯讀 vs 有副作用 | `list_listings`、`get_need_card`、`match`、`patrol_posts`、`get_push_quota` 唯讀。`queue_for_review` 只**排隊**：客戶面的訊息一律先送審核卡給租戶本人，他按「送出」才會到客戶手上（租戶可在設定改成自動，那是他的決定，不是 Skill 的）。**沒有任何工具能直接推給客戶、留言或私訊。** |
| 錯誤 | 不丟例外，回 `{"error": {"code", "message", "retryable"}}`。`code`：`invalid_argument`（參數或資料不合格）、`not_found`、`not_ready`（資料源或 LINE 還沒設定、功能尚未開放）、`rate_limited`、`quota_exhausted`、`forbidden`。`message` 是可以直接念給仲介聽的白話。 |
| 每筆回傳都有 | `as_of`（資料截至，ISO 時間）、`contract`（契約版本，目前 `"0.2"`）。列表類另有 `source`（資料來源，例：`csv`）。 |
| 個資 | 回傳**不含**電話、身分證、地址門牌、屋主、原始 LINE ID。客戶只給 `customer_id` 與 `label`（租戶自己取的稱呼）。CSV 匯入時這類欄位就沒進系統。 |
| 單位 | 售價＝**萬元**；租金＝**元／月**；坪數＝坪；屋齡＝年；日期＝`YYYY-MM-DD`；時間＝ISO 8601。 |
| 分頁 | `limit`＋`cursor`；回 `next_cursor`，`null`＝沒有下一頁。 |

## 1. 資料格式

### 1.1 Listing（物件）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | string | 租戶自己的物件編號（原樣保留大小寫；只給租戶看，**不會出現在客戶卡片上**） |
| `transaction` | `"buy"`／`"rent"` | buy＝出售物件、rent＝出租物件 |
| `city` | string\|null | 縣市，例 `台中市`（臺一律寫台） |
| `area` | string | **縣市＋鄉鎮市區**，例 `台中市西屯區`。配對用這個欄位比對 |
| `title` | string\|null | 案名 |
| `price` | number | 售：萬；租：元／月 |
| `price_unit` | `"萬"`／`"元/月"` | |
| `property_type` | string\|null | 見 1.3 |
| `rooms` | number\|null | 房數；開放式／套房＝0 |
| `size_ping` | number\|null | 坪 |
| `age_years` | number\|null | 新成屋／預售＝0 |
| `floor` | string\|null | 原樣 |
| `url` | string\|null | 可點的公開連結；**null 的物件不能推給客戶** |
| `photo_url` | string\|null | 只收 https |
| `listed_at` | date\|null | 上架日 |
| `online` | bool | 上架中。下架的物件 `list_listings` 預設不回 |
| `source` | string | 例 `csv` |
| `updated_at` | datetime | |

### 1.2 NeedCard（客需卡）＝`core/listing_matching` 吃的格式

| 欄位 | 型別 | 說明 |
|---|---|---|
| `transaction` | `"buy"`／`"rent"` | 必填 |
| `preferred_areas` | string[] | 必填；格式同 Listing.area（縣市＋鄉鎮市區） |
| `budget_max` | number | 必填；單位同 Listing.price |
| `budget_min` | number\|null | |
| `budget_tolerance_pct` | number | 預設 10（＝預算×1.1 內都算） |
| `property_type` | string\|null | 見 1.3；null＝不限 |
| `rooms_min` | number\|null | |

另附 `version`（客需改一次 +1）、`updated_at`。

### 1.3 物件型態（固定字表，對齊內政部實價登錄建物型態）

`電梯大樓`、`華廈`、`公寓`、`透天`、`別墅`、`套房`、`店面`、`辦公`、`廠房`、`土地`、`農地`、`車位`

> Skill（客需抽取、配對說明）一律輸出這些字，不要用英文或其他同義詞；轉接器匯入時已把「住宅大樓(11層含以上有電梯)」「透天厝」等寫法收斂成上表。

## 2. 工具

### 2.1 `list_listings` — 列出租戶的物件

| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `transaction` | `"buy"`／`"rent"` | 不限 | |
| `areas` | string[] | 不限 | 可給縣市（`台中市`）或縣市＋區（`台中市西屯區`） |
| `property_type` | string | 不限 | 1.3 字表 |
| `price_min`／`price_max` | number | 不限 | 單位同 Listing.price |
| `online_only` | bool | `true` | |
| `changed_since` | datetime | — | 只回這個時間後新增／變更／下架的物件（新案監測用） |
| `ids` | string[] | — | |
| `limit` | int | 50（上限 200） | |
| `cursor` | string | — | |

回傳：`{listings: Listing[], total, next_cursor, as_of, source, contract}`

### 2.2 `get_need_card` — 讀一位客戶的客需卡

參數：`customer_id`（必填）
回傳：`{customer_id, label, status, need_card: NeedCard, missing: string[], can_push: bool, version, updated_at, as_of, contract}`
- `status`：`active`／`paused`／`closed`（已成交、失效）。
- `missing`：配對前一定要補的欄位（`transaction`、`preferred_areas`、`budget_max`）。
- `can_push`：客戶已綁 LINE 群組或好友、且狀態 active。
- 找不到 → `not_found`。

### 2.3 `match` — 客需卡 × 物件配對（引擎＝`core/listing_matching`）

| 參數 | 型別 | 說明 |
|---|---|---|
| `customer_id` | string | 二擇一：用系統裡這位客戶的客需卡 |
| `need_card` | NeedCard | 二擇一：Skill 剛整理出來、還沒存的草稿卡（試配用） |
| `listing_ids` | string[] | 只在這幾間裡配；預設＝所有上架中物件 |
| `limit` | int | 每個 bucket 最多回幾筆，預設 10（上限 50） |

回傳：`{priority: Item[], review: Item[], rejected: Item[], need_card_version, as_of, contract}`
`Item = {listing_id, bucket, score, reasons[], missing[], listing: Listing}`——`listing_id` 已對回原始大小寫，`listing` 附完整物件。
- `priority`＝可優先審核；`review`＝缺資料（例：沒連結）補了才能推；`rejected`＝硬條件不符（每筆都有原因）。
- 客需卡缺必填 → `invalid_argument`；配對引擎還沒部署 → `not_ready`。

### 2.4 `queue_for_review` — 把配對結果排進推播審核

| 參數 | 型別 | 說明 |
|---|---|---|
| `customer_id` | string | 必填 |
| `listing_ids` | string[] | 1–3 間（一則訊息最多 3 間，避免洗版） |
| `note` | string | 選填，≤200 字：給租戶看的「為什麼推這間」，會出現在審核卡上，**不會給客戶看** |

行為：做成一張客戶面 Flex 卡（無內部編號、可點連結）→ 推播閘。預設先推審核卡（含預覽）給租戶本人；他在 LINE 按「送出」才送到客戶群。同一位客戶同一批物件重送＝`duplicate`。
回傳：`{state, item_id, reason, quota: {used, plan_cap, remaining}, as_of, contract}`

| `state` | 意思 |
|---|---|
| `held` | 已排隊等租戶審核（正常結果） |
| `sent` | 租戶設成自動，已送出 |
| `duplicate` | 同一則已在等審 |
| `deferred` | 已核准但本月額度不夠：等額度恢復，或客戶下次開口時用「回覆」補送（不計額度） |
| `skipped`／`failed` | 沒送，`reason` 說明 |

錯誤：客戶沒綁 LINE、租戶沒設 LINE → `not_ready`；物件下架、沒連結、超過 3 間、客戶非 active → `invalid_argument`。

### 2.5 `patrol_posts` — 24h 海巡：找公開社群裡想買／租房的貼文（免費③）

| 參數 | 型別 | 說明 |
|---|---|---|
| `platforms` | string[] | `threads`、`facebook_group`、`import`（租戶手動匯入）；預設＝租戶已啟用的 |
| `keywords` | string[] | 例：想買房、找房、求租 |
| `areas` | string[] | 地區提示（縣市或縣市＋區） |
| `since` | datetime | |
| `limit`／`cursor` | | 預設 50 |

回傳（規劃）：`{posts: Post[], collection: {mode, as_of, stopped_reason}, next_cursor, contract}`
`Post = {post_id, platform, url, posted_at, text, matched_keywords[], area_hints[]}`
- `text` 最多 500 字，電話／Email 先遮罩；**不回作者帳號、頭像、個人頁**——分類（真需求／同業／廣告）是 Skill 的工作，跟進由仲介本人用 `url` 自己去回。
- `collection.mode`：`local_helper`（租戶自己電腦上的小幫手、用他自己的瀏覽器、只看公開頁）或 `imported`。`stopped_reason`：遇到 429／驗證碼／變慢就停並寫在這裡。
- **沒有自動留言、自動私訊的工具，以後也不會有。**

**狀態**：W1 只有契約，呼叫一律回 `not_ready`（retryable）。Skill 先用合成貼文開發；採集等本機小幫手（W2 以後）。

### 2.6 `get_push_quota`（附加）— 本月 LINE 推播額度

回傳推播預算摘要：`{month, plan_cap, used, remaining, control_reserve, levels: {...}}`。Skill 要決定「現在推還是等客戶開口再回」時可以看。沒設 LINE → `not_ready`。

### 2.7 `get_line_bind_code`（v0.2）— 拿 LINE 通知的綁定碼

預設：LINE 以「共用通知帳號」為主，仲介不用自己申請官方帳號。仲介在 ChatGPT 說「我要用 LINE 收新案通知」時呼叫這個。
參數：無。
回傳：`{code, expires_in_minutes: 15, already_bound, how_to, as_of, contract}`——把 `how_to` 原句告訴使用者（加好友後在一對一聊天傳「綁定 123456」）。碼一次性；同一人重新拿碼，舊碼作廢。共用帳號沒開通 → `not_ready`。

共用帳號模式下，新案只通知**仲介本人**（卡片標「適合：哪幾位客戶」＋「分享給客戶」鈕），由仲介自己轉給客人；`queue_for_review`（推進客戶群）只適用仲介自己的官方帳號。

## 3. 推播額度怎麼算（Skill 要知道的事實）

- LINE 免費方案每月 **200 則主動推播**；**回覆不計額度、不限量**。所以產品「回覆為主、推播為輔」。
- 推群組按**人頭**計費：推一個 3 人群＝3 則。
- 分級：客戶物件配對（預設 120／月）、固定範本問候（25）、內部公告（15）、內部日報（0：要看就打字問）；另保留 40 則給租戶本人的通知與審核卡（每日斷路器）。
- 同一位客戶一天最多收 1 則物件推播。

## 4. Skill × 工具對照

| Skill | 用到的工具 |
|---|---|
| `customer-need-structuring` | `get_need_card`（讀現有卡比對差異）；寫回客需卡的工具 v0.2 再加 |
| `listing-need-matching` | `get_need_card`、`list_listings`、`match`、`queue_for_review` |
| `market-new-listing-monitor` | `list_listings(changed_since=…)`、`match` |
| `buyer-intent-patrol`（待新增） | `patrol_posts` |
| `market-price-brief`（收費） | 實價登錄工具 v0.3 再定 |

## 5. 實作狀態

| 工具 | 狀態 | 實作 |
|---|---|---|
| `list_listings` | ✅ 可用（CSV 來源） | `web/mcp_tools.py` → `adapters/csv/listing_source.py` |
| `get_need_card` | ✅ 可用（CSV 來源） | → `adapters/csv/customer_source.py` |
| `match` | ✅ 可用 | → `core/listing_matching.py` |
| `queue_for_review` | ✅ 可用 | → `adapters/line/push_gate.py`＋`push_budget.py` |
| `patrol_posts` | ⏳ 只有契約 | 等本機小幫手 |
| `get_push_quota` | ✅ 可用 | → `adapters/line/push_budget.py` |
| `get_line_bind_code` | ✅ 可用 | → `adapters/line/shared.py`（共用通知帳號） |
| MCP server 包裝 | ⏳ W2 | `web/`（把上面函式註冊成 MCP tools） |

## 6. 變更紀錄

- v0.1（2026-10-01）初版：五個工具＋`get_push_quota`。
- v0.2（2026-10-01 晚）加 `get_line_bind_code`（共用通知帳號）；說明共用模式只通知仲介本人。
