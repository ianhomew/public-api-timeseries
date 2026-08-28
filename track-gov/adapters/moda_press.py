#!/usr/bin/env python3
"""數位發展部新聞發布 adapter（track-gov 政府公告快照）。

只用標準函式庫。每次 HTTP 請求後 time.sleep(1)，不並行。
清單頁的翻頁是純前端 JS（SearchJsonData → POST 官方 API），
所以清單改打該站自己的公開 API（www-api.moda.gov.tw）一次取回 100 筆，
比逐頁抓更省請求；內頁仍走一般網頁。
"""
import json
import re
import time
import html as _html
import urllib.request
from urllib.parse import urljoin

KEY = "moda_press"
PARSER_VERSION = 2   # v2：_slice 去除切點殘缺標籤
DESC = "數位發展部新聞發布"
ROBOTS_VERIFIED = (
    "2026-08-27 親驗 https://moda.gov.tw/robots.txt 與 https://www.moda.gov.tw/robots.txt："
    "兩者皆 HTTP 404 Not Found（全站無 robots.txt，即無任何 Disallow 規則）"
    "→ 目標路徑 /press/press-releases/* 未被 Disallow"
)
SOURCE_HOME = "https://moda.gov.tw/press/press-releases/372"

API_URL = "https://www-api.moda.gov.tw/WebsiteList/NewsList"
MAIN_SN = 372            # 「新聞發布」清單的 MainSN（頁面 <input id="sqn" value="372">）
DEPTS = ["M", "M7000", "M5000", "M6000", "M4000", "M2000", "M3000", "S", "I"]
MAX_PAGES = 1            # 寫死分頁上限：一次取 100 筆已達上限，不再翻頁
MAX_ITEMS = 100
UA = ("snapshotter-research/1.0 (daily archival; public accountability; 1 req/sec; "
      "github.com/ianhomew/public-api-timeseries)")

_ITEM = re.compile(
    r'href="(/press/press-releases/(\d+))"[^>]*title="([^"]*)".*?'
    r'class="listDate[^"]*">\s*(\d{4}-\d{2}-\d{2})\s*<',
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
    # 切點可能卡在標籤中間，去掉尾端殘缺標籤（否則每篇結尾都殘留裸的 "<div"）
    return re.sub(r"<[^>]*$", "", doc[i:j])


def _list_html(page):
    payload = {
        "Lang": "zh-tw", "MainSN": MAIN_SN, "StartDate": "", "EndDate": "",
        "SearchString": "", "Condition4": "", "Condition5": "", "Condition6": "",
        "CustomizeTagSN": "", "SysZipCode": "", "Condition7": "", "Regulations": "0",
        "P": page, "DisplayCount": MAX_ITEMS, "Dep": DEPTS, "hashtag": "",
    }
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"User-Agent": UA, "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))


def collect(fetch, clean):
    rows = []
    seen = set()
    for p in range(1, MAX_PAGES + 1):
        page_html = _list_html(p)
        time.sleep(1)
        k = page_html.find('id="ListTable"')
        seg = page_html[k:] if k >= 0 else page_html
        for href, sn, title, date in _ITEM.findall(seg):
            if sn in seen:
                continue
            seen.add(sn)
            rows.append((date, urljoin("https://moda.gov.tw/", href), sn,
                         _html.unescape(title).replace("移至", "", 1).strip()))
        if len(rows) >= MAX_ITEMS:
            break
    rows = rows[:MAX_ITEMS]
    if not rows:
        raise RuntimeError("moda_press：清單抓到 0 筆，可能改版或被擋，視為失敗")

    items = []
    for date, url, sn, title in rows:
        doc = fetch(url)
        time.sleep(1)
        frag = _slice(doc, 'class="article1 cpArticle"',
                      ['class="articleOther"', 'class="articleInfo"', '<footer'])
        body = clean(frag)
        if not title:
            m = re.search(r'class="titleTxt">(.*?)</span>', doc, re.S)
            if m:
                title = clean(m.group(1))
        items.append({
            "id": sn,
            "url": url,
            "title": title,
            "date": date,
            "body_text": body,
        })
    if not items:
        raise RuntimeError("moda_press：內頁全部解析失敗")
    return items
