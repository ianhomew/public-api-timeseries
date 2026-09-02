# -*- coding: utf-8 -*-
"""x402_index_thirdparty：x402scan 第三方索引 sitemap 快照 adapter（www.x402scan.com）。

批次：Batch 3（MCP／agent 生態目錄）。
只用標準函式庫（xml.etree.ElementTree）。單一請求，之後 time.sleep(1)。

【已知定位，實作前必讀】
本輪重驗（2026-08-28）：本 sitemap 僅涵蓋約 1,000 個獨立資源頁（/server/<uuid>），
遠低於 B1 官方 x402 Bazaar 目前 14,753 筆掛牌（約 6.8% 覆蓋率）。
這代表 B2 不適合當「與官方交叉驗證」的獨立核心資料源，只適合當輔助視角
（觀察第三方索引與官方掛牌落差本身是否有變化）。
本規格書只建議收錄 sitemap 本身（URL 清單的存在與消失），不逐頁深入抓取內文，
以維持請求數為 1 次／日。
"""
import time
import xml.etree.ElementTree as ET

KEY = "x402_index_thirdparty"
DESC = "x402scan 第三方索引 sitemap URL 清單（僅涵蓋約官方 x402 Bazaar 掛牌數的 6.8%，屬輔助視角非核心資料源）"
SOURCE_HOME = "https://www.x402scan.com/sitemap.xml"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗 https://www.x402scan.com/robots.txt：Allow: /，"
    "Content-Signal: search=yes, ai-train=no, ai-input=yes"
)
PARSER_VERSION = 1

URL = "https://www.x402scan.com/sitemap.xml"
NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def collect(fetch) -> dict:
    """回傳 dict：{"urls": [...], "total": N, "server_count": M}。
    urls 以完整字串去重；驗收下限：總數 >=500，/server/ 前綴數 >=300。
    """
    raw = fetch(URL)
    time.sleep(1)

    root = ET.fromstring(raw)
    locs = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "loc" and el.text:
            locs.append(el.text.strip())

    urls = sorted(set(locs))
    server_count = sum(1 for u in urls if "/server/" in u)

    if len(urls) < 500:
        raise RuntimeError("x402_index_thirdparty：URL 總數 %d 低於驗收下限 500" % len(urls))
    if server_count < 300:
        raise RuntimeError(
            "x402_index_thirdparty：/server/ 前綴 URL 數 %d 低於驗收下限 300" % server_count
        )

    return {"urls": urls, "total": len(urls), "server_count": server_count}
