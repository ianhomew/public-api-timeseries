#!/usr/bin/env python3
"""經濟部「本部新聞」（新聞稿）每日快照 adapter（track-gov 政府公告快照）。

只用標準函式庫。每次 HTTP 請求後 time.sleep(1)，不並行。

坑 1（清單分頁）：清單頁是 ASP.NET WebForms，頁碼鈕是 <input type="submit">
（postback），不是可以拼 querystring 的 GET 連結。換頁必須：
  1) 先 GET 首頁一次，取得 __VIEWSTATE / __VIEWSTATEGENERATOR /
     __EVENTVALIDATION 三個隱藏欄位，以及回應標頭的 Set-Cookie
     （ASP.NET_SessionId、__AntiXsrfToken 兩者都要）。
  2) 之後每換一頁，用同一 URL 發 POST，帶最新的三個隱藏欄位 + 該頁頁碼鈕的
     name=value，Cookie header 帶回上一步兩個 cookie。
     兩個 cookie 只要少一個，站方就會把請求導到
     ../../Error/GenericErrorPage.aspx，回傳「很抱歉，目前無法顯示這個頁面」
     的錯誤頁而不是清單（HTTP 200，但內容是錯誤頁，不會是 4xx/5xx，
     必須用「解析不到任何 news_id」來判斷失敗，不能只看 status code）。
  3) 頁碼鈕清單是「以目前頁為中心的滑動視窗」（例如第 10 頁時視窗顯示
     5~14，不是 1~10），所以每次都要在「當下這一頁的回應」裡重新找
     「下一頁」那顆按鈕的 name，不能假設固定的 ctlNN 對應固定頁碼。
內頁（News.aspx?...&news_id=NNNNN）是一般 GET、不吃 cookie，直接用
harness 提供的 fetch() 即可。

坑 2（正文邊界）：正文 <div class="div-left-info"> 前面緊接著就是
「點閱數」瀏覽次數計數器（在同一張卡片但不同的 div），若切點抓早了
（例如整段 class="div-content-white100" 或更外層）會把點閱數一起吃進來，
每天都會變 → 假性「內容改寫」。div-left-info 之後的兄弟節點依序是
「相關檔案／相關圖片」側欄（div-right-info，僅在有附件/圖片時才出現）
與頁尾的「相關內容」相關新聞輪播（slick carousel），也都不能算進正文。
本 adapter 用「深度計數」精確切出 div-left-info 這一層，不依賴後面
是否存在 div-right-info（很多篇沒有附件/圖片，這個 sibling 根本不存在）。

坑 3（假日期欄位）：頁面 <meta name="DC.Date" content="2009-09-09" /> 與
<meta name="DC.Coverage.t.min/max"> 是全站共用的樣板固定值，所有文章
都是同一組數字，完全不是該篇文章的發布日期，不能拿來當 date 欄位。
真正的日期來自清單頁 lblBeginDate 那個 span（YYYY-MM-DD）。
"""
import re
import time
import html as _html
import urllib.request
import urllib.parse

KEY = "moea_press"
PARSER_VERSION = 1
DESC = "經濟部本部新聞（新聞稿）"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗 https://www.moea.gov.tw/robots.txt（HTTP 200，64 bytes，"
    "last-modified 2023-09-25，快取穩定，非動態產生）。全文只有四行：\n"
    "  User-Agent:ZoomEye\n  Disallow:/\n  User-Agent:*\n  Disallow:/MNS_OLD/\n"
    "第一段只針對具名爬蟲 ZoomEye 全站封鎖，與本 adapter 的 UA 無關；"
    "第二段 'User-Agent:*' 對所有其他 UA（含本 adapter）只禁止 /MNS_OLD/ "
    "這個舊站目錄。本 adapter 目標路徑 /MNS/populace/news/News.aspx 屬於 "
    "/MNS/（新站），不是 /MNS_OLD/，不落在任何 Disallow 之下 → 允許抓取。"
    "先前文件將第一段 ZoomEye 專屬的 'Disallow:/' 誤讀為全站封鎖，"
    "經本次重新親驗證實為誤讀；本次親驗結果與誤讀說法不同，以本次親驗為準。"
)
SOURCE_HOME = "https://www.moea.gov.tw/MNS/populace/news/News.aspx?kind=1&menu_id=40"

ORIGIN = "https://www.moea.gov.tw"
LIST_URL = ORIGIN + "/MNS/populace/news/News.aspx?kind=1&menu_id=40"
DETAIL_URL = ORIGIN + "/MNS/populace/news/News.aspx?kind=1&menu_id=40&news_id=%s"

UA = ("snapshotter-research/1.0 (daily archival; public accountability; 1 req/sec; "
      "github.com/ianhomew/public-api-timeseries)")

MAX_PAGES = 10          # 站方每頁固定 10 筆、寫死分頁上限：10 頁 x 10 筆 = 100 筆（SPEC 上限）
MAX_ITEMS = 100

ROW_RE = re.compile(
    r'<a id="holderContent_grdNews_lnkTitle_\d+" href="\.\./news/News\.aspx\?'
    r'kind=\d+&amp;menu_id=\d+&amp;news_id=(\d+)">(.*?)</a>.*?'
    r'class="begin-date-time d-inline-block d-md-none">([\d\-]+)&nbsp;</span>',
    re.S,
)
PAGER_RE = re.compile(
    r'name="(ctl00\$holderContent\$grdNews\$ctl\d+\$uctlPages\$dltPage\$ctl\d+\$btnPage)"'
    r'\s+value="([^"]*)"'
)
HIDDEN_NAMES = ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")


def _http(data=None, cookie=None, retries=3):
    """對 LIST_URL 發 GET（data=None）或 POST（data=bytes）。回傳 (html, set_cookie_list)。"""
    headers = {"User-Agent": UA}
    if cookie:
        headers["Cookie"] = cookie
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["Referer"] = LIST_URL
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(LIST_URL, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read()
                cookies = r.headers.get_all("Set-Cookie") or []
                return raw.decode("utf-8", "ignore"), cookies
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(3 * (i + 1))
    raise last


def _cookie_header(set_cookie_list):
    jar = {}
    for c in set_cookie_list:
        kv = c.split(";", 1)[0]
        if "=" in kv:
            k, v = kv.split("=", 1)
            jar[k.strip()] = v.strip()
    if "ASP.NET_SessionId" not in jar or "__AntiXsrfToken" not in jar:
        return None
    return "ASP.NET_SessionId=%s; __AntiXsrfToken=%s" % (
        jar["ASP.NET_SessionId"], jar["__AntiXsrfToken"])


def _hidden_fields(doc):
    out = {}
    for name in HIDDEN_NAMES:
        m = re.search(r'id="%s"[^>]*value="([^"]*)"' % re.escape(name), doc)
        out[name] = m.group(1) if m else ""
    return out


def _pager_field(doc, page):
    target = str(page)
    for name, value in PAGER_RE.findall(doc):
        if value.strip() == target:
            return name, value
    return None


def _extract_balanced_div(doc, marker):
    """從 marker 往前找到所屬 <div ...> 的起點，用深度計數找對應的 </div>，
    回傳中間內容（不含頭尾標籤）。用深度計數而非「找下一個 </div>」或
    「找下一個已知 sibling 標記」，是因為 sibling（相關檔案/相關圖片側欄）
    不一定存在，且深度計數對「正文裡以後被加進巢狀 div」也不會誤切。"""
    mi = doc.find(marker)
    if mi < 0:
        return ""
    start_tag = doc.rfind("<div", 0, mi + 1)
    if start_tag < 0:
        return ""
    gt = doc.find(">", start_tag)
    if gt < 0:
        return ""
    content_start = gt + 1
    depth = 1
    pos = content_start
    tag_re = re.compile(r"<(/?)div\b", re.I)
    while depth > 0:
        m = tag_re.search(doc, pos)
        if not m:
            # 理論上不會發生（找不到收尾）；防禦性處理，去掉尾端殘缺標籤
            return re.sub(r"<[^>]*$", "", doc[content_start:])
        if m.group(1) == "/":
            depth -= 1
            if depth == 0:
                return doc[content_start:m.start()]
        else:
            depth += 1
        pos = m.end()
    return ""


def _collect_list():
    """回傳 [(news_id, title, date), ...]，最新在前，最多 MAX_ITEMS 筆。"""
    doc, cookies = _http()
    time.sleep(1)
    cookie_header = _cookie_header(cookies)
    if not cookie_header:
        raise RuntimeError("moea_press：清單頁未取得 session/anti-xsrf cookie，站方可能改版")

    rows, seen = [], set()
    page = 1
    while True:
        found = ROW_RE.findall(doc)
        new = 0
        for news_id, title_raw, date in found:
            if news_id in seen:
                continue
            seen.add(news_id)
            title = re.sub(r"\s+", " ", _html.unescape(title_raw)).strip()
            rows.append((news_id, title, date))
            new += 1
        if new == 0 or len(rows) >= MAX_ITEMS or page >= MAX_PAGES:
            break
        nxt = page + 1
        field = _pager_field(doc, nxt)
        if field is None:
            break
        hidden = _hidden_fields(doc)
        hidden[field[0]] = field[1]
        body = urllib.parse.urlencode(hidden).encode("utf-8")
        doc, _ = _http(data=body, cookie=cookie_header)
        time.sleep(1)
        page = nxt
    return rows[:MAX_ITEMS]


def collect(fetch, clean):
    rows = _collect_list()
    if not rows:
        raise RuntimeError("moea_press：清單抓到 0 筆，可能改版或被擋，視為失敗")

    items = []
    for news_id, title, date in rows:
        url = DETAIL_URL % news_id
        doc = fetch(url)
        time.sleep(1)
        frag = _extract_balanced_div(doc, 'class="div-left-info"')
        body = clean(frag)
        if len(body) < 50:
            continue
        items.append({
            "id": news_id,
            "url": url,
            "title": title,
            "date": date,
            "body_text": body,
        })
    if not items:
        raise RuntimeError("moea_press：內頁全部解析失敗")
    return items
