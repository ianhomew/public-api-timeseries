#!/usr/bin/env python3
"""行政院「本院新聞」adapter（track-gov 政府公告快照）。

只用標準函式庫。每次 HTTP 請求後 time.sleep(1)，不並行。
"""
import re
import time
import html as _html
from urllib.parse import urljoin

KEY = "ey_press"
DESC = "行政院本院新聞（新聞與公告）"
ROBOTS_VERIFIED = (
    "2026-08-27 親驗 https://www.ey.gov.tw/robots.txt，全文為 "
    "'user-agent: *' / 'disallow: /Upload' / 'disallow:/Program/EY/Hope_decision.ascx'"
    " → 目標路徑 /Page/* 未被 Disallow（不抓 /Upload 下的附件）"
)
SOURCE_HOME = "https://www.ey.gov.tw/Page/6485009ABEC1CB9C"

LIST_URL = "https://www.ey.gov.tw/Page/6485009ABEC1CB9C?page={p}&PS=130"
NEWS_NODE = "9277F759E41CCD91"   # 本院新聞的內頁節點；同清單另含影音節點，排除之
MAX_PAGES = 1                    # 寫死分頁上限
MAX_ITEMS = 100

_ITEM = re.compile(
    r'<a\s+title="([^"]*)"[^>]*href="(/Page/' + NEWS_NODE + r'/([0-9a-f-]{36}))"'
    r'.*?class="date">\s*([0-9]{2,3}-[0-9]{2}-[0-9]{2})\s*<',
    re.S,
)


def _slice(doc, start_marker, end_markers):
    i = doc.find(start_marker)
    if i < 0:
        return ""
    gt = doc.find(">", i)
    i = gt + 1 if gt > 0 else i + len(start_marker)
    j = len(doc)
    for em in end_markers:
        k = doc.find(em, i)
        if 0 <= k < j:
            j = k
    return doc[i:j]


def collect(fetch, clean):
    rows = []
    seen = set()
    for p in range(1, MAX_PAGES + 1):
        page = fetch(LIST_URL.format(p=p))
        time.sleep(1)
        found = _ITEM.findall(page)
        if not found:
            break
        for title, href, guid, date in found:
            if guid in seen:
                continue
            seen.add(guid)
            rows.append((date, urljoin("https://www.ey.gov.tw/", href), guid,
                         _html.unescape(title).strip()))
        if len(rows) >= MAX_ITEMS:
            break
    rows = rows[:MAX_ITEMS]
    if not rows:
        raise RuntimeError("ey_press：清單頁抓到 0 筆，可能改版或被擋，視為失敗")

    items = []
    for date, url, guid, title in rows:
        doc = fetch(url)
        time.sleep(1)
        frag = _slice(doc, 'class="data_left',
                      ['class="col-4 right_content"', 'class="other_link',
                       'id="ctl09_other_link"', '<!--相關照片-->', '<footer'])
        body = clean(frag)
        if not title:
            m = re.search(r'<span class="h2">(.*?)</span>', doc, re.S)
            if m:
                title = clean(m.group(1))
        items.append({
            "id": guid,
            "url": url,
            "title": title,
            "date": date,
            "body_text": body,
        })
    if not items:
        raise RuntimeError("ey_press：內頁全部解析失敗")
    return items
