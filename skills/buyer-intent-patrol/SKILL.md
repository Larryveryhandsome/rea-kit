---
name: buyer-intent-patrol
description: Use when a real-estate agent wants to find genuine people publicly expressing that they want to buy or rent property. Trigger on 24h 海巡、找買方、找想買房的人、社群需求掃描. It requires supplied or authorized public-post results; collection belongs to the MCP/tool layer and this skill never comments, follows, messages, or contacts anyone automatically.
---

# 24h 海巡想買房的人

## SOP

1. Confirm the source, collection time, public visibility, and target area if provided.
2. Call the authorized `patrol_posts` tool when live public-post collection is available; otherwise ask for a supplied batch.
3. Classify each post as `buyer-intent`, `industry`, `advertisement`, or `irrelevant`.
4. For buyer-intent posts, extract only visible business signals: area, transaction, budget, property type, rooms, timing, and stated constraints.
5. Mark missing fields and confidence; never infer an identity, phone number, address, or hidden intent.
6. Return a human-review queue. Do not comment, follow, send a DM, add a contact, or push a message.

## Decision points

- Publicly visible does not mean permission to contact; the result is a lead-review queue only.
- A post mentioning property without a personal buying/renting signal is not a buyer lead.
- Posts that promote listings, services, recruiting, or agent activity are `industry` or `advertisement`, not leads.
- A live search may be claimed only when the tool returns source URLs and collection timestamps.
- Stop and surface the source error on 429, captcha, login wall, robots restriction, or unclear authorization.

## Checklist

- [ ] Source and collection timestamp are recorded.
- [ ] Each item has a stable post id and source URL when available.
- [ ] Category and evidence signals are shown.
- [ ] Missing conditions are visible instead of guessed.
- [ ] No private profile data or hidden metadata is included.
- [ ] Human review is required before any outreach.
- [ ] External action is explicitly `none`.

## Template

```text
24h 海巡結果
- 資料來源／截至：{source} / {as_of}
- 真需求：{count}
- 同業：{count}
- 廣告：{count}
- 無關：{count}
- 待人工審核：{review_queue}
- 外部動作：未留言、未私訊、未追蹤
```

## Output requirements

Return `資料來源`, `截至時間`, `分類統計`, `真需求候選`, `需求摘要`, `缺少欄位`, `建議人工下一步`, and `外部動作`. For every candidate include `post_id`, source URL if supplied, evidence signals, and confidence. State whether the input came from a live tool or a supplied batch.

## Test cases

**T1 — genuine buyer:** a public post says the author wants to buy in a named area and gives a budget; expected `buyer-intent` and review-only output.

**T2 — agent promotion:** a post advertises a listing or says the author is an agent; expected `industry` or `advertisement`, never a buyer lead.

**T3 — no contact:** every result must explicitly show no automated comment, follow, DM, or push.

## Acceptance criteria

- The skill never claims to have scanned live posts without a tool result.
- Buyer candidates are explainable from visible text only.
- No automated outreach occurs.
- Re-running the same supplied batch produces the same categories and counts.
