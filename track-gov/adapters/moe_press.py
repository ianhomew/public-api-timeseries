# -*- coding: utf-8 -*-
"""教育部（www.edu.tw）即時新聞 adapter —— track-gov 每日公告快照。

清單頁：News.aspx?n=<單元ID>&sms=<選單ID>&page=<頁>&PageSize=<每頁>
內頁  ：News_Content.aspx?n=<單元ID>&sms=<選單ID>&s=<公告ID>
正文  ：<div id="ContentPlaceHolder1_divcontent" class="data_midlle_news_box02"> ... </div>
只用標準函式庫。每次 HTTP 請求後 time.sleep(1)。
"""
import re
import time
import html as _html

KEY = "moe_press"
DESC = "教育部即時新聞（新聞稿）"
ROBOTS_VERIFIED = (
    "2026-08-27 親驗 https://www.edu.tw/robots.txt，全文僅 5 行："
    "User-agent: * / Disallow: /WebResource.axd / Disallow: /src / "
    "Disallow: /Scripts/fu_Accessibility.js / Disallow: /search。"
    "本 adapter 只取 /News.aspx 與 /News_Content.aspx，"
    "兩者皆不在上述 4 條 Disallow 之下 → 目標路徑未被 Disallow。"
)
SOURCE_HOME = "https://www.edu.tw/News.aspx?n=9E7AC85F1954DDA8&sms=169B8E91BB75571F"

BASE = "https://www.edu.tw/"
NODE = "9E7AC85F1954DDA8"   # 即時新聞 單元 ID
SMS = "169B8E91BB75571F"    # 訊息公告 > 即時新聞 選單 ID

MAX_ITEMS = 100      # 最新 100 筆以內
PAGE_SIZE = 100      # 該 CMS 支援 PageSize 參數，一頁即可取滿
MAX_PAGES = 2        # 分頁上限寫死，避免無限翻頁

# 清單頁 <tr>：日期 + 標題連結
ROW_RE = re.compile(
    r'<td[^>]*>\s*(\d{2,4}-\d{1,2}-\d{1,2})\s*</td>.*?'
    r'<a[^>]+href="(News_Content\.aspx\?[^"]+)"[^>]*>(.*?)</a>',
    re.S,
)
# 內頁正文容器
BODY_RE = re.compile(
    r'<div id="ContentPlaceHolder1_divcontent"[^>]*>(.*?)'
    r'<div class="data_midlle_news_box03"',
    re.S,
)
DATE_RE = re.compile(r'上版日期[：:]\s*(\d{2,4}-\d{1,2}-\d{1,2})')
TAGSTRIP = re.compile(r"<[^>]+>")


def _abs(href):
    return BASE + _html.unescape(href).lstrip("/")


def _list_page(fetch, page):
    url = "%sNews.aspx?n=%s&sms=%s&page=%d&PageSize=%d" % (BASE, NODE, SMS, page, PAGE_SIZE)
    h = fetch(url)
    time.sleep(1)
    return h


def collect(fetch, clean):
    # ---- 1. 清單 ----
    entries = []
    seen = set()
    for page in range(1, MAX_PAGES + 1):
        if len(entries) >= MAX_ITEMS:
            break
        listing = _list_page(fetch, page)
        found = 0
        for date, href, raw_title in ROW_RE.findall(listing):
            if NODE not in href:
                continue
            url = _abs(href)
            m = re.search(r"[?&]s=([0-9A-Fa-f]+)", url)
            if not m:
                continue
            oid = m.group(1)
            if oid in seen:
                continue
            seen.add(oid)
            title = _html.unescape(TAGSTRIP.sub("", raw_title)).strip()
            title = re.sub(r"\s+", " ", title)
            if not title:
                continue
            entries.append({"id": oid, "url": url, "title": title, "date": date.strip()})
            found += 1
            if len(entries) >= MAX_ITEMS:
                break
        if found == 0:
            break

    if not entries:
        raise RuntimeError("教育部即時新聞清單抓到 0 筆：%s" % SOURCE_HOME)

    # ---- 2. 內頁正文 ----
    out = []
    for e in entries:
        try:
            page_html = fetch(e["url"])
        except Exception:
            time.sleep(1)
            continue
        time.sleep(1)
        m = BODY_RE.search(page_html)
        if not m:
            continue
        body = clean(m.group(1)).strip()
        if len(body) < 50:
            continue
        dm = DATE_RE.search(page_html)
        out.append({
            "id": e["id"],
            "url": e["url"],
            "title": e["title"],
            "date": dm.group(1) if dm else e["date"],
            "body_text": body,
        })

    if not out:
        raise RuntimeError("教育部即時新聞內頁正文全部解析失敗（可能改版）：%s" % SOURCE_HOME)
    return out
