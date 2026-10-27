# adapters

# adapters

目前已抽入公開來源註冊表、保守公開頁抓取骨架，以及兩個安全的資料介面：`csv_listing_source.py` 與 `customer_csv_source.py`。

它只處理租戶主動提供的 CSV：欄位檢查、型別正規化、快照差異與新案/變更/未變更/移除分類。它不連網、不登入、不讀取第三方內部系統，也不負責推播。

未來公開頁或租戶授權來源應輸出同樣的 normalized listing contract，再交給 `core.listing_matching`。

客戶資料必須由租戶明確提供或授權，不得默默讀取私人訊息；Google Sheet、LINE 官方帳號與 CRM 都應各自實作 adapter，再交給相同的客需欄位契約。

`sources/public_sources.json` 是候選來源登錄表。只有 `verified` 才能進排程；目前只有政府母名單來源標成 verified，品牌與平台網站仍待逐站檢查 robots、條款與頁面格式。
