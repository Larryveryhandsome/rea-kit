# rea-kit（房仲自動化神器 開源版）公開前檢查（RELEASE_CHECK）

- 最新複查日：**2026-11-05**（雲端上線品質整理，見「2026-11-05 複查」一節）；前次：2026-10-24、2026-10-27
- 檢查的版本：`bf10e9e`（起點）＋本次修正 commit（PR 分支 `claude/festive-gauss-5la38e`）
- 目前可見度：**PUBLIC**（2026-10-27 依店長決策 O02 公開）
- 測試環境：11/05 為 Linux 雲端容器（Python 3.10.20／3.11.18／3.12.3／3.13.18／3.14.6、Docker 29）；10/24 為 Windows 11、Python 3.14 與 3.10.22

## 結論先講

**維持公開，本次修正後可上線。** 11/05 複查找到並修好 11 個問題（其中 1 個是「只限受邀」可被繞過的安全問題、2 個是試算表同步會蓋掉 LINE 上的操作），每個都有重現與回歸測試；測試 384 → **400 項，5 個 Python 版本全過**。Docker 第一次實測可建置、可啟動。
第 3 道「真實 LINE／Google／搜尋／地政帳號從沒實測成功路徑」的已知限制不變（雲端碰不到真帳號，店長 10/27 已接受）。

| # | 閘門 | 結果 | 一句話 |
|---|---|---|---|
| 1 | 需求與設計 | ✅ | 角色（管理員／仲介）、只限受邀、推播額度、外部服務失效退路都有寫；11/05 補上「還沒設管理員時只有第一個人能加入」的規則與文件 |
| 2 | 程式本身 | ✅ | 400 項測試全過（Python 3.10–3.14）、相依套件 0 個已知漏洞、11/05 修 11 個問題 |
| 3 | 串接 | ⚠️ | 本機假 LINE（含 Docker 容器內簽章 webhook）走完整流程；真實 LINE／Google／搜尋服務／地政平台的成功路徑沒有實測 |
| 4 | 完成使用者任務 | ✅ | 邀請→綁定→建客人→查詢主流程；11/05 修好試算表物件卡按鈕沒反應、租金按鈕永遠被擋、打字區域認錯縣市 |
| 5 | 安全／效能／環境 | ✅ | 11/05 修好「沒設管理員時任何陌生人都能加入」；越權、簽章、精靈只限本機、管理員面板登入維持實測通過 |
| 6 | 資料 | ✅ | 11/05 修好試算表每日同步會下架 LINE 物件、把暫停的客人改回啟用、蓋掉 LINE 改過的需求；稱呼欄含電話不再收 |
| 7 | 交付版本 | ✅ | 乾淨 clone 可裝可測；git 歷史 10/27 已重建；Docker 11/05 實測可建置啟動（非 root 執行） |
| 8 | 出事能恢復 | ✅ | 稽核紀錄、串接健康檢查（精靈頂端紅字）、推播冪等重送、可還原備份（未變動） |

## 證據

### 第 2 道 程式本身
| 項目 | 指令 | 結果 |
|---|---|---|
| 全部測試 | `python -m unittest discover -s tests -p "test_*.py"`（Python 3.14） | 382 項全過（原 378，本次新增 4） |
| 同上 | Python 3.10.22 | 382 項全過 |
| 相依套件漏洞 | `pip-audit -r requirements-server.txt` | No known vulnerabilities found |
| 靜態檢查 | `pyflakes core adapters web tools` | 找到 `adapters/line/customer_intake.py` 有一段在 `return` 之後、永遠跑不到、而且引用不存在變數的殘留程式碼 → **已刪除**（不影響行為，測試仍全過）；其餘只是沒用到的 import |
| 其他自檢 | `validate_cards.py`（LINE 卡片格式）、`validate_skills.py`（36 個 Skills）、`pii_scan.py --all` | 61 種回覆 0 問題；36 skills 通過；pii_scan 通過 |
| 擴展性與漏洞檢視 | `docs/擴展性與漏洞檢視.md` | 🟠 16 項已修並有測試；🟡 只列出 |

### 第 4、5 道 實機（真的啟動 `tools/serve_line.py`，本機假 LINE API，簽章 webhook，共 39 項檢查全過）
| 需求 | 風險 | 測試 | 預期 | 結果 |
|---|---|---|---|---|
| webhook 一定要簽章 | 偽造請求 | 壞簽章、沒帶簽章、超大 body | 拒絕（400/401/403，超大直接斷線） | ✅ |
| 預設只限受邀 | 陌生人耗用推播／搜尋額度 | 陌生人傳「同意並開始」 | 「只開放受邀的人使用」，沒有建立帳號 | ✅ |
| 邀請流程 | 綁定碼被濫用 | 管理員面板發 2 組碼；亂打碼；A 拿 B 的碼 | 亂打碼拒絕；碼只能用一次 | ✅ |
| 仲介之間資料隔離 | 越權讀取 | A 建客人；B 查客戶清單、搜尋 | B 看不到 A 的客人 | ✅（另有 `test_review_shared_isolation.py`：B 用客人 ID 查／改／暫停／恢復 A 的客人全部失敗、資料不變） |
| 非管理員不能拿管理員面板 | 提權 | 一般仲介傳「管理員面板」 | 沒有登入連結 | ✅ |
| 管理員面板登入 | 未授權／重放／CSRF | 沒登入開 `/admin/`；登入連結用兩次；表單 CSRF 錯誤；偽造 cookie | 401／第二次 403／403／401 | ✅ |
| 串接精靈只限本機 | 外網打進來 | 沒進入碼、帶 `X-Forwarded-For`、Host 改成別的網域、進入碼錯誤 | 全部 403；進入碼正確才給 cookie | ✅ |
| 精靈 API 防 CSRF | 跨站請求 | POST 不帶自訂標頭 | 400 | ✅ |
| 精靈不回顯金鑰 | 外洩 | 讀 `/setup/api/status` | 回應不含 secret／token | ✅ |
| 貼壞金鑰 | 輸入處理 | 精靈貼 1 字的 secret | 白話錯誤（「應該是 32 個英數字…」），不當掉 | ✅ |
| 超長／注入的客人暱稱 | 輸入處理 | 暱稱 `<script>`×100 | 「請用 1–30 字」，不當掉 | ✅ |
| 金鑰不落檔 | 外洩 | 掃描資料夾所有 json／csv／txt | 不含頻道 secret／token | ✅ |
| 沒有原始對話檔 | 個資 | 檢查資料夾 | 沒有 messages／events 目錄；稽核紀錄不含 LINE ID | ✅ |
| 不會自己亂推播 | 超額／騷擾 | 整段流程後檢查假 LINE 的 push | 0 則 | ✅ |
| 精靈畫面 | 畫面壞掉 | 瀏覽器開精靈（電腦與 375px 手機寬度） | console 無錯誤、排版正常 | ✅ |

### 第 5 道 自動化、只模擬不送出、平台風險、AI
| 項目 | 結果 |
|---|---|
| 自動發文 | 本版**沒有**任何自動對外發文功能（臉書發文、本機小幫手 README 標「尚未上線」）；沒有爬 591／樂屋（平台條款禁止，改走搜尋服務官方 API）；不代調謄本 |
| 主動推播（今日報告、新物件通知）| 每位仲介每天最多 3 則、每月公平份額；同一 retry key 重送不會重複（`test_line_push_budget_gate.py`）；沒接搜尋服務時排程整個不啟動 |
| **只模擬不送出（本次新增）** | 環境變數 `REA_PUSH_DRY_RUN=1`：推播整條流程照跑，但不連 LINE、不耗額度，只在 server.log 印 `[dry-run]`。新增 `tests/test_push_dry_run.py` 4 項：不碰網路、預設仍是真推播、回覆不受影響、壞收件 ID 仍被擋；寫進 `.env.example` 與 `docs/金鑰申請.md` ✅ |
| LINE Flex 卡片官方格式 | `tools/validate_cards.py`：61 種回覆 0 問題（本機自檢；尚未送 LINE 官方驗證器） |
| 提示詞注入 | 本專案沒有呼叫任何 LLM（程式碼搜尋沒有 anthropic／openai／claude API 呼叫），貼文判斷是規則式；搜尋結果網址只放 http(s)（防 `javascript:`，`AdminXssTests`）。此項不適用 |
| 合規 | `docs/法遵/` 有使用條款、委託處理條款、客人告知範本；README 免責聲明用「原則上不構成估價、法律或稅務意見」；「刪除我的資料」「匯出我的資料」LINE 指令已有 |

### 第 6 道 資料
| 項目 | 做法 | 結果 |
|---|---|---|
| 備份還原 | 把跑過的資料資料夾（`REA_DATA_DIR`）整個複製到新資料夾，用程式讀回 | ✅ 仲介 A 的 1 位客人完整讀回、仲介 B 0 位；綁定、同意紀錄都在 |
| 資料格式 | 每位仲介一個資料夾的 JSON，原子寫入＋鎖 | ✅（`adapters/storage.py`；百位仲介以內） |
| 刪除我的資料 | LINE 指令＋測試 | ✅（`test_my_data.py`） |
| 升級路徑 | 資料是 JSON、沒有資料庫結構要遷移；`git pull` 後重啟（`停止.vbs`→`啟動.vbs`） | ✅ |

### 第 7 道 交付版本
| 項目 | 結果 |
|---|---|
| 測的版本＝要發布的版本 | ✅ 乾淨 clone 的 `fcb4279` 跑測試；修正後再重跑 382 項全過 |
| 乾淨環境照 README 安裝 | ✅ 建 venv、`pip install -r requirements-server.txt`、`tools/serve_line.py` 啟動、`/healthz`、`/setup` 都通 |
| Docker | ✅ 11/05 實測（見下方「2026-11-05 複查」）；10/24 那台沒有 docker |
| 去識別化（現有檔案） | ✅ `deep_audit.py` 命中逐筆判讀：命中的地名都是全台行政區字典與測試資料（地名，不是個資）；`velo` 是 LICENSE／英文字「develop」的誤判；測試裡的 `SECRET=...` 是合成假值（`0123…ef`、`synthetic-secret`）；`xxxx.trycloudflare.com` 是說明用範例網址；「留白事務所／留白創研」為作者署名、收款主體與客製化 LINE（`林其衞的 LINE`），是刻意保留（見下方請店長確認） |
| CI | ✅ 本次新增 `.github/workflows/test.yml`（Python 3.10、3.13、ubuntu：測試＋Skills／卡片／pii 檢查）；GitHub Actions 實跑 `success`（run 40058072012） |
| **git 歷史** | ✅ 10/27 已重建為全新單一 commit（見最下方「2026-10-27 公開前補充」）；作者信箱全部是 noreply |

### 第 8 道 出事能恢復
| 失效情境 | 行為 | 證據 |
|---|---|---|
| LINE token 被重發／刪除 | 每天檢查，精靈頂端顯示紅字 | 檢視報告 #11 |
| Google 試算表取消共用、搜尋金鑰失效、地政金鑰過期 | 精靈頂端紅字；金鑰換新立即解除 | 檢視報告 #12、#13 |
| 精靈設錯 webhook 網址 | 先測新網址，通過才改 LINE 設定，不會弄壞原本能用的 | 檢視報告 #4 |
| 地政查詢逾時／連按 | 送出前先算用量、同一地號排隊、第二次用快取，不重複扣款 | 檢視報告 #14、#15 |
| 公開 webhook 被亂打 | 壞簽章稽核每分鐘最多一筆，不寫滿硬碟 | 檢視報告 #6 |
| 回復方式 | 還原 `REA_DATA_DIR` 備份（已演練）；程式版本用 git 回到前一版 | 第 6 道 |

## 已知問題（要寫進 README 讓使用者知道）

1. **真實串接成功路徑從沒實測**：沒有店長的測試用 LINE 官方帳號、地政平台帳號與金鑰、搜尋服務 API key。目前用本機假 LINE／假網路走過成功路徑，用真網路只驗過失敗訊息。第一次接真帳號時請先設 `REA_PUSH_DRY_RUN=1` 試跑。（店長已指示：不用提供金鑰。）
2. ~~Docker 部署沒實測~~ → 11/05 已實測建置與啟動（Linux）；Windows 上的 Docker Desktop 沒測。
3. 同店多位經紀人各自獨立，不能共用客戶清單；JSON 儲存約百位仲介以內；webhook 去重只在記憶體（檢視報告 🟡）。
4. MCP 伺服器、臉書發文、local-helper 尚未上線（README 已標）。
5. 本專案由 Windows 開發；CI 已在 Ubuntu 上實跑全綠（Python 3.10、3.13）。

## 要店長決定／處理

1. ~~歷史要全新~~ → 10/27 已完成。
2. ~~作者署名、收款主體、客製化 LINE~~ → 店長已決定刻意保留（客製化廣告導生意，Apache-2.0＋NOTICE 要求轉散布保留）。
3. 主機租用方案的價格仍是草稿（`docs/主機租用方案.md`）。
4. 接受「真實串接未實測」「Docker 未實測」的已知限制。
5. 原專案的夜間自我檢查排程已被刪除（不是本檢查動的），要不要重建由店長決定。

## 發布決定

~~目前不建議公開~~（10/24 舊結論）→ 10/27 第 7 道解決後公開；11/05 複查後維持公開，合併本次 PR 即可上線。

## 本次修正

| 項目 | 內容 |
|---|---|
| 新增 | `REA_PUSH_DRY_RUN=1` 只模擬不送出（`adapters/line/client.py`）＋`tests/test_push_dry_run.py` 4 項＋`.env.example`、`docs/金鑰申請.md` 說明 |
| 移除 | `adapters/line/customer_intake.py` 一段 return 之後永遠跑不到的殘留程式碼 |
| 新增 | `.github/workflows/test.yml`（CI） |
| 新增 | 本檔 |


## 2026-10-27 公開前補充
| 項目 | 結果 |
|---|---|
| 店長決策 | O02「兩個都公開」（2026-10-27）；第 3 道「真實帳號未實測」的已知限制一併接受，README 已註明 |
| 新發現的 bug | 客製化服務資訊含「衞」，繁中 Windows 主控台（cp950）印不出 → `tools/start.py` 啟動會當掉。已改成印不出的字換成 ?，並加回歸測試 |
| 全部測試 | 繁中 Windows cp950 主控台：384 項全過（原 382） |
| 去識別化掃描 | `deep_audit.py`（現有檔案＋全歷史＋作者信箱＋照片 GPS），報告 `_qa/deep/O02_公開前.md`：命中全部判讀為誤判或刻意保留（行政區地名、velo 誤判、作者署名與 林其衞的 LINE 客製化廣告、測試用合成假值、說明用範例網址）；歷史命中 0、非 noreply 作者 0 |
| 授權 | 授權由 AGPL-3.0-only 改為 Apache-2.0（LICENSE、NOTICE、README、plugin.json、setup 頁同步）；Apache-2.0＋NOTICE（轉散布須保留作者與客製化聯絡資訊） |
| 金鑰 | 沒有任何真實金鑰進過這個 repo，不需輪替 |
| 第 7 道 | 舊歷史 bundle 備份後，以目前內容建立全新單一 commit 並 force push，再改 PUBLIC，最後從乾淨 clone 重跑測試與掃描 |


## 2026-11-05 複查（雲端上線品質整理）

環境：Linux 雲端容器，碰不到本機 LINE、機器人、Ollama；需要外部服務的部分一律用本機假 LINE（`REA_LINE_API_BASE` 指向假 API）與合成資料。

### 第 2 道 程式本身
| 項目 | 指令 | 結果 |
|---|---|---|
| 全新安裝 | 乾淨 `git clone` → `python -m venv` → `pip install -r requirements-server.txt` | ✅ 成功（waitress 3.0.2） |
| 全部測試（修正前） | `python -m unittest discover -s tests -p "test_*.py"` | 384 項全過（Python 3.10／3.11／3.12／3.13／3.14） |
| 全部測試（修正後） | 同上，乾淨 clone | **400 項全過**（5 個版本都過；新增 16 項回歸測試） |
| 其他自檢 | `validate_skills.py`、`validate_cards.py`、`pii_scan.py --all` | 36 skills 通過；61 種回覆 0 問題；pii_scan 通過 |
| 示範腳本 | `self_test_product.py`、`demo_line_intake.py`、`demo_w1_push.py`、`node tools/test_web_demo.cjs` | 全部 PASS |
| 相依套件漏洞 | `pip-audit -r requirements-server.txt` | No known vulnerabilities found |
| 靜態檢查 | `pyflakes core adapters web tools` | 只剩 3 個無害警告（沒用到的區域變數、迴圈變數遮蔽 import），不影響行為 |

### 本次找到並修好的問題（每項都有「修正前失敗、修正後通過」的回歸測試）
| # | 嚴重度 | 問題 | 重現 | 修正 | 測試 |
|---|---|---|---|---|---|
| 1 | 🔴 安全 | 還沒設 `REA_ADMIN_USERS` 時，**任何陌生人**按「同意並開始」都能加入（程式註解寫「第一個人」，實作是所有人）。只用環境變數的雲端／Docker 部署會一直開著 | Docker 容器＋假 LINE：第 2 位陌生人也收到「✅ 開始使用！」、`signups.json` n=2 | 沒設管理員時，只有「還沒有任何人加入」或「精靈管理員碼有效中」才放行（`adapters/line/shared.py`、`web/setup_claim.py`）。修正後容器內第 2 位收到「只開放受邀」、n=1 | `test_review_hardening.py` 2 項 |
| 2 | 🔴 資料 | Google 試算表每日同步會把 LINE「新增物件」加的物件全部**下架** | LINE 加 M001 → 同步試算表 → M001 `online=False` | 只下架同一來源帶進來的物件（`adapters/csv/listing_source.py`） | `test_sheet_sync_keeps_line_edits.py` |
| 3 | 🔴 資料 | 試算表同步會把 LINE 上**暫停的客人改回啟用**（又開始推播），並蓋掉 LINE 改過的需求（車位、預算區間） | 暫停＋改需求 → 試算表沒動、隔天同步 → `status=active`、車位要求消失 | 試算表那一列沒變就保留 LINE 的修改；試算表沒填狀態就沿用原狀態（`adapters/csv/customer_source.py`） | 同上 2 項 |
| 4 | 🟠 功能 | 試算表／CSV 匯入的物件（編號像 S-001），卡片上「配對／物件／下架」按鈕**完全沒反應** | 「配對 S-001」→ 沒有回覆 | 編號改成也認英數編號，小寫也找得到（`adapters/line/listing_intake.py`） | `test_listing_match_flow.py` |
| 5 | 🟠 功能 | 新增買方打字區域：「新竹縣竹北市」「嘉義縣」被認成新竹市／嘉義市；「桃園市中壢區、桃園區」「苗栗縣 苗栗市」被當成新縣市 → 都被拒絕 | 「新竹縣竹北市」→「新竹市沒有縣竹北市這個區」 | 先比對同縣市的區、再比完整縣市名、最後才用兩字簡寫（`adapters/line/customer_intake.py`） | `test_intake_typed_input.py` 4 項 |
| 6 | 🟠 功能 | 租屋預算按鈕「6萬以上」**永遠被擋**（預算要有上限） | 點按鈕 →「預算要有上限」，卡在同一題 | 改成「6-10萬」；並測試每一個預算按鈕都收得下 | `test_intake_typed_input.py` |
| 7 | 🟠 個資 | 客戶匯入的稱呼欄含電話也照收（違反「電話不收」） | 稱呼「合成客戶＋電話」→ 存進去，之後改需求還會失敗 | 稱呼含電話／email 就不收，客人照樣匯入並列出問題 | `test_csv_import_hardening.py` |
| 8 | 🟡 防呆 | 沒有稱呼欄的客人「修改需求」→ 顯示並存成文字「None」 | 確認畫面「A001｜None」 | 顯示與儲存為「未命名」 | 同上 |
| 9 | 🟡 防呆 | 預算下限比上限高的客人被靜默匯入，之後永遠配不到 | 1500／1200 → 匯入 OK、配對 0 | 列為問題列並白話說明 | 同上 |
| 10 | 🟡 白話 | 不存在的日期（2 月 30 日、13 月）匯入報告出現英文錯誤 | `day is out of range for month` | 「日期不存在：…（請確認月份和日期）」 | 同上 |
| 11 | 🟡 白話 | 串接精靈畫面會直接顯示 `bad request`／`not found`／`too large` | 貼超長內容 → 畫面「✗ too large」 | 改成「發生什麼事＋怎麼修」的中文 | `test_setup_wizard.py` |

### 第 3、5 道 實機（本機假 LINE，簽章 webhook）
| 項目 | 結果 |
|---|---|
| `tools/serve_line.py` 啟動 | `/healthz` 200（`setup-needed`）、`/terms` 200、`/setup` 沒進入碼 403、`/admin/` 沒串 LINE 503、webhook 沒串 LINE 503 |
| 串接精靈畫面（Playwright，1280px 與 375px 手機寬度） | console 0 錯誤、沒有橫向捲動；`/setup/api/status` 不含 secret／token |
| Docker 容器：簽章 webhook | 正確簽章 200、壞簽章 403；回覆送到假 LINE |
| Docker 容器：只限受邀 | 修正前第 2 位陌生人可加入 ❌ → 修正後被擋 ✅ |
| Docker 容器：金鑰不落檔 | 掃 `/data` 全部檔案，不含 channel secret ✅ |

### 第 7 道 交付版本
| 項目 | 結果 |
|---|---|
| Docker | ✅ `docker build` 成功（雲端需另帶代理憑證，屬測試環境限制，不改 `Dockerfile`）；容器以 uid 10001 非 root 執行；`/healthz`、`/terms`、`/setup`（403）、`/admin/` 行為與本機一致。README 由 🟡 改 ✅ |
| 去識別化 | ✅ 全部追蹤檔：手機號碼（作者公開客製化電話除外）、email（noreply 除外）、LINE userId、金鑰樣式、身分證樣式 **0 命中**；唯一圖片 `assets/richmenu.png` 無 EXIF／GPS；作者信箱全部 noreply；本機識別字清單逐一搜尋 0 命中（清單內容不寫入本紀錄）。客製化 LINE／電話廣告依店長指示**刻意保留** |
| 本次新增測試資料 | 全部合成（「合成客戶甲」、`synthetic_line_id()`、非手機格式的假號碼），`pii_scan` 通過 |

### 沒做完／已知限制（11/05）
1. 真實 LINE／Google 試算表／搜尋服務／地政平台成功路徑仍未實測（雲端沒有真帳號；用假 LINE 代替）。
2. Windows 專屬項目（`pythonw` 不跳視窗、DPAPI、cp950 主控台、`.vbs` 啟動器）這次在 Linux 上無法實測，沿用 10/24、10/27 結果。
3. 已存在的客戶資料：第一次同步時還沒有「試算表列指紋」，若店長之前在 LINE 改過試算表客人的需求，升級後第一次同步仍可能被試算表蓋過一次（之後就會保留）。暫停狀態不受影響（試算表沒填狀態就沿用）。
4. 3 個 pyflakes 無害警告沒清（不影響行為，避免動到不相關的程式）。
