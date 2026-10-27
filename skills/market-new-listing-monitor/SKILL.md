---
name: market-new-listing-monitor
description: Use when a real-estate agent wants to monitor new listings in a selected county, district, property type, price/size/age range, or wants to know which new or changed listings should enter a buyer-matching queue. Trigger on 全市場掃描、新案監測、指定區域找新物件、哪些新案要通知買方. It requires a supplied or authorized listing feed; web collection, deduplication storage, and notifications belong to the MCP/tool layer.
---

# 全市場新案監測

## SOP

1. Confirm the scan scope: county/city, district/township, transaction, property type, price, size, age, and as-of time.
2. Load only normalized listings from an approved source and record source/timestamp for every row.
3. Compare the current snapshot with the prior snapshot by stable listing id and content fingerprint.
4. Keep `new` and materially `changed` rows; do not re-alert unchanged rows.
5. Apply hard scope filters before ranking; put missing filter fields into review instead of silently including them.
6. Send qualifying rows to the matching queue. A future tool may notify a buyer only after policy/approval checks.

## Decision points

- A region must be explicit; do not infer a district from a project name.
- A listing missing price, type, or location cannot be marked ready for buyer notification.
- A changed price/status/URL is material; a timestamp-only refresh is not.
- Removed listings leave the active queue and are retained only as an audit event.
- Public-page collection must obey the source's terms, rate limits, and stop on 429/captcha/tarpit.
- The Skill never claims to have searched live websites unless a tool result is supplied.

## Checklist

- [ ] Region and as-of time are recorded.
- [ ] Source and source URL are retained.
- [ ] New/changed/unchanged/removed states are separated.
- [ ] Hard filters are applied before ranking.
- [ ] Missing data is visible as review, not a match.
- [ ] Duplicate IDs and content fingerprints are handled.
- [ ] Notification remains behind approval/quota/tool boundaries.

## Template

```text
市場新案監測
- 範圍：{縣市}/{區域}/{類型}
- 條件：{價格}/{坪數}/{屋齡}/{買租}
- 資料截至：
- 新案：{count}
- 有變更：{count}
- 待補資料：{count}
- 已移除：{count}
- 候選清單：物件、變更原因、來源時間、可配對條件
- 外部動作：尚未通知；查詢、保存、推播需 MCP/tool layer。
```

## Output requirements

Return `掃描範圍`, `新案`, `重大變更`, `待補資料`, `排除原因`, and `下一步`. Every candidate needs a stable id, source, timestamp, and reason for entering the queue. State clearly whether the input was a supplied snapshot or a live tool result.

## Test cases

**T1 — region filter:** supplied listings cover two districts; expected only the requested district enters the candidate set.

**T2 — new/changed:** one new id, one price change, one unchanged row, and one removed id; expected only new and changed rows are alert candidates.

**T3 — incomplete row:** a matching-area listing lacks price; expected review, never ready-to-notify.

## Acceptance criteria

- Re-running the same snapshots does not create duplicate candidates.
- Region and hard filters are deterministic and explainable.
- Changed listings have a visible change reason.
- No live search or notification is claimed without a tool result.
