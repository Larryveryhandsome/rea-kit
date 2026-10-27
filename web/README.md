# web

`index.html` 是第一版公開產品入口：在瀏覽器內載入合成範例或使用者自己的 CSV，完成一次「新案 → 買方」配對。

- 不上傳 CSV；本 demo 只在瀏覽器內處理。
- `app.js` 只發出瀏覽器 CustomEvent；事件儲存與登入屬於未來 web/MCP layer。
- 真實來源、LINE、CRM、謄本與公開網路查詢不在這個靜態 demo 內。
- 入口成功條件：使用者 5 分鐘內看到優先候選、待補資料與淘汰理由。

## 服務本體

| 檔 | 內容 |
|---|---|
| `line_app.py` | 組裝 LINE 服務：各功能處理順序、今日報告、管理員面板連結 |
| `app_holder.py` | 串接精靈存了新金鑰後重新組裝服務，不用重開程式；沒串 LINE 也能開 |
| `setup_wizard.py`、`setup.html` | 一鍵串接精靈 `/setup`（只限本機＋一次性網址） |
| `setup_claim.py` | LINE 傳「管理員 6碼」綁定管理員 |
| `scheduler.py` | 每分鐘一輪：今日報告、加報、LINE 額度同步、Google 試算表每日同步 |
| `admin_app.py` | 管理員面板 `/admin` |
| `terms_page.py` | 服務條款 `/terms` |

啟動入口：`tools/serve_line.py`（Waitress）；一般使用者用 `tools/start.py` 或根目錄的 `.vbs`。
