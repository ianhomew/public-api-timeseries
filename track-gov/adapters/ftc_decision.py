"""公平交易委員會 本會行政決定（處分書及不處分決議書）

清單頁 decisionList.aspx 本身即已用 <ul class="result-list"> 結構化揭露
發文日期／類型／相關法條／案由全文，不需另外進入內頁（正文為 PDF 附件，
本 adapter 依規範不抓附件）。robots.txt 回應的是 ASP.NET 對未匹配路徑的
預設首頁內容（親驗：/robots.txt 與亂數不存在路徑回應長度相同），
故技術上無 Disallow 限制存在。

翻頁：官網翻頁為 ASP.NET WebForms postback（__doPostBack），純 GET query
string 對 ?page=N 無效。本 adapter 對第 1 頁用 harness 提供的 fetch()（GET，
含重試），第 2 頁起用第 1 頁拿到的 __VIEWSTATE / __VIEWSTATEGENERATOR /
__EVENTVALIDATION，透過『跳頁下拉選單』控制項
ctl00$ContentPlaceHolder1$dl_toPage 直接 POST 目標頁碼（非逐頁點『下一頁』），
實測可行、不需鏈式攜帶前一頁的 viewstate。只用 urllib.request（標準函式庫）。

2026-09-04 依 SPEC-y2-deadline.md 補上 collect(fetch, clean, deadline=None) 支援：
deadline 為驅動程式傳入的 UNIX 時間戳，本 adapter 在每次翻頁／每抓一筆內頁前檢查
time.time() < deadline，超過就停止並回傳已取得的資料（向下相容：deadline 為 None
時視為無時間限制，行為與舊版完全相同）。只新增提早停止的能力，不改動既有抓取邏輯、
欄位、排序或 MAX_ITEMS。
"""
import re, time, urllib.request, urllib.parse

KEY = "ftc_decision"
DESC = "公平交易委員會 本會行政決定（處分書及不處分決議書）"
SOURCE_HOME = "https://www.ftc.gov.tw/internet/main/decision/decisionList.aspx?mid=11"
ROBOTS_VERIFIED = ("2026-08-28 親驗 https://www.ftc.gov.tw/robots.txt：GET 回 200，"
                    "但內容是首頁 HTML（與亂數不存在路徑 /this-path-should-not-exist-zzz "
                    "回應長度相同，屬 ASP.NET 對未匹配路徑的預設頁，非真正 robots.txt）"
                    "→ 判定無真正 robots.txt，技術上無 Disallow 限制存在")

LIST_URL = "https://www.ftc.gov.tw/internet/main/decision/decisionList.aspx?mid=11"
UA = "snapshotter-research/1.0 (daily archival; public accountability; 1 req/sec; github.com/ianhomew/public-api-timeseries)"
ITEMS_PER_PAGE = 10
MAX_PAGES = 10          # 100 筆以內（latest100 政策）
PARSER_VERSION = 1

ITEM_RE = re.compile(
    r'<ul class="result-list">\s*'
    r'<li><span>發文日期</span><p>([^<]*)</p></li>\s*'
    r'<li><span>類型</span><p>([^<]*)</p></li>\s*'
    r'<li><span>相關法條</span><p>(.*?)</p></li>\s*'
    r'<li class="result-reason">\s*<span>案由</span>\s*'
    r"<a href='([^']*)'[^>]*title='[^']*'>.*?<p>(.*?)</p></a>",
    re.S,
)
VS_RE = re.compile(r'id="__VIEWSTATE" value="([^"]*)"')
VSG_RE = re.compile(r'id="__VIEWSTATEGENERATOR" value="([^"]*)"')
EV_RE = re.compile(r'id="__EVENTVALIDATION" value="([^"]*)"')


def _parse_items(raw, clean):
    out = []
    for date, kind, laws, pdf_url, reason_html in ITEM_RE.findall(raw):
        pid_m = re.search(r"/uploadDecision/([0-9a-fA-F-]+)\.pdf", pdf_url)
        if not pid_m:
            continue
        pid = pid_m.group(1)
        reason = clean(reason_html)
        laws_txt = clean(laws)
        if not reason:
            continue
        body = "類型：%s\n相關法條：%s\n案由：%s" % (kind.strip(), laws_txt, reason)
        out.append({
            "id": pid,
            "url": pdf_url,
            "title": reason,
            "date": date.strip(),
            "body_text": body,
        })
    return out


def _post_page(vs, vsg, ev, page):
    data = {
        "__EVENTTARGET": "ctl00$ContentPlaceHolder1$dl_toPage",
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": vs,
        "__VIEWSTATEGENERATOR": vsg,
        "__EVENTVALIDATION": ev,
        "ctl00$ContentPlaceHolder1$dl_toPage": str(page),
    }
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        LIST_URL, data=body,
        headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"},
    )
    last = None
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            if i < 2:
                time.sleep(3 * (i + 1))
    raise last


def _deadline_hit(deadline):
    return deadline is not None and time.time() >= deadline


def collect(fetch, clean, deadline=None):
    page1 = fetch(LIST_URL)
    items = _parse_items(page1, clean)
    if not items:
        raise RuntimeError("ftc_decision 第 1 頁清單 0 筆 —— 視為抓取失敗")

    vs_m, vsg_m, ev_m = VS_RE.search(page1), VSG_RE.search(page1), EV_RE.search(page1)
    if vs_m and vsg_m and ev_m and len(items) >= ITEMS_PER_PAGE:
        vs, vsg, ev = vs_m.group(1), vsg_m.group(1), ev_m.group(1)
        page = 2
        while len(items) < MAX_PAGES * ITEMS_PER_PAGE and page <= MAX_PAGES:
            if _deadline_hit(deadline):
                break
            time.sleep(1)
            raw = _post_page(vs, vsg, ev, page)
            new_items = _parse_items(raw, clean)
            if not new_items:
                break
            seen_ids = {it["id"] for it in items}
            new_items = [it for it in new_items if it["id"] not in seen_ids]
            if not new_items:
                break
            items.extend(new_items)
            page += 1

    return items[: MAX_PAGES * ITEMS_PER_PAGE]
