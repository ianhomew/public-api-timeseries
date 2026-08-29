"""金管會 裁罰案件（id=131，與現有 fsc_clarification 同網域同一套 CMS）。

清單：https://www.fsc.gov.tw/ch/home.jsp?id=131&parentpath=0,2&mcustomize=multimessages_list.jsp&page=<N>
內頁：https://www.fsc.gov.tw/ch/home.jsp?id=131&parentpath=0,2&mcustomize=multimessages_view.jsp&dataserno=<12碼>&dtable=Penalty

正文容器與 fsc_clarification 相同（class="ap" → 切到 <!--ap END -->），
本站已各自重新實測（2026-08-28），非假設沿用；<script> 內的「點閱率」readfile() 呼叫
會被 clean() 的 <script> 剝除，不會污染正文（fsc_clarification 曾因「瀏覽人次」文字誤報改寫，
本 adapter 已用切點驗證過內頁不含裸露的點閱數字文字節點）。
只用標準函式庫。每次 HTTP 請求後 time.sleep(1)，不並行。
"""
import re
import time

KEY = "fsc_penalty"
DESC = "金管會裁罰案件"
SOURCE_HOME = "https://www.fsc.gov.tw/ch/home.jsp?id=131&parentpath=0,2"
ROBOTS_VERIFIED = ("2026-08-28 親驗 https://www.fsc.gov.tw/robots.txt："
                   "User-agent: Googlebot / Disallow: /uploaddowndoc（附件下載目錄）。"
                   "與 fsc_clarification 同網域，重新親驗結果一致："
                   "僅對 Googlebot 禁止 /uploaddowndoc，對 * 無限制，目標 home.jsp 不在其下 → 允許")
ROOT = "https://www.fsc.gov.tw/ch/"
CH = {"id": "131", "parentpath": "0,2",
      "list_mc": "multimessages_list.jsp", "view_mc": "multimessages_view.jsp", "dtable": "Penalty"}
MAX_PAGES = 8          # 每年約34筆，最新100筆以內；每頁15筆，8頁=120筆已足夠覆蓋
PARSER_VERSION = 1

def _grab(raw, cls, clean):
    m = re.search(r'(?is)<div[^>]*class="' + cls + r'"[^>]*>(.*?)</div>', raw)
    return clean(m.group(1)) if m else ""

def _body(raw, clean):
    """從 class=ap 之後，切到 <!--ap END --> 為止（與 fsc_clarification 相同邏輯，
    避免把導覽選單／頁尾當成正文）。"""
    i = raw.find('class="ap"')
    if i < 0:
        i = raw.find('class="maincontent"')
    if i < 0:
        return ""
    k = raw.find(">", i)
    if 0 < k < i + 200:
        i = k + 1
    j = raw.find("<!--ap END -->", i)
    if j < 0:
        j = len(raw)
        for mark in ('class="fat_box', 'class="footer', 'id="footer"', 'class="gotop"'):
            m = raw.find(mark, i)
            if m > 0:
                j = min(j, m)
    return clean(re.sub(r"<[^>]*$", "", raw[i:j]))

def collect(fetch, clean):
    sernos, seen, page = [], set(), 1
    while page <= MAX_PAGES and len(sernos) < 100:
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
    sernos = sernos[:100]
    if not sernos:
        raise RuntimeError("fsc_penalty 清單 0 筆 —— 視為抓取失敗")
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
    if not items:
        raise RuntimeError("fsc_penalty 內頁全部解析失敗（可能改版）")
    return items
