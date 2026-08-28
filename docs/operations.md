# 運作方式

回上層：[README](../README.md)　｜　相關：[methodology.md](methodology.md)

## 排程

VPS 時區為 `Asia/Taipei`（UTC+8）。下列時間皆為**台北時間**。

| 台北時間 | 動作 | 指令 |
|---|---|---|
| 09:00 | 抓取 `track-crypto` | `track-crypto/scripts/snap_crypto.py` |
| 09:30 | 抓取 `track-gov`（11 個機關，約 58 分鐘） | `track-gov/scripts/snap_gov.py` |
| 11:30 | 統計快取 → 變動偵測 → 事件流 → 時間戳 → 里程碑 → 自我檢查 → commit → push → 死人開關 | `scripts/push.sh` |

三個排程共用一把 `flock` 鎖（`~/snap/.lock-snap`）：抓取進行中時 push 會等待（最多 2 小時），
避免「抓到一半就被提交」的競態。抓取腳本以 `python3 -u` 執行，否則 stdout 緩衝會讓
`cron.log` 在程式結束前一直是空的（出事時無日誌可查）。

檔名使用的是該時刻的 **UTC 日期**。台北 09:00 等於 UTC 01:00，同日。

## 每日提交流程（`scripts/push.sh`）

1. `explore.py --build-cache` — 更新 `*.stats.json` 統計快取。
2. `detect_changes.py` — 比對最近兩份快照，偵測改寫與下架。
3. `cex_events.py` — 萃取交易所上／下架事件到 `track-crypto/data/cex_events/events.jsonl`。
4. `stamp.py` — OpenTimestamps 蓋章。
5. `milestone.py` — 里程碑檢查。
6. `healthcheck.py` — 自我檢查，產生或刪除 `ALERT.md`。
7. `git add -A` → commit → `git push origin main`。

commit 作者固定為 `vps-snapshotter <snapshotter@users.noreply.github.com>`。

commit 標題：

| 情況 | 標題 |
|---|---|
| 一般 | `data: YYYY-MM-DD 每日快照 (N 檔變更)` |
| 偵測到變動 | `[ALERT] YYYY-MM-DD 偵測到內容改寫 N 筆、下架 M 筆` |

在 GitHub 按 **Watch → All Activity** 即可用 email 收到通知。

## 死人開關（dead-man's switch）

`ALERT.md` 有一個先天限制：它要**推上 GitHub** 你才看得到。
如果壞掉的正好是 push 本身，或整台 VPS 當機、斷網、被停機，
**不會有任何警報產生** —— 壞掉和一切正常看起來一模一樣。

因此每日流程結束時會 ping 一次外部服務（healthchecks.io）：

| 情況 | 動作 |
|---|---|
| 流程開始 | ping `/start` |
| 全部成功且無 `ALERT.md` | ping 成功 |
| 任一步驟失敗、push 失敗 | ping `/fail` |
| push 成功但存在 `ALERT.md` | ping `/fail`（讓使用者收到通知） |
| **VPS 當機／斷網／cron 沒跑** | **什麼都不 ping → 外部服務逾時後主動通知** |

計時器在**外部**，不在 VPS 上，所以整台機器消失也能被發現。
ping 網址等同一把權杖，存放在 `~/snap/.env` 的 `HC_PING_URL`（已被 `.gitignore` 排除），
不寫進這個公開 repo。

## 自我檢查：`ALERT.md`

`scripts/healthcheck.py` 每日檢查下列項目，任一項異常就在 repo 根目錄產生 `ALERT.md`；
異常排除後自動刪除。

| 檢查 | 判準 |
|---|---|
| 缺檔 | 今日（UTC）沒有新快照 |
| 體積異常 | 今日體積不在前 7 日中位數的 **0.5×–3.0×** 區間 |
| manifest 失敗 | 當日 manifest 中有來源 `ok: false` |

檢查名單：`track-crypto` 為寫死的 `ACTIVE_CRYPTO`（`x402_bazaar`、`cex_symbols`、`vast_gpu`），
停抓的來源要從該清單移除，否則會持續誤報；`track-gov` 則自 `track-gov/adapters/*.py`
**自動探索**，新增機關不必改程式。

### 三種告警檔

| 檔案 | 意義 |
|---|---|
| `ALERT.md` | 資料異常：缺檔、體積異常、manifest 有來源失敗 |
| `ALERT-DETECT.md` | **變動偵測程式本身失敗** —— 當日沒有做改寫／下架比對 |
| `ALERT-HEALTH.md` | **自我檢查程式本身失敗** —— 當日沒有做資料異常檢查 |

後兩者是「監控自己壞掉」的情況。若不特別處理，程式崩潰會被當成「沒有異常」，
核心功能失效的那一天剛好也是最不會被發現的一天。
任一告警檔存在時，死人開關一律 ping `/fail`。

排查順序：`crontab -l` → `track-*/logs/cron.log` → 手動執行 snapshotter。

> 2026-08-27（UTC）曾因 `vast_gpu` 改用金鑰認證、筆數由 64 增為 512，觸發體積異常告警。
> 這是預期中的變化，不是抓取失敗。

## 變動偵測

`scripts/detect_changes.py` 自 `track-gov/adapters/*.py` 自動探索來源，
**目前涵蓋全部 11 個機關**（皆有 `body_text` 與 `body_sha256` 欄位）。

| 事件 | 判斷方式 | 是否留紀錄 |
|---|---|---|
| 內容改寫 | 同一 `id` 的 `body_sha256` 改變 | 是 |
| 下架 | 前一日存在、今日消失 | 是 |
| 新增 | 今日新出現 | 否 |

比對規則：
- 同一 UTC 日期若有多份快照（重跑產生），**只取當日最後一份**。
- 兩份快照的 `_meta.parser_version` 不同時**跳過比對**。
  解析器改版會讓整批 `body_sha256` 改變，那是我方程式變更，不是機關改寫公告。

有變動才產生 `changes/<source>/YYYY-MM-DD.md`（標準 unified diff，格式同 `git diff`）
與累積索引 `CHANGES.md`。截至 2026-08-27（UTC）尚未偵測到任何改寫或下架，
因此這兩個路徑尚未產生。

## 交易所事件流

`scripts/cex_events.py` 逐日比對 `cex_symbols` 快照，把差異寫入
`track-crypto/data/cex_events/events.jsonl`（只追加）：

```json
{"date":"2026-08-27","exchange":"bybit","symbol":"XXXUSDT","event":"DELISTED","from":"Trading","to":null}
```

`event` 為 `LISTED` / `DELISTED` / `STATUS_CHANGED`。
需累積兩份以上快照才會產生輸出。

## 里程碑

`scripts/milestone.py` 依累積天數自動在 repo 根目錄產生 `NEXT-STEP.md`：

| 天數 | 待辦 |
|---|---|
| 90 | 上傳 `track-crypto` 到 Hugging Face Datasets |
| 180 | 檢視是否有人引用；是否申請 g0v / NLnet 補助 |
| 365 | 一年檢查點：是否出現陌生人重複使用 |

未達門檻時不產生該檔。2026-08-27（UTC）累積 2 天。

## 資料保存位置

| 內容 | GitHub | VPS |
|---|---|---|
| `track-gov` 資料 | 有 | 有 |
| `track-crypto` 資料 `*.json.gz` | **無**（見 `.gitignore`） | 有 |
| `_manifest`、`*.stats.json` | 有 | 有 |
| `timestamps/` | 有 | 有 |
| `logs/` | 無 | 有 |

`track-crypto` 原始資料保存於 VPS `~/snap/public-api-timeseries/track-crypto/data/`，
累積後再發布到資料集平台。
