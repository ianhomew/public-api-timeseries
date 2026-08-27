# -*- coding: utf-8 -*-
"""勞動部「新聞稿」每日快照 adapter（只用標準函式庫）。"""
import re, time

KEY = "mol_press"
DESC = "勞動部新聞稿"
ROBOTS_VERIFIED = (
    "2026-08-27 親驗 https://www.mol.gov.tw/robots.txt：全文為 'user-agent: *' + "
    "'disallow: /bin/*'、'disallow: /App_Data/*'、'disallow: /App_Plugins/*'、"
    "'disallow: /Umbraco/*'；本 adapter 只取 /1607/1632/1633/ 之下的清單與內頁 → 未被 Disallow"
)
SOURCE_HOME = "https://www.mol.gov.tw/1607/1632/1633/lpsimplelist"

ORIGIN = "https://www.mol.gov.tw"
NODE = "/1607/1632/1633"
LIST_URL = ORIGIN + NODE + "/lpsimplelist?Page=%d&PageSize=40"

PAGE_SIZE = 40        # 站方下拉選單允許的最大值（10/20/30/40）
MAX_PAGES = 3         # 寫死分頁上限 → 最多 120 筆，再截到 100
MAX_ITEMS = 100

BLOCK_RE = re.compile(r'<div class="item_list2">(.*?)</div>\s*</div>', re.S)
LINK_RE = re.compile(r'href="(' + NODE + r'/(\d+)/post)"[^>]*title="(.*?)"', re.S)
DATE_RE = re.compile(r'發布日期：([0-9]{4}-[0-9]{2}-[0-9]{2})')
SEC_RE = re.compile(r'<section class="cp">(.*?)</section>', re.S)
BODY_RE = re.compile(r'<body[^>]*>(.*?)</body>', re.S)
DROP_RE = re.compile(
    r'(?is)<div class="pic">.*?</picture>|<div class="related_photoblock">.*?</div>\s*</div>\s*</div>'
    r'|<ul class="publish_info_top">.*?</ul>|<ul class="publish_info_down">.*?</ul>'
    r'|<div class="file_download.*?</div>')


def _list_page(fetch, page):
    html = fetch(LIST_URL % page)
    time.sleep(1)
    out = []
    for chunk in html.split('<div class="item_list2">')[1:]:
        m = LINK_RE.search(chunk)
        if not m:
            continue
        d = DATE_RE.search(chunk)
        out.append((m.group(2), ORIGIN + m.group(1),
                    re.sub(r"\s+", " ", m.group(3)).strip(),
                    d.group(1) if d else ""))
    return out


def collect(fetch, clean):
    seen, metas = set(), []
    for p in range(1, MAX_PAGES + 1):
        rows = _list_page(fetch, p)
        if not rows:
            break
        new = 0
        for nid, url, title, date in rows:
            if nid in seen:
                continue
            seen.add(nid)
            metas.append((nid, url, title, date))
            new += 1
        if new == 0 or len(metas) >= MAX_ITEMS:
            break
    metas = metas[:MAX_ITEMS]
    if not metas:
        raise RuntimeError("勞動部新聞稿清單抓到 0 筆（版面可能改版）")

    items = []
    for nid, url, title, date in metas:
        html = fetch(url)
        time.sleep(1)
        sec = SEC_RE.search(html)
        frag = sec.group(1) if sec else ""
        inner = BODY_RE.search(frag)          # 內文是巢狀的完整 html 片段
        frag = inner.group(1) if inner else DROP_RE.sub(" ", frag)
        body = clean(frag)
        if not date:
            d = DATE_RE.search(html) or re.search(r'發布日期:([0-9\-]{8,10})', html)
            date = d.group(1) if d else ""
        if len(body) < 50:
            continue
        items.append({"id": nid, "url": url, "title": title,
                      "date": date, "body_text": body})
    if not items:
        raise RuntimeError("勞動部新聞稿內頁全部解析失敗")
    return items
