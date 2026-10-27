---
name: owner-pricing-negotiation
description: Use when a real-estate agent needs to prepare an asking-price recommendation, explain a valuation gap, or plan a conversation with an owner who resists a price adjustment. Trigger on 屋主嫌我估太低、明天怎麼談、定價策略、幫我準備議價、這間要開多少. Requires supplied numbers and assumptions; live comps, CRM history, and follow-up logging belong to a future MCP/tool layer.
---

# 屋主定價與議價準備

## SOP

1. Separate known numbers: proposed asking price, target net, costs, time window, comparable evidence, and owner's stated motivation.
2. Check arithmetic, units, and whether each number is an asking price, expected net, floor, or scenario.
3. Build a decision range: market-supported scenario, stretch scenario, and speed-of-sale scenario; state assumptions.
4. Prepare a conversation in this order: align goal → show evidence → offer choices → ask for a reversible next step → confirm follow-up date.
5. Define concession ladder and stop points before the meeting; never promise a result that depends on an unknown buyer.
6. Produce a one-page brief plus questions that would materially change the recommendation.

## Decision points

- No comparable evidence means no false-precision price; provide a data-gathering plan instead.
- Owner's emotional anchor is acknowledged, not treated as market evidence.
- A price reduction recommendation must name the tradeoff: time, exposure, buyer pool, or net proceeds.
- If target net conflicts with costs or mortgage assumptions, pause and reconcile the numbers.
- Never coach deception, undisclosed material facts, or pressure tactics.
- Current market lookup, CRM history, and meeting follow-up are future tools, not hidden capabilities.

## Checklist

- [ ] All amounts have unit and role labels.
- [ ] Evidence date/source/sample size are shown.
- [ ] Owner goal and deadline are explicit.
- [ ] At least two scenarios are compared.
- [ ] Concession ladder and stop point are written.
- [ ] Conversation uses choices and evidence, not guarantees.
- [ ] Missing facts are questions, not assumptions.

## Template

```text
屋主議價簡報
- 屋主目標：
- 我方已知數字：開價／期望淨額／成本／期限
- 證據摘要：
- 情境 A｜速度優先：
- 情境 B｜價格平衡：
- 情境 C｜價格優先：
- 建議先談的選項：
- 讓步階梯：每一步的交換條件
- 停損/重估點：
- 三句開場：
- 待補資料：
- 未來工具：最新行情、CRM 紀錄、會後寫回需授權 MCP/tool layer。
```

## Output requirements

Return `數字檢查`, `情境比較`, `談判流程`, `可直接說的話`, `風險與待補`. Make every recommendation conditional on its evidence. Include a neutral alternative if the owner rejects the first recommendation.

## Test cases

**T1 — supplied evidence:** asking 2,380, three comparable ranges 1,900–2,100, owner prioritizes speed. Expected: speed-balanced scenario leads; no claim that a sale is guaranteed.

**T2 — arithmetic conflict:** target net exceeds asking price after stated costs. Expected: flag impossible arithmetic and ask which number changes.

**T3 — no comps:** owner asks「市場現在多少」but supplies no data. Expected: decline numeric answer and specify a future market-data request/tool contract.

## Acceptance criteria

- Arithmetic and unit errors are caught before rhetoric is generated.
- At least one evidence-backed and one tradeoff scenario are shown when data allows.
- The script is firm, transparent, and non-deceptive.
- External lookup and CRM actions remain explicit future integrations.
