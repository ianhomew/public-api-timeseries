#!/usr/bin/env python3
"""airdrop_claim_pages：空投資格規則與認領頁 adapter（track-crypto，batch6／A3）。

對應規格：/Users/monica/Documents/temp/終端機/vps-161.97.82.83/adapters-wip/specs/batch6.md 6-B

**範疇裁示（本輪自行決定，理由如下）**：
    規格書 6-B 本輪重驗的 4 個範例網址中，已有 2 個確認死亡
    （EigenLayer claim.eigenfoundation.org DNS 解析失敗、Jupiter jup.ag/jupuary 404），
    Scroll Portal（portal.scroll.io/sessions）判斷需要 JS（Next.js SPA，信心低）。
    規格書明文建議「若使用者只想要輕量嘗試，建議先只做 Starknet Provisions 這一個確認為靜態
    頁面的目標」，本輪採納此建議，只實作 Starknet Provisions 一項。

    ⚠️ 依規格書與 POLICY.md 提醒：絕對不可抓取「輸入地址查資格」的個人化查詢結果，
    本 adapter 只抓規則說明頁本身（geo-regulations 靜態頁），沒有帶任何地址／查詢參數。

    ⚠️ 這個類別的候選網址天生會隨活動結束而下架（規格書已明講），本 adapter 目前只涵蓋
    Starknet 這一個仍在進行的活動；若日後 Starknet Provisions 活動結束、頁面下架，
    這支 adapter 會如實 raise 失敗，而不是安靜地回傳舊資料或空資料。

技術棧（本輪 2026-08-28 VPS 實測 HTML 確認）：WordPress，正文直接在 <article> 標籤內，
不需要 JS。頁面內容本身是「地區限制規則」（哪些國家/名單被排除），屬於 A3 規格書所稱
「資格門檻」欄位。

只用 Python 標準函式庫（re + hashlib）。不落地整頁原始 HTML，只保留去除標籤後的純文字。
"""

import hashlib
import re

KEY = "airdrop_claim_pages"
DESC = "空投資格規則頁（本輪僅收錄 Starknet Provisions 地區限制規則頁，見模組說明）"
PARSER_VERSION = 1
SOURCE_HOME = "https://www.starknet.io/provisions-geo-regulations/"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗 https://www.starknet.io/robots.txt：HTTP 200，"
    "User-agent: * 的 Disallow 清單（查詢參數、/wp-admin、/tag/ 等）未涵蓋 "
    "/provisions-geo-regulations/，允許存取"
)

MIN_TEXT_LEN = 200


def _strip_html(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = text.replace("&#8217;", "'").replace("&amp;", "&")
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"&\w+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def collect(fetch) -> dict:
    """抓取 Starknet Provisions 空投資格地區限制規則頁。

    fetch(url, headers=None, timeout=45) 回傳原始 HTML 字串（未解析）。
    失敗一律讓例外往上拋，不吞例外、不回傳空資料。
    """
    html = fetch(SOURCE_HOME, headers={"Accept": "text/html"})
    if not isinstance(html, str) or len(html) < 5000:
        got = len(html) if isinstance(html, str) else 0
        raise RuntimeError(f"airdrop_claim_pages：回應僅 {got} 位元組，明顯過短，視為失敗")

    m = re.search(r"<article.*?</article>", html, re.S)
    if not m:
        raise RuntimeError("airdrop_claim_pages：找不到 <article> 區塊，starknet.io 版面可能已改版")

    article_html = m.group(0)
    # <article> 內含頁尾腳本（gsp_data_html 等），一律截斷在第一個 <script 之前，
    # 避免把 JS 雜訊混進「內容是否改變」的比對基準。
    sidx = article_html.find("<script")
    if sidx != -1:
        article_html = article_html[:sidx]

    text = _strip_html(article_html)
    if len(text) < MIN_TEXT_LEN:
        raise RuntimeError(
            f"airdrop_claim_pages：<article> 純文字僅 {len(text)} 字元，"
            f"低於驗收下限 {MIN_TEXT_LEN}，可能是活動已下架或版面改版導致擷取失敗"
        )

    # 資格門檻文字：規格書要求至少能抽出「資格門檻」/「快照時間」/「認領期限」三者其一，
    # 本頁內容屬於地區限制型資格門檻（哪些國家/名單被排除），檢查關鍵字確保抓到的是規則內容
    # 而非誤抓到別的頁面（例如站台改版後同網址變成其他主題頁）。
    if not re.search(r"sanction|OFAC|regulat|entit(y|ies)", text, re.I):
        raise RuntimeError(
            "airdrop_claim_pages：純文字內容找不到預期的地區限制/資格關鍵字，"
            "頁面內容可能已變更為其他主題，視為擷取失敗"
        )

    return {
        "campaigns": {
            "starknet_provisions": {
                "url": SOURCE_HOME,
                "eligibility_text": text,
                "eligibility_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "eligibility_text_len": len(text),
            }
        },
        "not_covered": {
            "scroll_portal": "portal.scroll.io/sessions（Next.js SPA，判斷需要 JS，信心低），未實作",
            "jupiter_jupuary": "jup.ag/jupuary 本輪實測 HTTP 404，頁面已下架",
            "eigenlayer_claim": "claim.eigenfoundation.org 本輪實測 DNS 解析失敗，網域已死",
        },
    }
