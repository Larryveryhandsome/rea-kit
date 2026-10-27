# adapters/line — LINE 出口（MessagingChannel）

每個租戶自己的 LINE 官方帳號；webhook 網址＝`https://<網域>/webhook/<租戶id>`。

| 檔 | 做什麼 |
|---|---|
| `webhook.py` | 多租戶 webhook：驗簽（沒 secret 一律擋）→ 事件落檔 → 審核鈕／本人指令（待審、額度、測試）→ 外掛 handler → 欠的訊息用回覆補送。`python -m adapters.line.webhook --port 8080` 開發用 |
| `push_gate.py` | **所有主動推播的唯一入口** `PushGate.submit()`：客戶面先送審核卡給本人；範本可一次核准；沒額度→deferred |
| `push_budget.py` | 每月推播預算：上限＝LINE 方案、分級配額、本人通知保留額、每日斷路器；帳本只記成功送出 |
| `client.py` | API 出口：節流、429 分辨限流與月額度用罄、X-Line-Retry-Key 冪等 |
| `flex.py` | 客戶面物件卡、審核卡、送出前自檢（避開 LINE 400） |
| `credentials.py` | 每租戶金鑰（`env:變數名` 不落真值） |
| `groups.py` | 官方帳號在哪些群（由 join／leave 事件維護） |
| `fake_api.py` | 本機假 LINE（測試、示範用）；`synthetic_line_id()` 產合成 ID |

規矩：
- 不要直接呼叫 `LineClient.push` 推客戶——走 `PushGate.submit()`，額度與審核才管得到。
- 回覆（`EventContext.reply`）不計額度：能等對方開口就等。
- 落檔在 `<資料根>/tenants/<租戶>/line/`；reply token 不落檔；帳本不存原始 LINE ID。

試跑：`python tools/demo_w1_push.py`（本機假 LINE）。
