# selftest.py — 離線回歸自測

## 這是什麼

`scripts/selftest.py` 是**離線、唯讀、可重複執行**的回歸自測，涵蓋本專案 5 支關鍵程式的
核心保護機制：

| 程式 | 涵蓋的不變量 |
|---|---|
| `scripts/detect_changes.py` | 解析器版本不同時跳過比對／截斷時不判定下架／滾動視窗尾端移出不算下架／揮發性欄位不進正文比對（實作於 `track-gov/scripts/snap_gov.py`，見下方「歸屬澄清」） |
| `track-crypto/scripts/detect_delistings.py` | 完整性守門（`total != len(items)` 要跳過）／熔斷門檻／`REAPPEARED` 判定／`RENAMED` 上游改名抵銷與事件寫入（含新舊主鍵方向）／冪等性（同區間重跑零新事件） |
| `scripts/cex_events.py` | 每日只取最後一份／交易所級失敗守門／異常規模熔斷註記 |
| `scripts/healthcheck.py` | 連續截斷告警 N=2／排程寬限（排程未到不算缺檔） |
| `scripts/daily_report.py` | 42 個來源全列（不漏列）／異常數與 `ALERT.md` 一致 |

（另有 1 條 `selftest.workdir_cleanup_guard` 檢查，2026-09-08 新增，測試對象是
`scripts/selftest.py` 自己的 WORKDIR 自清安全防呆，不屬於上述 5 支正式程式，
見下方「WORKDIR 自清」一節。）

**它不是**「跑一次歷史資料看有沒有報錯」的煙霧測試。每一條不變量都有對應的合成測試資料，
故意打造「截斷」「來源失敗」「同日重跑」「暫時消失又恢復」這類情境，斷言保護機制**確實會被觸發**——
這比只看歷史資料更能防回歸（詳見 `docs/selftest-report.md` 的「驗證要求」章節）。

## 怎麼跑

在 repo 根目錄（`selftest.py` 的上上層目錄）直接執行：

```bash
python3 scripts/selftest.py
```

不需要任何參數或環境變數。全程唯讀正式程式碼與 `adapters/*.py`／少數幾份既有歷史快照，
所有輸出（合成快照、程式副本、沙盒執行結果）都寫在 `/tmp/selftest/run-<時間戳記>-<pid>/`，
不會寫到任何正式目錄，不連外網。**全數 PASS 時，執行結束會自動清掉這個 WORKDIR**；
有 FAIL 時保留供除錯；`SELFTEST_KEEP=1` 可強制保留（不論成敗），見下方「WORKDIR 自清」
一節。耗時隨檢查數量增加持續成長，**2026-09-09 正式目錄實測 160 條 37.4s**（2026-09-08 的
138 條 44.3s、132 條 41.6s、130 條 40.2s，早期 86 條 15.6s、19 條約 3～5 秒為歷史數字，
僅供對照成長趨勢，請以最新實測為準），仍遠低於 2 分鐘預算。

可用旗標：
- `--filter <關鍵字>`：只跑名稱包含這個關鍵字的檢查（開發單一項目時用），例如
  `python3 scripts/selftest.py --filter detect_changes`。
- `--list`：只列出所有登記的檢查名稱，不執行。

可用環境變數（一般用不到，除錯或在非標準位置跑才需要）：
- `SELFTEST_SOURCE_REPO`：要測試的目標 repo 根目錄，預設＝本檔案往上一層（部署在
  `<repo>/scripts/selftest.py` 時的正常位置）。**只會被讀取**，不會被寫入。
- `SELFTEST_WORKDIR`：本檔所有輸出的根目錄，預設 `/tmp/selftest/run-<時間戳記>-<pid>`。
- `SELFTEST_SKIP_MUTANTS=1`：只跑「正常檢查」，略過「破壞驗證」（見下）。一般不需要設定，
  兩者一起跑也在秒級完成；只有在單獨除錯某條「正常檢查」、想先排除破壞驗證的雜訊時才用。
- `SELFTEST_KEEP=1`：不論全數 PASS 或有 FAIL，一律保留 WORKDIR（見下方「WORKDIR 自清」
  一節）。全數 PASS 但想留著手動核對沙盒內容時才需要設定，一般不用。

## WORKDIR 自清（2026-09-08 新增）

`scripts/selftest.py` 每次執行都會在 `SELFTEST_WORKDIR`（預設 `/tmp/selftest/
run-<時間戳記>-<pid>`）底下建立合成快照、程式副本與沙盒執行結果。**2026-09-08 之前
無論成敗都不清理**，長期是 `/tmp` 累積量最大的單一來源（見 `docs/0907-G-tmp-cleanup.md`
估計佔比 55%、`docs/0908-2-alert-selftest-report.md` 的實測驗證）。

現行規則：

| 情況 | 行為 |
|---|---|
| 全數 PASS | 執行結束自動 `shutil.rmtree(WORKDIR)`，並印一行 `WORKDIR 已清除（全數 PASS）：...` |
| 有 FAIL | WORKDIR **保留**，供除錯，並印一行 `WORKDIR 保留（有 FAIL，供除錯）：...` |
| `SELFTEST_KEEP=1` | 不論全數 PASS 或有 FAIL，**一律保留**，印一行 `WORKDIR 保留（SELFTEST_KEEP=1 強制保留）：...` |

安全設計（`_workdir_is_safe_to_delete()`，`scripts/selftest.py` 檔案尾端）：自動清除前會先
做四層唯讀防呆判斷——路徑正規化失敗／為空／等於 `/` 一律拒絕；命中系統目錄黑名單
（常見掛載點、家目錄，**含 `/tmp` 本身**）一律拒絕；路徑深度 `< 2` 層一律拒絕；**不是以
`/tmp/` 開頭一律拒絕**。四關都通過、且該路徑確實是既存目錄，才會呼叫 `shutil.rmtree()`。
任何一關不過就整個放棄刪除（寧可少清，不可誤刪），並在輸出說明放棄的原因，不會靜默略過。
這道防呆本身有 1 條自測鎖住（`selftest.workdir_cleanup_guard`，含 `#mutant`），
只驗證「決策」不驗證「危險情況下的動作」——即使防呆被破壞驗證刻意拆掉，也絕對不會真的
對 `/etc`、`/` 這類系統路徑呼叫 `shutil.rmtree()`，細節見該檢查的 docstring。

若要保留 WORKDIR 手動核對沙盒內容（例如 `sandbox-NNN-*/` 底下的 `changes/*.md`、
`ALERT.md`、`events.jsonl` 等實際產生的檔案），設定 `SELFTEST_KEEP=1` 即可，不必等到
剛好有檢查 FAIL。

## 輸出怎麼看

每一行是一項檢查的結果：

```
PASS  detect_changes.truncation_skips_removed        skip_removed=True removed=0 rolled=0 (...)
FAIL  detect_delistings.breaker_threshold             removed_rate=30.0% judged=NORMAL (...)
```

- `PASS`／`FAIL` 後面是檢查名稱，再後面是這次實測的具體數字（不是空話，出錯時直接看得到
  「實際發生了什麼、跟預期差在哪」，不需要重新加 print 才能除錯）。
- 名稱以 **`#mutant`** 結尾的行，是「破壞驗證」，不是又發現了一個新問題：它的意思是
  「對這條保護機制的暫存副本動了一個最小的定向修改（關掉那一條保護），用同一組資料重跑」。
  這一行要 **PASS** 才代表「如果哪天這條保護真的被誤刪或改壞，selftest 真的會發現」；
  如果這一行 **FAIL**，代表 selftest 本身這條檢查是鈍的（破壞了保護機制卻沒被抓到），
  需要修檢查邏輯本身，跟正式程式碼有沒有 bug 是兩回事。
- 名稱以 **`.real_replay`** 結尾的行，用的是既有真實歷史快照（唯讀複製，日期固定，
  不是「最近 N 天」這種會隨時間漂移的窗口），核對「這次改動有沒有破壞任何已知的真實案例」；
  沒有 `.real_replay` 後綴、直接用 2030 年日期的合成資料的行，才是專門設計來**保證**
  觸發到保護機制邊界情況（例如「連續 2 天」跟「只有 1 天」的差別）的檢查——兩者互補，
  real_replay 不保證涵蓋所有邊界情況（真實資料不一定剛好出現過），合成資料則不保證
  「跟正式資料的實際規模/分布一致」，兩者都跑才放心。
- 最後一行 `SUMMARY total=N pass=N fail=N elapsed=X.Xs`：任一項 FAIL，結束碼非 0
  （可以直接接到 CI／pre-commit：`python3 scripts/selftest.py || echo "有回歸，不要部署"`）。

### 失敗時怎麼判讀

1. 先看是哪一類行 FAIL：
   - 一般行（無後綴）FAIL → **現在的正式程式碼**在這條不變量上壞了，去看 detail
     欄位裡的實際數字，對照檢查函式（`scripts/selftest.py` 裡同名的 `chk_*` 函式）
     期望什麼，通常一看就知道是哪一步邏輯跑掉了。
   - `.real_replay` 行 FAIL、但同一條不變量的一般行 PASS → 現在的程式碼在**合成邊界情況**
     下是對的，但重放**既有真實歷史快照**時结果變了。先確認是不是正式資料檔案本身被
     移動/改了（不應該，正式資料唯讀累積），再確認是不是程式邏輯有「合成測試沒覆蓋到、
     但真實資料剛好踩到」的角落案例。
   - `#mutant` 行 FAIL → 這條保護機制的「正常」行為現在測不出問題（PASS），但破壞驗證
     沒抓到被破壞的版本，代表這條檢查邏輯本身不夠敏感，需要加強斷言或合成資料設計，
     不代表正式程式碼有 bug。
2. 到 `SELFTEST_WORKDIR`（預設印在輸出開頭 `WORKDIR = ...`）底下對應的 `sandbox-NNN-*/`
   目錄，可以直接看到那次執行實際產生的檔案（`changes/*.md`、`ALERT.md`、`ALERT-DELIST.md`、
   `events.jsonl`、`REPORT.md`……），比對合成資料（同目錄下的 `*.json.gz`）逐步重現問題。

## 怎麼加新檢查

1. 在檔案上方對應程式的區塊，寫一個 `def chk_xxx(is_mutant): ...`，回傳
   `Result(guard_active: bool, detail: str)`。`is_mutant` 這個參數只用來決定「要用哪一份
   原始碼」，斷言邏輯本身兩種模式共用同一段，不要分支寫兩套。
2. 如果這條不變量可以用「關掉某一行/某個條件」重現壞掉的行為，寫一個
   `mut_xxx(text)`，用 `apply_mutation(text, "唯一錨點文字", "替換後文字", "標籤")`
   ——`apply_mutation` 會在錨點文字找不到或不唯一時直接丟例外（代表正式程式碼已經改版，
   錨點文字要跟著更新），不要吞掉這個例外。
3. 用 `@check("程式名.這條不變量的名字", mutate_target="程式代稱", mutate=mut_xxx)`
   裝飾這個函式，登記進檢查清單（不需要手動維護清單，裝飾器自動註冊）。
   如果暫時想不到怎麼破壞測試（例如純粹的 real-replay 煙霧測試），
   `mutate=None` 也可以，只是不會有 `#mutant` 那一行。
4. 合成資料請用本檔既有的 `gov_item()`／`gov_snapshot()`（track-gov 格式）、
   `x402_item()`／`x402_snapshot()`（x402_bazaar 格式）、`cex_snapshot()`（cex_symbols
   格式）等 helper，欄位名稱已核對正式資料 schema；日期一律用 **2030 年**這類一望即知
   是合成資料的年份，不要用可能跟真實資料撞期的日期。
5. 跑 `python3 scripts/selftest.py --filter 你的新檢查名稱` 確認正常檢查 PASS、
   破壞驗證也 PASS（代表兩種模式都如預期），再跑一次完整的
   `python3 scripts/selftest.py` 確認沒有把既有檢查跑壞或拖慢（時間預算 2 分鐘）。

## 歸屬澄清（推論標示）

「揮發性欄位不進正文比對」這條不變量，實際實作在 `track-gov/scripts/snap_gov.py` 的
`strip_volatile()`（寫入快照前，先從 `body_text` 剔除「瀏覽人次」這類行才計算
`body_sha256`），不在 `detect_changes.py` 本身——`detect_changes.py` 只單純比對
已經算好的 `body_sha256`。本檔仍把這條列在 `detect_changes.py` 的不變量清單下（沿用
`SPEC-selftest.md` 的分類），因為這是使用者實際會觀察到「detect_changes.py 有沒有
誤報改寫」的地方；檢查本身同時串接 `snap_gov.normalize()` 與 `detect_changes.compare()`
兩支程式，破壞驗證也是對 `snap_gov.py` 動刀，不是對 `detect_changes.py` 本身。

## 硬性限制（本檔設計時已內建遵守）

- 只寫入 `SELFTEST_WORKDIR`（預設 `/tmp/selftest/...`），從不寫入 `SELFTEST_SOURCE_REPO`
  指向的任何路徑（包含正式部署位置本身）。
- 不連外網：全程只讀本機檔案、寫本機檔案、以子行程呼叫本機 `python3`。
- 不需要任何套件：只用 Python 標準函式庫（比照本專案其餘程式的既有慣例）。
