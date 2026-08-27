# -*- coding: utf-8 -*-
"""中央銀行 新聞稿 快照 adapter。"""
import re
import time
import urllib.parse

KEY = "cbc_press"
DESC = "中央銀行新聞稿"
ROBOTS_VERIFIED = (
    "2026-08-27 親驗 https://www.cbc.gov.tw/robots.txt：伺服器不提供 robots.txt，"
    "而是以 302 導向中文首頁 https://www.cbc.gov.tw/tw/mp-1.html 回傳 HTML，"
    "因此全站沒有任何 Disallow 規則 → 目標路徑 /tw/lp-302-*.html 與 /tw/cp-302-*.html 未被禁止"
)
SOURCE_HOME = "https://www.cbc.gov.tw/tw/lp-302-1.html"

BASE = "https://www.cbc.gov.tw/tw/"
MAX_PAGES = 5          # 寫死分頁上限：5 頁 x 20 筆 = 100 筆
PAGE_SIZE = 20
MAX_ITEMS = 100

# <li><span class="num">1</span><time>2026-08-27</time><a href="/tw/cp-302-192784-f4ff3-1.html" title="...">標題</a></li>
ROW = re.compile(
    r'<time>([^<]*)</time>\s*<a\s+href="([^"]*cp-302-(\d+)-[^"]*\.html)"\s+title="([^"]*)"',
    re.I | re.S,
)
CP = re.compile(r'<section[^>]*class="cp"[^>]*>(.*?)</section>', re.I | re.S)


def collect(fetch, clean):
    seen = set()
    order = []
    for page in range(1, MAX_PAGES + 1):
        url = urllib.parse.urljoin(BASE, "lp-302-1-%d-%d.html" % (page, PAGE_SIZE))
        html = fetch(url)
        time.sleep(1)
        rows = ROW.findall(html)
        if not rows:
            break
        for date, href, cid, title in rows:
            if cid in seen:
                continue
            seen.add(cid)
            order.append((urllib.parse.urljoin(BASE, href), cid, clean(title), date.strip()))
        if len(order) >= MAX_ITEMS:
            break

    order = order[:MAX_ITEMS]
    if not order:
        raise RuntimeError("cbc_press：清單頁抓到 0 筆，版型可能已改")

    items = []
    for url, cid, title, date in order:
        html = fetch(url)
        time.sleep(1)
        m = CP.search(html)
        if not m:
            continue
        body = clean(m.group(1))
        if len(body) < 50:
            continue
        items.append({
            "id": cid,
            "url": url,
            "title": title,
            "date": date,
            "body_text": body,
        })

    if not items:
        raise RuntimeError("cbc_press：內頁正文全部抓不到，版型可能已改")
    return items
