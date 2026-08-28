#!/usr/bin/env python3
"""project_tokenomics_docs：專案官方 tokenomics 文件頁 adapter（track-crypto，batch6／A2）。

對應規格：/Users/monica/Documents/temp/終端機/vps-161.97.82.83/adapters-wip/specs/batch6.md 6-A

**範疇裁示（本輪自行決定，理由如下）**：
    規格書 6-A 明確指出 A2 本質上是「一個類別」而非「單一端點」（各專案 docs 站台各自獨立，
    要收錄哪些專案、幾個專案是範疇問題，規格書本身沒有給出收錄清單）。
    本輪只實作規格書列為「建議的首發旗艦目標」的 Arbitrum Foundation 一項：
    - Jupiter（docs.jup.ag，Mintlify 平台）本輪只確認 200 OK，未逐字驗證正文是否完整內嵌於
      原始 HTML（規格書原文即註記「本輪未逐字確認」），若貿然實作可能因為 SSR 邊界判斷錯誤而
      拿到不完整資料，故不在本輪納入。
    - Hyperliquid（docs.hyperliquid.xyz）規格書已確認 DNS 解析失敗（網域已死），本輪不追查新網址
      （規格書明文列為超出重驗範疇）。
    未來若要擴充其他專案文件頁，可比照本檔 `_extract_arbitrum_tokenomics()` 的做法
    （regex 擷取 <article>…</article> 內文字後用正規表達式抓具體數字），逐一新增。

技術棧（本輪 2026-08-28 VPS 實測 HTML 確認）：Docusaurus v2.2.0 靜態網站產生器，
正文完整內嵌在首次回應的 <article>…</article> 標籤內，不需要 JS 即可解析。

只用 Python 標準函式庫（re + hashlib）。
不落地整頁原始 HTML（呼應規格書「不存整頁 HTML，只存數字＋文字片段＋SHA256」的建議），
只保留 <article> 純文字（已去 HTML 標籤）與由此計算的 SHA256，供下游偵測「內容是否改變」。
"""

import hashlib
import re

KEY = "project_tokenomics_docs"
DESC = "專案官方 tokenomics 文件頁（本輪僅收錄 Arbitrum Foundation 空投分配文件，見模組說明）"
PARSER_VERSION = 1
SOURCE_HOME = "https://docs.arbitrum.foundation/airdrop-eligibility-distribution"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗 https://docs.arbitrum.foundation/robots.txt：HTTP 404"
    "（該站沒有 robots.txt，視為無限制；根路徑本身可正常存取，非封鎖造成的 404）"
)

# 驗收下限：<article> 純文字長度不得低於此值，太短代表版面改版導致擷取失敗
MIN_TEXT_LEN = 2000


def _strip_html(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = text.replace("&#x27;", "'").replace("&amp;", "&").replace("&#39;", "'")
    text = re.sub(r"&\w+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_arbitrum_tokenomics(html: str) -> dict:
    m = re.search(r"<article.*?</article>", html, re.S)
    if not m:
        raise RuntimeError(
            "project_tokenomics_docs：找不到 <article> 區塊，Arbitrum docs 站台版面可能已改版"
        )
    text = _strip_html(m.group(0))
    if len(text) < MIN_TEXT_LEN:
        raise RuntimeError(
            f"project_tokenomics_docs：<article> 純文字僅 {len(text)} 字元，"
            f"低於驗收下限 {MIN_TEXT_LEN}，視為擷取失敗"
        )

    supply_m = re.search(r"Initial supply cap\s*([\d,]+\s*(?:billion|million|trillion))", text, re.I)
    if not supply_m:
        raise RuntimeError("project_tokenomics_docs：找不到 Initial supply cap 數字，版面可能已改版")

    seg_m = re.search(r"Allocated to (.+?) User airdrop eligibility details", text)
    rows = []
    if seg_m:
        rows = re.findall(
            r"(\d+(?:\.\d+)?%)\s+([\d.]+\s*(?:[Bb]illion|[Mm]illion))\s+"
            r"(.+?)(?=\s\d+(?:\.\d+)?%\s|\s*$)",
            seg_m.group(1),
        )
    if len(rows) < 3:
        raise RuntimeError(
            f"project_tokenomics_docs：代幣分配表僅解析到 {len(rows)} 列，"
            "低於預期下限 3 列，版面可能已改版"
        )

    return {
        "initial_supply_cap": supply_m.group(1).strip(),
        "allocation_rows": [
            {"percentage": p, "amount": a, "allocated_to": t.strip()} for p, a, t in rows
        ],
        "article_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "article_text_len": len(text),
    }


def collect(fetch) -> dict:
    """抓取 Arbitrum Foundation 官方 tokenomics／空投分配文件頁。

    fetch(url, headers=None, timeout=45) 回傳原始 HTML 字串（未解析）。
    失敗一律讓例外往上拋，不吞例外、不回傳空資料。
    """
    html = fetch(SOURCE_HOME, headers={"Accept": "text/html"})
    if not isinstance(html, str) or len(html) < 5000:
        got = len(html) if isinstance(html, str) else 0
        raise RuntimeError(
            f"project_tokenomics_docs：回應僅 {got} 位元組，明顯過短，視為失敗"
        )

    arbitrum = _extract_arbitrum_tokenomics(html)
    return {
        "projects": {
            "arbitrum": {
                "url": SOURCE_HOME,
                "platform": "Docusaurus v2.2.0",
                **arbitrum,
            }
        },
        "not_covered": {
            "jupiter": "docs.jup.ag（Mintlify）本輪僅確認 200 OK，未驗證正文是否完整內嵌，未實作",
            "hyperliquid": "docs.hyperliquid.xyz DNS 解析失敗（網域已死），未實作",
        },
    }
