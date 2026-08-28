#!/usr/bin/env python3
"""audit_registry_certik：CertiK Skynet「最近審計」清單 adapter（track-crypto，batch6／A5）。

對應規格：/Users/monica/Documents/temp/終端機/vps-161.97.82.83/adapters-wip/specs/batch6.md 6-C

**範疇裁示（本輪自行決定，理由如下）**：
    規格書明確要求「先花少量時間確認正文是否可解析，若確認需要 JS，直接移出本批」。
    本輪實測結果**一半一半**，比規格書猜測的更複雜：
    1. 首頁的 Next.js hydration 資料（`<script id="__NEXT_DATA__">` 內的 `pageProps._e`）
       是用 AES 加密後再 base64 編碼（開頭固定 `U2FsdGVkX1`，即 OpenSSL "Salted__" 標記），
       只用標準函式庫無法解密，**這部分確認需要 JS（前端解密邏輯）**，符合規格書的疑慮。
    2. 但首頁 DOM 本身（Next.js SSR 輸出的原始 HTML，在 hydration 之前）**確實已經內嵌了
       一段「Recently Audited」清單的純文字**（專案代號、名稱、審計日期），不需要執行 JS
       就能從原始回應直接用正則表達式擷取到。這段清單本輪實測固定為 8 筆。
    3. `robots.txt` 的 `Disallow: /api/` 證實：若要拿到完整審計資料庫（分頁、篩選、歷史全量），
       確實需要走 `/api/`（被 Disallow）或執行 JS 解密 `__NEXT_DATA__`，兩條路都不可行。

    **本輪決定**：只實作「Recently Audited」首頁清單這個窄範圍（每次抓取約 8 筆最新審計案，
    不是 CertiK 完整審計資料庫），誠實在 DESC 與回傳資料中標註這個限制。
    這是規格書原本「信心最低、可能整批移出」的一項中，實際驗證後找到的**部分可行**方案，
    而不是全有全無。

只用 Python 標準函式庫（re + hashlib）。不落地整頁原始 HTML（793KB 過大且多數是不相干的
交易價格等揮發性內容），只保留「Recently Audited」清單本身。
"""

import hashlib
import re

KEY = "audit_registry_certik"
DESC = "CertiK Skynet 首頁「Recently Audited」最新審計清單（僅約 8 筆，非完整審計資料庫，見模組說明）"
PARSER_VERSION = 1
SOURCE_HOME = "https://skynet.certik.com/"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗 https://skynet.certik.com/robots.txt：HTTP 200，"
    "User-agent: * 為 Allow: /，但 Disallow: /api/、/my/、/mobile/；"
    "本 adapter 只抓首頁 / 本體，未觸碰 /api/"
)

MIN_ITEMS = 3

_ROW_RE = re.compile(
    r'<a href="/projects/([^"]+)">.*?title="([^"]+)">\2</div>.*?'
    r'text-secondary">([A-Za-z]{3} \d{1,2})</div></div></a>',
    re.S,
)


def collect(fetch) -> dict:
    """抓取 CertiK Skynet 首頁的「Recently Audited」清單。

    fetch(url, headers=None, timeout=45) 回傳原始 HTML 字串（未解析）。
    失敗一律讓例外往上拋，不吞例外、不回傳空資料。
    """
    html = fetch(SOURCE_HOME, headers={"Accept": "text/html"})
    if not isinstance(html, str) or len(html) < 50000:
        got = len(html) if isinstance(html, str) else 0
        raise RuntimeError(f"audit_registry_certik：回應僅 {got} 位元組，明顯過短，視為失敗")

    idx = html.find("Recently Audited")
    if idx == -1:
        raise RuntimeError(
            "audit_registry_certik：找不到「Recently Audited」區塊標題，首頁版面可能已改版"
        )
    # 只在標題後一段固定範圍內找列表（避免正則吃到後面不相干的區塊），
    # 若後面剛好有下一個 <h1> 就以此為界，否則退回固定長度上限。
    idx2 = html.find("<h1", idx + 2000)
    seg = html[idx: idx2] if idx2 != -1 else html[idx: idx + 20000]

    rows = _ROW_RE.findall(seg)
    if len(rows) < MIN_ITEMS:
        raise RuntimeError(
            f"audit_registry_certik：僅解析到 {len(rows)} 筆「Recently Audited」項目，"
            f"低於驗收下限 {MIN_ITEMS}，版面可能已改版"
        )

    slugs = [r[0] for r in rows]
    if len(set(slugs)) != len(slugs):
        raise RuntimeError(f"audit_registry_certik：projects slug 有重複：{slugs!r}")

    items = [
        {"slug": slug, "name": name, "audited_date_text": date}
        for slug, name, date in rows
    ]
    payload_text = "|".join(f"{i['slug']}:{i['audited_date_text']}" for i in items)

    return {
        "count": len(items),
        "recently_audited": items,
        "payload_sha256": hashlib.sha256(payload_text.encode()).hexdigest(),
        "coverage_note": (
            "僅為 CertiK Skynet 首頁「Recently Audited」小工具的最新約 8 筆，"
            "不是完整審計資料庫（完整資料庫走 /api/，被 robots.txt Disallow，"
            "且首頁 hydration 用的 __NEXT_DATA__ JSON 為 AES 加密，須執行 JS 才能解密）"
        ),
    }
