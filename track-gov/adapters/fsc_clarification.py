"""金管會即時新聞澄清（原 snap_gov.py 內建邏輯，改寫為 adapter）"""
import re, time

KEY = "fsc_clarification"
DESC = "金管會即時新聞澄清"
SOURCE_HOME = "https://www.fsc.gov.tw/ch/home.jsp?id=609&parentpath=0,7,478"
ROBOTS_VERIFIED = ("2026-08-26 親驗 https://www.fsc.gov.tw/robots.txt："
                   "唯一 Disallow 為 /uploaddowndoc（附件下載），目標 home.jsp 不在其下 → 允許")
ROOT = "https://www.fsc.gov.tw/ch/"
CH = {"id": "609", "parentpath": "0,7,478",
      "list_mc": "disputearea_list.jsp", "view_mc": "disputearea_view.jsp", "dtable": "News"}
MAX_PAGES = 50

def _grab(raw, cls, clean):
    m = re.search(r'(?is)<div[^>]*class="' + cls + r'"[^>]*>(.*?)</div>', raw)
    return clean(m.group(1)) if m else ""

def _body(raw, clean):
    """從 class=ap 起、到 footer 前。注意 page-edit 是內容容器，不是頁尾"""
    i = raw.find('class="ap"')
    if i < 0:
        i = raw.find('class="maincontent"')
    if i < 0:
        return ""
    j = len(raw)
    for mark in ('class="footer', 'id="footer"', 'class="gotop"'):
        k = raw.find(mark, i)
        if k > 0:
            j = min(j, k)
    k = raw.find(">", i)
    if 0 < k < i + 200:
        i = k + 1
    return clean(raw[i:j])

def collect(fetch, clean):
    sernos, seen, page = [], set(), 1
    while page <= MAX_PAGES:
        u = (ROOT + "home.jsp?id=" + CH["id"] + "&parentpath=" + CH["parentpath"] +
             "&mcustomize=" + CH["list_mc"] + "&page=" + str(page))
        found = re.findall(re.escape(CH["view_mc"]) + r"&dataserno=(\d+)", fetch(u))
        new = [s for s in dict.fromkeys(found) if s not in seen]
        if not new:
            break
        for s in new:
            seen.add(s); sernos.append(s)
        page += 1
        time.sleep(1)
    if not sernos:
        raise RuntimeError("fsc 清單 0 筆 —— 視為抓取失敗")
    items = []
    for s in sernos:
        u = (ROOT + "home.jsp?id=" + CH["id"] + "&parentpath=" + CH["parentpath"] +
             "&mcustomize=" + CH["view_mc"] + "&dataserno=" + s + "&dtable=" + CH["dtable"])
        raw = fetch(u)
        body = _body(raw, clean)
        if body:
            items.append({"id": s, "dataserno": s, "url": u,
                          "title": _grab(raw, "subject", clean),
                          "date": _grab(raw, "date", clean),
                          "body_text": body})
        time.sleep(1)
    return items
