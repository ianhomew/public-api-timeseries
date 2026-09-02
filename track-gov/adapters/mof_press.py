# -*- coding: utf-8 -*-
"""財政部「本部新聞」每日快照 adapter（只用標準函式庫）。"""
import re, time

KEY = "mof_press"
DESC = "財政部本部新聞（新聞稿）"
PARSER_VERSION = 1  # 2026-09-02 新增宣告（維持原預設值＝1，非改版；缺此常數時 getattr 預設即為 1，語意不變）
ROBOTS_VERIFIED = (
    "2026-08-27 親驗 https://www.mof.gov.tw/robots.txt：全文僅兩行 "
    "'User-agent: *' / 'Disallow: /download/'；本 adapter 只取 "
    "/multiplehtml/ 與 /singlehtml/，未落在 /download/ 之下 → 未被 Disallow"
)
SOURCE_HOME = "https://www.mof.gov.tw/multiplehtml/384fb3077bb349ea973e7fc6f13b6974"

ORIGIN = "https://www.mof.gov.tw"
CHANNEL = "384fb3077bb349ea973e7fc6f13b6974"
LIST_URL = ORIGIN + "/multiplehtml/" + CHANNEL
ITEM_URL = ORIGIN + "/singlehtml/" + CHANNEL + "?cntId=%s"

MAX_PAGES = 10        # 寫死分頁上限（每頁 10 筆 → 最多 100 筆）
MAX_ITEMS = 100

ROW_RE = re.compile(
    r'<a\s+href="/singlehtml/' + CHANNEL + r'\?cntId=(?P<cid>[0-9a-f]{32})"'
    r'[^>]*?title=\'(?P<title>.*?)\'>', re.S)
DATE_RE = re.compile(r'發布日期：">\s*<span>\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*</span>', re.S)
TABLE_RE = re.compile(r'<table class="table-list".*?</table>', re.S)
TITLE_RE = re.compile(r'<span class="span-page-title">(.*?)</span>', re.S)
ARTICLE_RE = re.compile(r'<article>(.*?)</article>', re.S)
INFO_DATE_RE = re.compile(r'發布日期：([0-9]{4}-[0-9]{2}-[0-9]{2})')


def _list_page(fetch, page):
    """回傳該頁 [(cntId, title, date)]，只取 table-list 區塊，避開側欄連結。"""
    url = LIST_URL if page == 1 else LIST_URL + "?page=%d&isPage=true" % page
    html = fetch(url)
    time.sleep(1)
    m = TABLE_RE.search(html)
    if not m:
        return []
    block = m.group(0)
    rows = block.split("<tr>")
    out = []
    for r in rows:
        a = ROW_RE.search(r)
        if not a:
            continue
        d = DATE_RE.search(r)
        out.append((a.group("cid"),
                    re.sub(r"\s+", " ", a.group("title")).strip(),
                    d.group(1) if d else ""))
    return out


def collect(fetch, clean):
    seen, metas = set(), []
    for p in range(1, MAX_PAGES + 1):
        rows = _list_page(fetch, p)
        if not rows:
            break
        new = 0
        for cid, title, date in rows:
            if cid in seen:
                continue
            seen.add(cid)
            metas.append((cid, title, date))
            new += 1
        if new == 0 or len(metas) >= MAX_ITEMS:
            break
    metas = metas[:MAX_ITEMS]
    if not metas:
        raise RuntimeError("財政部本部新聞清單抓到 0 筆（版面可能改版）")

    items = []
    for cid, title, date in metas:
        url = ITEM_URL % cid
        html = fetch(url)
        time.sleep(1)
        tail = html
        t = TITLE_RE.search(html)
        if t:
            tail = html[t.end():]
            if not title:
                title = clean(t.group(1))
        a = ARTICLE_RE.search(tail)   # 內文區第一個 <article>，頁尾 <article> 在其後
        if not a:
            continue
        body = clean(a.group(1))
        if not date:
            d = INFO_DATE_RE.search(tail[:a.end() + 4000])
            date = d.group(1) if d else ""
        if len(body) < 50:
            continue
        items.append({"id": cid, "url": url, "title": title,
                      "date": date, "body_text": body})
    if not items:
        raise RuntimeError("財政部本部新聞內頁全部解析失敗")
    return items
