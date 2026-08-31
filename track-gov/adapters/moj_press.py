# -*- coding: utf-8 -*-
"""法務部 新聞發布 快照 adapter。

2026-08-31 因站方回應變慢（同一 URL 耗時從 2.76 秒飆到 14.77 秒），依 PERF_FIX_SPEC.md 修正 4，
MAX_ITEMS 由 100 降為 50；本站日增量約數筆~十餘筆，50 筆仍足以偵測改寫（重疊視窗遠大於日增量）。
同時依修正 2 支援 collect(fetch, clean, deadline=None)：deadline 為驅動程式傳入的 UNIX 時間戳，
本 adapter 在每次翻頁／每抓一筆內頁前檢查 time.time() < deadline，超過就停止並回傳已取得的資料
（向下相容：deadline 為 None 時視為無時間限制，行為與舊版完全相同）。
"""
import re
import time
import urllib.parse

KEY = "moj_press"
DESC = "法務部新聞發布"
ROBOTS_VERIFIED = (
    "2026-08-27 親驗 https://www.moj.gov.tw/robots.txt（伺服器 301 導向 https://www.moj.gov.tw/robots）："
    "全檔只有兩行空白與一行 'Sitemap: https://www.moj.gov.tw/sitemap?id=2204'，"
    "沒有任何 User-agent / Disallow 規則 → 目標路徑 /2204/2795/2796/** 未被 Disallow"
)
SOURCE_HOME = "https://www.moj.gov.tw/2204/2795/2796/Lpsimplelist"

BASE = "https://www.moj.gov.tw/"
LIST = "https://www.moj.gov.tw/2204/2795/2796/Lpsimplelist?Page=%d&PageSize=20"
MAX_PAGES = 5          # 寫死分頁上限：5 頁 x 20 筆 = 100 筆（足以覆蓋 MAX_ITEMS=50）
MAX_ITEMS = 50    # 2026-08-31：因站方回應變慢，由 100 降為 50；日增量約數筆~十餘筆，50 筆仍足以偵測改寫

ROW = re.compile(r'<a\s+href="(/2204/2795/2796/(\d+)/post)"\s+title="([^"]*)"', re.I)
CP = re.compile(r'<!--\s*CP Start\s*-->(.*?)<!--\s*CP End\s*-->', re.I | re.S)
H3 = re.compile(r'(?is)<h3[^>]*class="title"[^>]*>.*?</h3>')
INFO = re.compile(r'(?is)<div[^>]*class="info"[^>]*>.*?</ul>\s*</div>')
DATE = re.compile(r'發布日期：\s*<time[^>]*>([^<]+)</time>', re.I | re.S)
DCDATE = re.compile(r'<meta\s+name="DC.Date"\s+content="([^"]+)"', re.I)


def _deadline_hit(deadline):
    return deadline is not None and time.time() >= deadline


def collect(fetch, clean, deadline=None):
    seen = set()
    order = []
    for page in range(1, MAX_PAGES + 1):
        if _deadline_hit(deadline):
            break
        html = fetch(LIST % page)
        time.sleep(1)
        rows = ROW.findall(html)
        if not rows:
            break
        for href, aid, title in rows:
            if aid in seen:
                continue
            seen.add(aid)
            order.append((urllib.parse.urljoin(BASE, href), aid, clean(title)))
        if len(order) >= MAX_ITEMS:
            break

    order = order[:MAX_ITEMS]
    if not order:
        raise RuntimeError("moj_press：清單頁抓到 0 筆，版型可能已改")

    items = []
    for url, aid, title in order:
        if _deadline_hit(deadline):
            break
        html = fetch(url)
        time.sleep(1)
        m = CP.search(html)
        if not m:
            continue
        block = m.group(1)
        d = DATE.search(block)
        if d:
            date = d.group(1).strip()
        else:
            d2 = DCDATE.search(html)
            date = d2.group(1).strip() if d2 else ""
        if not date:
            continue
        body_html = INFO.sub(" ", H3.sub(" ", block))
        body = clean(body_html)
        if len(body) < 50:
            continue
        items.append({
            "id": aid,
            "url": url,
            "title": title,
            "date": date,
            "body_text": body,
        })

    if not items:
        raise RuntimeError("moj_press：內頁正文全部抓不到，版型可能已改")
    return items
