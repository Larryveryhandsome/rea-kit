# core

# core

目前已抽入第一條純邏輯 vertical slice：`listing_matching.py`。

- 輸入：已由上游整理、且不含真實個資的客需卡與物件字典。
- 輸出：`priority`、`review`、`rejected` 三個可解釋 bucket。
- 不負責：即時搜尋、租戶隔離、CRM 寫回、訊息發送、外部登入。
- 外部資料由 adapter/MCP 提供；本模組不自行連網。
