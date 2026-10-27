# adapters/csv — 租戶自己上傳的 CSV

| 檔 | 介面 |
|---|---|
| `listing_source.py` | ListingSource：`import_csv`、`list_active`、`get`、`public_url`、`changes_since`、`mark_online`、`delete_all` |
| `customer_source.py` | CustomerSource：`import_customers`、`get_need_card`、`bind_line_target`、`import_groups`、`export`、`delete_all` |
| `parsing.py` | 編碼（UTF-8／Big5）、欄位對映、金額單位、民國年、型態字表、區域正規化 |

正規化後的欄位與單位見 `docs/mcp_tools.md` §1（售價萬、租金元/月、區域＝縣市＋鄉鎮市區、型態用內政部字表）。

資料最小化：地址門牌、屋主、電話、身分證、Email、備註等欄位**不匯入**，匯入報告的 `ignored_sensitive_columns` 會列出來；也不能用欄位對映硬塞進來。

測試資料：`tests/fixtures/*_synthetic.csv`（全合成；LINE ID 在測試執行時產生）。
