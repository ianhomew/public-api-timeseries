#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""payment_pricing_pages：加密支付通道費率頁 adapter（track-crypto，batch6／B10，僅 Circle）。

對應規格：/Users/monica/Documents/temp/終端機/vps-161.97.82.83/docs/track-crypto-round2-spec.md
          6-D（B10：加密支付通道費率頁，僅 Circle，建議命名 payment_pricing_pages）；
          派工規格：/Users/monica/Documents/temp/終端機/vps-161.97.82.83/specs/SPEC-new-sources.md。

⚠️ 本輪（2026-09-02）親驗後發現規格書原定目標網址已失效，改用下述經驗證可行的替代網址，
   詳細調查過程見 docs/new-sources-report.md：

    規格書原定：https://www.circle.com/pricing
    本輪【實測】：該網址現在回 HTTP 301 導向 https://www.circle.com/contact/partner
                （一個「聯絡我們合作」表單頁，不含任何費率數字，200/219,188B 的舊記錄應是
                round2 重驗當時已經在導向該頁、只記了狀態碼與大小、未檢查標題與內文所致）。
    本輪進一步追查（circle.com 官方 Terms of Service 內「Fee Schedule」連結
    → help.circle.com 為 ServiceNow Service Portal，AngularJS 前端渲染，
    純 HTTP GET 只能拿到空殼樣板，看不到實際費率數字，需要執行 JS，本輪不強行破解）
    → 改用 Circle 官方開發者文件站（developers.circle.com，Mintlify 平台，SSR 靜態輸出，
    純 HTTP GET 即可取得完整表格與數字）的 Gateway 產品費率頁，內容即為 Circle 對外公開的
    跨鏈支付「費率頁」性質（轉帳手續費％、各鏈 gas 費、轉發服務費），符合候選原意。

只用 Python 標準函式庫（re + hashlib）。
不落地整頁原始 HTML，只保留結構化擷取後的數字欄位，以及主內文（Transfer fee ~ Optimizing costs
一段）去 HTML 標籤後的純文字 SHA256，供下游偵測「內容是否改變」（呼應 project_tokenomics_docs.py
的既有做法：不存整頁 HTML，只存數字＋文字片段＋SHA256）。
"""

import hashlib
import re

KEY = "payment_pricing_pages"
DESC = "Circle 官方開發者文件 Gateway 產品費率頁（跨鏈轉帳手續費率、各來源鏈 gas 費、轉發服務費）"
PARSER_VERSION = 1
SOURCE_HOME = "https://developers.circle.com/gateway/references/fees"
ROBOTS_VERIFIED = (
    "2026-09-02 親驗 https://www.circle.com/robots.txt：HTTP 200，"
    "User-agent: * 只有 Content-Signal: ai-train=no, search=yes, ai-input=yes，"
    "其餘為表單/policy-hub/search-results 等具體路徑的 Disallow，未見 /pricing 或本 adapter"
    "實際目標路徑被擋（但本輪發現 /pricing 本身已 301 導向 /contact/partner，非費率頁，故未採用）。"
    "2026-09-02 親驗 https://developers.circle.com/robots.txt（本 adapter 實際目標主機）：HTTP 200，"
    "全文為 'User-agent: *\nContent-Signal: ai-train=yes, search=yes, ai-input=yes\n"
    "Disallow: /cdn-cgi/\nAllow: /_next/image\nDisallow: /_next/\n"
    "Sitemap: https://developers.circle.com/sitemap.xml'，"
    "本 adapter 目標路徑 /gateway/references/fees 不在 /cdn-cgi/ 或 /_next/ 之下 → 允許。"
)

# 驗收下限：Gas fee 表格列數不得低於此值（本輪實測 12 條鏈），亦作為「等效分頁上限」
# （本來源為單頁靜態文件，無分頁必要；此常數僅作為表格列數的合理性上限與下限雙重防呆）。
MIN_GAS_FEE_ROWS = 5
MAX_GAS_FEE_ROWS = 100

# 主內文純文字長度下限：目前實測 3,253 字元，低於此值視為版面改版或擷取邊界跑掉
MIN_TEXT_LEN = 1500


def _strip_html(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = text.replace("&#x27;", "'").replace("&amp;", "&").replace("&#39;", "'").replace("&nbsp;", " ")
    text = re.sub(r"&\w+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_transfer_fee(html: str) -> dict:
    m = re.search(
        r"percentage-based fee of\s*<strong>\s*([\d.]+)\s*%\s*</strong>\s*"
        r"\(\s*([\d.]+)\s*basis\s*points?\s*\)",
        html, re.I | re.S,
    )
    if not m:
        raise RuntimeError("payment_pricing_pages：找不到 Transfer fee 百分比，版面可能已改版")
    return {"percent": m.group(1) + "%", "basis_points": m.group(2)}


def _extract_gas_fee_table(html: str) -> dict:
    m = re.search(r"<table[^>]*>(.*?)</table>", html, re.S)
    if not m:
        raise RuntimeError("payment_pricing_pages：找不到 Gas fee 表格，版面可能已改版")
    table_html = m.group(1)
    head_tail = re.split(r"</thead>", table_html, maxsplit=1)
    header_html = head_tail[0]
    body_html = head_tail[1] if len(head_tail) > 1 else table_html
    headers = [_strip_html(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", header_html, re.S)]
    rows = []
    for row_html in re.findall(r"<tr>(.*?)</tr>", body_html, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)
        if len(cells) != 2:
            continue
        rows.append({"source_chain": _strip_html(cells[0]), "gas_fee_usdc": _strip_html(cells[1])})
        if len(rows) >= MAX_GAS_FEE_ROWS:
            break
    if len(rows) < MIN_GAS_FEE_ROWS:
        raise RuntimeError(
            f"payment_pricing_pages：Gas fee 表僅解析到 {len(rows)} 列，"
            f"低於預期下限 {MIN_GAS_FEE_ROWS}，視為擷取失敗"
        )
    return {"headers": headers, "rows": rows}


def _extract_forwarding_fee(html: str) -> dict:
    m = re.search(
        r"forwarding service fee is\s*<strong>\s*\$([\d.]+)\s*</strong>\s*per transfer",
        html, re.I | re.S,
    )
    if not m:
        raise RuntimeError("payment_pricing_pages：找不到 forwarding service fee 數字，版面可能已改版")
    return {"flat_usd": m.group(1)}


def _extract_main_text(html: str) -> str:
    i0 = html.find('id="page-title"')
    i1 = html.find("Was this page helpful")
    if i0 < 0 or i1 < 0 or i1 <= i0:
        raise RuntimeError("payment_pricing_pages：找不到主內文邊界標記，版面可能已改版")
    text = _strip_html(html[i0:i1])
    if len(text) < MIN_TEXT_LEN:
        raise RuntimeError(
            f"payment_pricing_pages：主內文純文字僅 {len(text)} 字元，"
            f"低於驗收下限 {MIN_TEXT_LEN}，視為擷取失敗"
        )
    return text


def collect(fetch) -> dict:
    """抓取 Circle 官方開發者文件 Gateway 費率頁。

    fetch(url, headers=None, timeout=45) 回傳原始 HTML 字串（未解析）。
    失敗一律讓例外往上拋，不吞例外、不回傳空資料。
    """
    html = fetch(SOURCE_HOME, headers={"Accept": "text/html"})
    if not isinstance(html, str) or len(html) < 20000:
        got = len(html) if isinstance(html, str) else 0
        raise RuntimeError(f"payment_pricing_pages：回應僅 {got} 位元組，明顯過短，視為失敗")
    if "Gateway fees" not in html:
        raise RuntimeError("payment_pricing_pages：找不到 'Gateway fees' 標題，版面可能已改版")

    transfer_fee = _extract_transfer_fee(html)
    gas_fees = _extract_gas_fee_table(html)
    forwarding_fee = _extract_forwarding_fee(html)
    main_text = _extract_main_text(html)

    return {
        "page": SOURCE_HOME,
        "title": "Gateway fees",
        "transfer_fee": transfer_fee,
        "gas_fees_by_source_chain": gas_fees,
        "forwarding_fee": forwarding_fee,
        "main_text_sha256": hashlib.sha256(main_text.encode()).hexdigest(),
        "main_text_len": len(main_text),
        "not_covered": {
            "note": "Circle 除 Gateway 外尚有 CCTP／Wallets／xReserve／StableFX 等產品各自的費率文件頁"
                    "（developers.circle.com 站內另有 /cctp/concepts/fees、/wallets/gas-fees、"
                    "/xreserve/references/fees 等），本輪僅實作規格書原定範疇對應的單一頁面，"
                    "未擴大收錄，如需擴充請另行確認範疇。",
        },
    }
