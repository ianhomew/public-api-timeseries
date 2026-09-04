#!/usr/bin/env python3
"""內政部新聞稿 adapter（track-gov 政府公告快照）。

只用標準函式庫。每次 HTTP 請求後 time.sleep(1)，不並行。

2026-09-04 依 SPEC-y2-deadline.md 補上 collect(fetch, clean, deadline=None) 支援：
deadline 為驅動程式傳入的 UNIX 時間戳，本 adapter 在每次翻頁／每抓一筆內頁前檢查
time.time() < deadline，超過就停止並回傳已取得的資料（向下相容：deadline 為 None
時視為無時間限制，行為與舊版完全相同）。只新增提早停止的能力，不改動既有抓取邏輯、
欄位、排序或 MAX_ITEMS。
"""
import re
import time
import html as _html
from urllib.parse import urljoin

KEY = "moi_press"
PARSER_VERSION = 2   # v2：_slice 去除切點殘缺標籤
DESC = "內政部新聞稿"
ROBOTS_VERIFIED = (
    "2026-08-27 親驗 https://www.moi.gov.tw/robots.txt：HTTP 404 Not Found（全站無 robots.txt，"
    "即無任何 Disallow 規則）→ 目標路徑 /News.aspx、/News_Content.aspx 未被 Disallow"
)
SOURCE_HOME = "https://www.moi.gov.tw/News.aspx?n=4&sms=9009"

LIST_URL = "https://www.moi.gov.tw/News.aspx?n=4&sms=9009&page={p}&PageSize=100"
MAX_PAGES = 1          # 寫死分頁上限：一頁 100 筆已達上限，不再翻頁
MAX_ITEMS = 100

_ROW = re.compile(
    r'<td[^>]*data-title="日期"[^>]*>\s*<span>\s*([0-9]{2,3}-[0-9]{2}-[0-9]{2})\s*</span>.*?'
    r'<a\s+href="(News_Content\.aspx\?n=\d+&s=(\d+))"\s+title="([^"]*)"',
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


def _deadline_hit(deadline):
    return deadline is not None and time.time() >= deadline


def collect(fetch, clean, deadline=None):
    rows = []
    seen = set()
    for p in range(1, MAX_PAGES + 1):
        if _deadline_hit(deadline):
            break
        page = fetch(LIST_URL.format(p=p))
        time.sleep(1)
        found = _ROW.findall(page)
        if not found:
            break
        for date, href, sn, title in found:
            if sn in seen:
                continue
            seen.add(sn)
            rows.append((date, urljoin(SOURCE_HOME, href), sn,
                         _html.unescape(title).strip()))
        if len(rows) >= MAX_ITEMS:
            break
    rows = rows[:MAX_ITEMS]
    if not rows:
        raise RuntimeError("moi_press：清單頁抓到 0 筆，可能改版或被擋，視為失敗")

    items = []
    for date, url, sn, title in rows:
        if _deadline_hit(deadline):
            break
        doc = fetch(url)
        time.sleep(1)
        frag = _slice(doc, 'class="area-essay page-caption-p"',
                      ['class="area-editor system-info"', 'class="group page-footer"'])
        if not frag:
            frag = _slice(doc, 'id="CCMS_Content"', ['class="group page-footer"'])
        body = clean(frag)
        if not title:
            m = re.search(r'class="simple-text title".*?<h3>(.*?)</h3>', doc, re.S)
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
        raise RuntimeError("moi_press：內頁全部解析失敗")
    return items
