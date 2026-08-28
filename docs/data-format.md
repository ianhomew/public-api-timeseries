# 資料格式與讀取方式

回上層：[README](../README.md)　｜　相關：[sources.md](sources.md)

## 目錄結構

```
public-api-timeseries/
├── track-crypto/
│   ├── data/
│   │   ├── x402_bazaar/YYYY-MM-DD.json.gz
│   │   ├── cex_symbols/YYYY-MM-DD.json.gz
│   │   ├── vast_gpu/YYYY-MM-DD.json.gz
│   │   ├── mcp_registry/YYYY-MM-DD.json.gz      （已停抓，保留歷史）
│   │   ├── cex_events/events.jsonl              （上/下架事件流，只追加）
│   │   └── _manifest/YYYY-MM-DD.json
│   └── scripts/snap_crypto.py
├── track-gov/
│   ├── data/
│   │   ├── fsc_clarification/YYYY-MM-DD.json.gz
│   │   └── _manifest/YYYY-MM-DD.json
│   └── scripts/snap_gov.py
├── scripts/                 共用工具
├── timestamps/              OpenTimestamps 時間戳
├── changes/                 變動 diff（有變動才產生）
├── CHANGES.md               變動累積索引（有變動才產生）
└── ALERT.md                 自我檢查異常（有異常才產生）
```

## 檔名規則

| 樣式 | 意義 |
|---|---|
| `YYYY-MM-DD.json.gz` | 當日快照。日期為 **UTC**。 |
| `YYYY-MM-DDTHHMMSS.json.gz` | 同一 UTC 日內第二次抓取且內容不同時另存，**不覆蓋**原檔。時戳為 UTC。 |
| `YYYY-MM-DD.stats.json` | 由 `scripts/explore.py --build-cache` 產生的統計快取，非原始資料。 |

排程時間使用**台北時間**，檔名日期使用 **UTC**，兩者不可混寫。

## 快照 JSON 結構

每份 `*.json.gz` 解壓後為單一 JSON 物件：

```json
{
  "_meta": {
    "source": "x402_bazaar",
    "fetched_at": "2026-08-27T09:07:49.690862+00:00",
    "license": "CC BY 4.0"
  },
  "data": { }
}
```

`_meta.fetched_at` 為 ISO 8601、UTC。`data` 為該來源的原始回應，未經改寫。

各來源 `data` 的頂層形狀：

| 來源 | `data` 結構 |
|---|---|
| `x402_bazaar` | `{"x402Version":…, "total":N, "items":[…]}` |
| `cex_symbols` | `{"exchanges":{"bybit":…,"okx":…,…}, "errors":{}}`，每家保留各自原始回應 |
| `vast_gpu` | vast.ai 原始回應，另加 `_authenticated`（布林） |
| `mcp_registry` | `{"total":N, "servers":[…]}` |
| `track-gov` 各來源 | `{"_meta":{…}, "total":N, "errors":{}, "items":[…]}`，每筆含 `id`、`url`、`title`、`date`、`body_text`、`body_sha256`（`fsc_clarification` 另有 `dataserno`） |

> ⚠️ **兩軌的巢狀層級不同**：`track-crypto` 的內容在 `snap["data"]` 之下；
> `track-gov` 的 `items` 直接在**頂層**，沒有 `data` 這一層。

## manifest 結構

`_manifest/YYYY-MM-DD.json` 記錄當日各來源成敗，體積小，可證明排程確實執行：

```json
{
  "date": "2026-08-27",
  "fetched_at": "2026-08-27T09:07:49.690862+00:00",
  "sources": {
    "x402_bazaar": {"ok": true, "bytes": 6045267, "secs": 52.4},
    "cex_symbols": {"ok": true, "bytes": 407121, "secs": 12.6},
    "vast_gpu":    {"ok": true, "bytes": 174956, "secs": 1.8}
  }
}
```

`track-gov` 的 manifest 使用 `channels` 而非 `sources`，並多一個 `n`（筆數）與 `errors` 欄位。

## 讀取範例

### Python

```python
import gzip, json

with gzip.open("track-crypto/data/x402_bazaar/2026-08-27.json.gz", "rt", encoding="utf-8") as f:
    snap = json.load(f)

print(snap["_meta"]["fetched_at"])       # 2026-08-27T09:07:49.690862+00:00
print(snap["data"]["total"])             # 14755
print(snap["data"]["items"][0])
```

### 比對兩日的政府公告 hash

```python
import gzip, json

def load(path):
    # 注意：track-gov 的 items 在頂層，沒有 "data" 這一層
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return {i["id"]: i for i in json.load(f)["items"]}

a = load("track-gov/data/fsc_clarification/2026-08-27.json.gz")
b = load("track-gov/data/fsc_clarification/2026-08-28.json.gz")

for k in a.keys() & b.keys():
    if a[k]["body_sha256"] != b[k]["body_sha256"]:
        print("改寫:", a[k]["title"], a[k]["url"])
for k in a.keys() - b.keys():
    print("消失:", a[k]["title"])
```

### 命令列

```bash
python3 scripts/explore.py                                        # 各來源檔案數、日期範圍、大小
python3 scripts/explore.py fsc_clarification                      # 列出該來源所有日期
python3 scripts/explore.py fsc_clarification 2026-08-27 -n 5      # 預覽 5 筆樣本
python3 scripts/explore.py --diff fsc_clarification 2026-08-27 2026-08-28
```

> ⚠️ **只有 clone 這個 repo 的人**：`track-crypto` 的資料檔**不在 GitHub 上**（見 `.gitignore`），
> 所以 `explore.py x402_bazaar`、`explore.py vast_gpu` 對你會顯示查無資料，這是預期行為。
> GitHub 上可用的是 `track-gov` 全部資料、兩軌的 `_manifest`、時間戳與程式碼。

## 授權

資料 **CC BY 4.0**，程式碼 **MIT**。使用資料時請標示來源。
