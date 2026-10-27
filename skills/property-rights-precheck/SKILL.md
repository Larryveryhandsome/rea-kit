---
name: property-rights-precheck
description: Use when a real-estate agent provides a deed excerpt, land/building registry fields, encumbrance notes, or a document summary and asks for a first-pass property-rights checklist, missing documents, or items to verify. Trigger on 幫我看謄本、產權初檢、這份權狀有什麼要注意、列出補件. This is not legal advice and does not request official records; official retrieval and identity-sensitive parsing belong to a future authorized MCP/tool layer.
---

# 謄本/產權初步檢查

## SOP

1. Identify the document type, issue date, page/section labels, and whether the content is complete.
2. Extract only visible fields into `文件顯示`; keep interpretation in a separate section.
3. Check for ownership parties, area/unit consistency, use/type labels, restrictions, mortgages, annotations, leases, and missing pages.
4. Classify each item as `未見異常於所提供頁面`, `需要補件`, `需要專業確認`, or `資料矛盾`.
5. Produce a transaction-preparation checklist and questions for the qualified professional/authority.
6. Never conclude that title is clear, transferable, or free of debt from an excerpt.
7. 若使用者要做完整的物件調查（物調表），依下方「物調表欄位群」逐群列出：已填（附來源）／缺／與登記資料矛盾。
8. 檢查不動產說明書的時點：有沒有經紀人簽章、解說前有沒有經委託人簽章、是不是今年 1 月 1 日公告土地現值之後的版本（見「不動產說明書的時點與年度重印」）。

## Decision points

- Missing issue date or incomplete pages downgrade the whole review to limited.
- A mortgage entry is a fact to verify, not proof that repayment is impossible or complete.
- A mismatch between area, parcel, building unit, or address becomes a stop-and-verify item.
- Names and identification details should be minimized in output; do not copy unnecessary personal data.
- Legal interpretation, tax calculation, priority rights, or transaction approval requires a qualified professional.
- Official document retrieval, OCR, and secure storage are future tools; this Skill analyzes only supplied content.

### 物調表欄位群（物件調查＋銷售資料合一）

每一欄都要有「來源＋查證日」；屋主口述標「依屋主告知」；沒有來源的欄位留空，不猜。

| 欄位群 | 內容 | 對照什麼 |
|---|---|---|
| 基本 | 物件代號、案名（內部用）、坐落（地段地號／建號；對外只寫到段）、委託來源、售屋動機（內部，不寫進任何廣告）、建檔人 | 委託書 |
| 價格 | 總價、單價、屋主實拿試算（服務費、稅費、代書費、履約保證費等項目與比例由租戶設定，不寫死） | 委託書 |
| 土地 | 面積（全部／持分／含道路用地）、都市計畫內或外、使用分區、非都市土地使用地類別（甲乙丙丁種建築用地、農牧、林業…）、臨路寬、面寬、深度、空地比 | 土地登記資料、地籍圖、分區證明 |
| 建物 | 權狀坪＝主建物＋附屬建物＋公設（算出公設比）、增建、外觀、結構、樓層、屋齡、格局（房廳衛）、朝向 | 建物登記資料、建物測量成果圖 |
| 車位／管理 | 有無、編號、停車方式；管理方式、管理費／清潔費、繳費方式 | 規約、管理單位 |
| 機能／水電 | 學區（以當年度教育主管機關公告為準）、公園、市場、車站；水電狀態、現有貸款 | 屋主告知＋查證 |
| 重點／簽核 | 銷售重點、注意事項、委託類別；經紀人員、主管、建檔人簽核 | — |

- 面積、權利範圍、登記日、抵押與限制以登記資料為準；坐落、相鄰、形狀與臨路看地籍圖；建物範圍與面積看建物測量成果圖。物調表和這三種文件對不上 → `資料矛盾`。
- 增建不算進權狀坪與房數；分區或使用地類別沒有來源 → `需要補件`，不能寫「可建」。
- 物調表是內部資料：售屋動機、屋主資訊、實拿試算不外流到廣告或給買方的文件。

### 不動產說明書的時點與年度重印

- **誰簽、什麼時候**：
  - 說明書要由經紀業指派的經紀人簽章（第 22 條）。
  - 經紀人員執行業務時要用說明書向買方（或承租方）解說；**解說前，說明書要先經委託人簽章**（第 23 條）。所以物調完成 → 製作說明書 → 委託人簽章 → 才拿去帶看解說。
  - 簽買賣或租賃契約時，經紀人要把說明書交給買方並由買方簽章，**說明書視為契約的一部分**（第 24 條）：寫錯的內容等於寫進契約，與登記資料不一致一律先改。
  依據：不動產經紀業管理條例第 22、23、24 條（全國法規資料庫，查證日 2026-10-03）。
- **每年 1 月 1 日之後要重印**：直轄市、縣（市）政府每年 1 月 1 日公告土地現值，作為申報土地移轉現值的參考。說明書裡用公告土地現值算的欄位（例如土地增值稅概算）會跟著變。1 月 1 日後仍在銷售的物件 → 用新公告現值重算、重印，新版要再經委託人簽章才能用來解說；舊版標「作廢」，不要兩版並存。
  依據：平均地權條例第 46 條（全國法規資料庫，查證日 2026-10-03）。
- 稅額概算只是概算，正式金額以稅捐機關核定為準；本 Skill 不計算稅額，只提醒要重算。

## Checklist

- [ ] Document type/date/completeness recorded.
- [ ] Ownership and share fields separated from annotations.
- [ ] Land/building/parking areas not mixed.
- [ ] Mortgage/restriction/lease/annotation sections checked.
- [ ] Contradictions and missing pages listed.
- [ ] Personal data minimized.
- [ ] No legal clearance or transaction guarantee stated.
- [ ] 物調表七個欄位群都看過；每欄有來源與查證日，缺的列補件。
- [ ] 說明書：經紀人已簽章；解說前已經委託人簽章；版本在今年 1 月 1 日之後（或已排重印）。

## Template

```text
產權初檢（僅限所提供文件）
- 文件範圍與完整度：
- 文件顯示：
  - 標示部：
  - 所有權部：
  - 他項/註記：
- 需要補件：
- 需要專業確認：
- 資料矛盾：
- 可先問的問題：
- 物調表：{欄位群}｜已填 {n}／缺 {n}／矛盾 {n}｜缺：{…}
- 不動產說明書：版本日期 {日期}｜經紀人簽章 {有/無}｜委託人簽章 {有/無}｜{需重印：1/1 公告土地現值已更新／不需}
- 限制：本結果不是法律意見，也不是官方最新謄本判定。
```

## Output requirements

Lead with scope and confidence. Use a table with `項目 / 文件顯示 / 風險狀態 / 下一步`. Keep quoted evidence short and avoid reproducing unnecessary identifiers. End with a clear handoff list for legal, tax, or official-record review.

## Test cases

**T1 — incomplete excerpt:** supplied ownership and mortgage pages lack issue date. Expected: limited review, issue-date/page補件, no clear-title conclusion.

**T2 — mismatch:** land area and building summary disagree. Expected: contradiction stop, do not calculate ownership or price impact.

**T3 — clean-looking sample:** no visible annotation in supplied pages. Expected wording is limited to「所提供頁面未見」, not「無負擔」.

**T4 — 年度重印：** 物件的說明書在前一年 11 月製作（含土地增值稅概算），今天是 1 月 5 日，物件仍在銷售，下週有帶看。期望：標「需重印」：以 1 月 1 日新公告土地現值重算概算、重印，新版經委託人簽章後才能用於帶看解說；舊版標作廢；附平均地權條例第 46 條依據。

**T5 — 物調缺來源＋說明書未簽：** 物調表土地欄只寫「建地」，沒有使用分區或使用地類別的來源；說明書經紀人已簽章、委託人還沒簽，明天要帶看。期望：分區列 `需要補件`（要求分區證明或登記資料），不得寫「可建」；說明書未經委託人簽章 → 不得用於解說，列為明天帶看前必補的第一件事。

## Acceptance criteria

- Fact and interpretation are visibly separated.
- Every risk status has a next verification action.
- Incomplete documents never receive a definitive clearance label.
- No external record retrieval or legal conclusion is claimed.
- 未經委託人簽章、或早於當年 1 月 1 日公告土地現值的說明書，一定被標出來，不會被當成可用版本。
