"""LINE 轉接器（MessagingChannel）：多租戶 webhook、推播閘＋推播預算、Flex 卡片、API 出口。

所有主動推播一律走 PushGate.submit()；回覆走 EventContext.reply()（不計額度）。
"""
