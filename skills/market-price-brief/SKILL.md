---
name: market-price-brief
description: Use when a real-estate agent supplies comparable transactions or an approved market-data result and wants a price range, trend summary, client-facing market brief, or a sanity check on an asking price. Trigger on 實價分析、行情報告、這間房大概多少、幫我整理成交比較. Do not claim live official lookup; current data retrieval belongs to a future MCP/tool layer.
---

# 行情/實價 → 報告

## SOP

1. Inspect the dataset: date, area, property type, size basis, total price, unit price, floor/age and source labels.
2. Remove or quarantine rows with missing critical fields; flag duplicates and obvious outliers rather than silently deleting them.
3. Define the comparison segment before calculating: same area, type, size band, age/floor tolerance, and date window.
4. Summarize count, median, interquartile range or robust low/high band, and known limitations.
5. Translate the result into a suggested asking range only when the subject property fields and adjustment assumptions are supplied.
6. Separate internal agent analysis from a cautious client-facing explanation.
7. 若使用者要「同區同型的行情基準」，照下方「實價登錄開放資料基準」的方法算（或檢查工具算出來的結果是否照這個方法）。下載與快取屬工具層；本 Skill 只定方法與報告。

## Decision points

- Median is preferred over average when the sample is small or skewed.
- Fewer than three comparable rows means directional signal only, not a confident range.
- A row without a date cannot support a trend claim.
- Different size bases (建坪/地坪/含車位) cannot be mixed without an explicit adjustment.
- The report must say whether data is user-supplied, imported, or pending a future official query.
- Never call an estimate「官方認定價格」or「保證成交價」.

### 實價登錄開放資料基準（鄉鎮市區 × 型態）

**資料來源只有一個**：內政部不動產交易實價查詢服務網的開放資料（按季產製的批次資料，免費下載）。不用任何仲介平台、會員系統或別人整理過的二手表；不登入、不爬查詢頁。
依據：內政部及地方地政機關說明，實價登錄批次資料按季產製、免費下載（內政部不動產成交案件實際資訊資料供應系統，plvr.land.moi.gov.tw/DownloadOpenData；查證日 2026-10-03）。

方法（每一步的數字都是參數，預設值如下）：

1. **期間**：最近 4 個「已結束」的季（季別寫法：民國年＋S＋季，例如 `{115S2}`）。本季資料還沒齊，不用。
2. **檔案**：各縣市的買賣檔 `{縣市代碼}_lvr_land_a.csv`（`_a`＝不動產買賣）。第一列中文欄名、第二列英文欄名，資料從第三列起；第一欄常帶 BOM，讀檔要去掉，否則「鄉鎮市區」欄會讀不到。
3. **只留建物或房地成交**：「交易標的」含「建物」或「房地」（土地＋建物）才算；純土地、純車位不進住宅行情。
4. **換成萬／坪**：單價元／㎡ × 3.305785 ÷ 10,000（1 坪＝3.305785 ㎡），四捨五入到小數 2 位。
5. **合理範圍 3–120 萬／坪**：範圍外視為離群（常見原因：含車位拉低或拉高單價、親友間交易、登錄錯誤），剔除並**報出剔除幾筆**。上限是參數：高房價區可能有真實成交超過 120 萬／坪，剔除比例明顯偏高時要提醒租戶調高，不要默默砍掉。
6. **型態歸類**：華廈／透天（別墅併入透天）／套房／大樓／公寓／其他；「其他」不做比較。
7. **分組統計**：以「鄉鎮市區 × 型態」分組，算**中位數**、**第 25 百分位**（含端點的線性內插）、**樣本數**。**樣本少於 3 筆的組不出數字**，只寫「樣本不足」。
8. **成交量**：同時列各區成交筆數與成交最多的型態，回答「這區什麼型態比較有人買」，不要只給單價。
9. **時效**：基準 45 天內可沿用；重建失敗可以退回舊基準，但必須標「資料截至 {季別}，已過期」；什麼都沒有 → `unknown`，不硬給數字。
10. **開價對照（內部用）**：開價每坪 ÷ 同區同型中位數＝比值。≤0.9「低於行情」、0.9–1.1「貼近行情」、>1.1「偏高」；查不到基準或輸入無效 → `unknown`。開價坪數與實價登錄單價的面積基礎可能不同（含不含車位、公設），比值只當方向，不當估價；給客戶的版本只寫比值、樣本數與資料期間，不寫「好賣／難賣」。

- 報告不列門牌，也不要把開放資料拼回個別住戶或屋主。
- 工具層（未來）：每個季檔只下載一次並快取；下載失敗就停，不重試轟炸；連線保持憑證驗證。

## Checklist

- [ ] Subject property and comparison segment are described.
- [ ] Data source and as-of date are visible.
- [ ] Sample count and excluded rows are shown.
- [ ] Unit definitions are consistent.
- [ ] Outliers and missing fields are explained.
- [ ] Range is labeled estimate, not fact.
- [ ] 實價登錄基準：資料來源只寫內政部開放資料、季別寫清楚；只含建物／房地成交；3–120 萬／坪以外的剔除筆數有報；樣本 <3 的組沒有數字。
- [ ] 開價比值只在內部版出現分級字樣；客戶版只寫比值、樣本與期間。
- [ ] Client version avoids unsupported legal or financial certainty.

## Template

```text
行情摘要（資料截至：{date/as supplied}）
- 標的摘要：
- 比較條件：
- 有效樣本：{n}
- 觀察到的單價/總價區間：
- 中位數與分布：
- 實價登錄基準（內政部開放資料｜{季別起}–{季別迄}）：{鄉鎮市區}{型態} 中位 {x} 萬／坪、第 25 百分位 {y} 萬／坪、樣本 {n} 筆｜剔除 {m} 筆（範圍外）
- 開價對照（內部）：開價 {a} 萬／坪 ÷ 中位 {x} ＝ {比值}（{低於／貼近／偏高}；只當方向）
- 建議開價區間（若資料足夠）：
- 影響上下修的因素：
- 資料限制與待查證：
- 未來工具：若需最新實價、地址定位或批次載入，交由 MCP/tool layer。
```

## Output requirements

Provide `資料品質`, `市場觀察`, `估計區間`, `限制`, and `下一步`. Include the raw sample count and adjustment assumptions. If evidence is insufficient, output a range only as a scenario or decline to provide a numeric range.

## Test cases

**T1 — eight rows:** one extreme high and one missing date. Expected: missing-date row excluded from trend; extreme row flagged; median/range remains explainable.

**T2 — mixed basis:** some rows include parking and some do not. Expected: split segments or stop numeric comparison until basis is clarified.

**T3 — no comps:** only asking price is supplied. Expected: no market range; list the minimum data needed.

**T4 — 開放資料基準（合成資料）：** {示範區} 買賣檔 10 列：2 列交易標的是「土地」、1 列是「車位」；華廈 5 列單價換算後為 2.5、25、27、28、30 萬／坪，另有 1 列 150 萬／坪；透天 1 列。期望：土地、車位 3 列不進；2.5 與 150 剔除並報「剔除 2 筆」；華廈中位數 27.5、第 25 百分位 26.5、樣本 4；透天只有 1 筆 →「樣本不足」，不出數字。

**T5 — 開價對照與客戶版用字：** 同上基準，物件開價 1,000 萬、建坪 32 坪。期望：1,000÷32＝31.25 萬／坪，÷27.5＝1.14 → 內部版標「偏高」並註明面積基礎可能不同；客戶版寫「約為同區華廈近 4 季成交中位數的 1.14 倍（樣本 4 筆，內政部實價登錄，{季別}）」，不出現「難賣」。

## Acceptance criteria

- No current-data claim without a current-data tool result.
- Numeric output is reproducible from the shown sample and assumptions.
- Small samples and mixed definitions trigger visible caveats.
- Client copy cannot be mistaken for a guarantee.
- 實價登錄基準可由同一份季檔重算出同樣的中位數、第 25 百分位與樣本數；資料來源只有內政部開放資料。
