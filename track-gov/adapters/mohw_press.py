# -*- coding: utf-8 -*-
"""衛生福利部 焦點新聞（新聞稿）快照 adapter。

2026-09-04 依 SPEC-y2-deadline.md 補上 collect(fetch, clean, deadline=None) 支援：
deadline 為驅動程式傳入的 UNIX 時間戳，本 adapter 在每次翻頁／每抓一筆內頁前檢查
time.time() < deadline，超過就停止並回傳已取得的資料（向下相容：deadline 為 None
時視為無時間限制，行為與舊版完全相同）。只新增提早停止的能力，不改動既有抓取邏輯、
欄位、排序或 MAX_ITEMS。
"""
import re
import time
import urllib.parse

KEY = "mohw_press"
DESC = "衛生福利部焦點新聞（新聞稿）"
PARSER_VERSION = 1  # 2026-09-02 新增宣告（維持原預設值＝1，非改版；缺此常數時 getattr 預設即為 1，語意不變）
ROBOTS_VERIFIED = (
    "2026-08-27 親驗 https://www.mohw.gov.tw/robots.txt："
    "全檔僅一行 'User-agent: *'，沒有任何 Disallow 行 → 目標路徑 /lp-16-*.html 與 /cp-16-*.html 未被 Disallow"
)
SOURCE_HOME = "https://www.mohw.gov.tw/lp-16-1.html"

BASE = "https://www.mohw.gov.tw/"
MAX_PAGES = 5          # 寫死分頁上限：5 頁 x 20 筆 = 100 筆
PAGE_SIZE = 20
MAX_ITEMS = 100

# <li><a href="https://www.mohw.gov.tw/cp-16-87687-1.html" title="..."><p>標題</p><time>115-08-27</time></a></li>
ROW = re.compile(
    r'<li>\s*<a\s+href="([^"]*cp-16-(\d+)-\d+\.html)"[^>]*>\s*<p>(.*?)</p>\s*<time>([^<]*)</time>',
    re.I | re.S,
)
ART = re.compile(r'<article[^>]*class="[^"]*cpArticle[^"]*"[^>]*>(.*?)</article>', re.I | re.S)


def _deadline_hit(deadline):
    return deadline is not None and time.time() >= deadline


def collect(fetch, clean, deadline=None):
    seen = {}
    order = []
    for page in range(1, MAX_PAGES + 1):
        if _deadline_hit(deadline):
            break
        url = urllib.parse.urljoin(BASE, "lp-16-1-%d-%d.html" % (page, PAGE_SIZE))
        html = fetch(url)
        time.sleep(1)
        rows = ROW.findall(html)
        if not rows:
            break
        for href, cid, title, date in rows:
            if cid in seen:
                continue
            seen[cid] = True
            order.append((urllib.parse.urljoin(BASE, href), cid, clean(title), date.strip()))
        if len(order) >= MAX_ITEMS:
            break

    order = order[:MAX_ITEMS]
    if not order:
        raise RuntimeError("mohw_press：清單頁抓到 0 筆，版型可能已改")

    items = []
    for url, cid, title, date in order:
        if _deadline_hit(deadline):
            break
        html = fetch(url)
        time.sleep(1)
        m = ART.search(html)
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
        raise RuntimeError("mohw_press：內頁正文全部抓不到，版型可能已改")
    return items
