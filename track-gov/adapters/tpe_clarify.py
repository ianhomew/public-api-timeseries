# -*- coding: utf-8 -*-
"""台北市政府（www.gov.taipei）即時新聞澄清 adapter —— track-gov 每日公告快照。

清單頁：News.aspx?n=<單元ID>&sms=<選單ID>&page=<頁>
內頁  ：News_Content.aspx?n=<單元ID>&sms=<選單ID>&s=<公告ID>
正文  ：<div class="area-essay page-caption-p"> ... </div>（與內政部 moi_press 同一套 GSP 共通性平台，
        本站已各自實測，不假設一定相同；結束標記改用 class="area-editor system-info"）
只用標準函式庫。每次 HTTP 請求後 time.sleep(1)，不並行。
"""
import re
import time
import html as _html
from urllib.parse import urljoin

KEY = "tpe_clarify"
DESC = "台北市政府即時新聞澄清"
PARSER_VERSION = 1
ROBOTS_VERIFIED = (
    "2026-08-28 親驗 https://www.gov.taipei/robots.txt：HTTP 404 Not Found"
    "（全站無 robots.txt，即無任何 Disallow 規則）"
    "→ 目標路徑 /News.aspx、/News_Content.aspx 未被 Disallow"
)
SOURCE_HOME = "https://www.gov.taipei/News.aspx?n=74806083EBDF5A03&sms=72544237BBE4C5F6"

BASE = "https://www.gov.taipei/"
NODE = "74806083EBDF5A03"   # 即時新聞澄清 單元 ID
SMS = "72544237BBE4C5F6"    # 選單 ID

MAX_ITEMS = 100
MAX_PAGES = 8          # 分頁上限寫死，該類別估計個位數~數十篇/年，8 頁已遠超歷史總量

# 清單頁 <tr>：編號 / 標題連結 / 發布日期(民國) / 發布機關
ROW_RE = re.compile(
    r'<a\s+href="(News_Content\.aspx\?n=' + NODE + r'&sms=' + SMS + r'&s=([0-9A-Fa-f]+))"'
    r'\s+title="([^"]*)"[^>]*>.*?</a>.*?'
    r'data-title="發布日期"[^>]*><span>([^<]*)</span>',
    re.S,
)
TAGSTRIP = re.compile(r"<[^>]+>")


def _abs(href):
    return urljoin(BASE, _html.unescape(href))


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


def _roc_to_ad(d):
    """115-07-14 → 2026-07-14（民國年 +1911）"""
    m = re.match(r"(\d{2,3})-(\d{1,2})-(\d{1,2})", d.strip())
    if not m:
        return d.strip()
    y, mo, da = m.groups()
    return "%04d-%02d-%02d" % (int(y) + 1911, int(mo), int(da))


def _list_page(fetch, page):
    url = "%sNews.aspx?n=%s&sms=%s&page=%d" % (BASE, NODE, SMS, page)
    h = fetch(url)
    time.sleep(1)
    return h


def collect(fetch, clean):
    entries = []
    seen = set()
    for page in range(1, MAX_PAGES + 1):
        if len(entries) >= MAX_ITEMS:
            break
        listing = _list_page(fetch, page)
        found = 0
        for href, oid, raw_title, raw_date in ROW_RE.findall(listing):
            if oid in seen:
                continue
            seen.add(oid)
            title = _html.unescape(TAGSTRIP.sub("", raw_title)).strip()
            title = re.sub(r"\s+", " ", title)
            if not title:
                continue
            entries.append({
                "id": oid,
                "url": _abs(href),
                "title": title,
                "date": _roc_to_ad(raw_date),
            })
            found += 1
            if len(entries) >= MAX_ITEMS:
                break
        if found == 0:
            break

    if not entries:
        raise RuntimeError("台北市政府即時新聞澄清清單抓到 0 筆：%s" % SOURCE_HOME)

    out = []
    for e in entries:
        try:
            page_html = fetch(e["url"])
        except Exception:
            time.sleep(1)
            continue
        time.sleep(1)
        frag = _slice(page_html, 'class="area-essay page-caption-p"',
                      ['class="area-editor system-info"', 'class="group page-footer"'])
        body = clean(frag).strip()
        if len(body) < 30:
            continue
        out.append({
            "id": e["id"],
            "url": e["url"],
            "title": e["title"],
            "date": e["date"],
            "body_text": body,
        })

    if not out:
        raise RuntimeError("台北市政府即時新聞澄清內頁正文全部解析失敗（可能改版）：%s" % SOURCE_HOME)
    return out
