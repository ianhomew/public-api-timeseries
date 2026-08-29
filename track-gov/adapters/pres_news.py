"""總統府新聞（本府新聞稿，Page/35 分類）

清單頁 /Page/35 由前端 JS（ViewComponents/News/index.js）呼叫
POST /WebAPI/News/List 做真分頁（detailno 參數），純 GET ?detailno=N
不會換頁（實測：page1 與 page1?detailno=2 回傳完全相同的 15 筆 id）。
本輪嘗試以 urllib 直接 POST 該 API（lang=zh-tw&country=TW&detailno=2，
含 X-Requested-With/Referer），伺服器一律回 400
{"content":"伺服器忙碌中，請稍後再試"}，判斷為需要瀏覽器端才會產生的
安全性 token（securityUtility.js 的雜湊）或其他反爬機制，本輪未能反解。

【假設，未能 0 UNKNOWNS，依規範自行選擇合理做法】
既然無法可靠翻頁，本 adapter 只抓清單首頁（server-rendered，穩定可
GET）能看到的最新 15 筆，不強行湊滿 100 筆上限（15 < 100，符合
『該類別總數少於 latest100 上限就全抓能抓到的』精神）。之後若反解出
真實分頁 API，可再放大 MAX_PAGES。

【踩到的坑：HiNetCDN 一次性 Cookie 挑戰，非 IP 封鎖】
內頁 /NEWS/<id> 由 HiNetCDN 代理，首次請求（無 __chtcdn cookie）一律回
308，且 Location 指回原網址本身（自我重導向迴圈），若用不帶 cookie 的
無狀態 fetch()（如 _harness.py 內建的 fetch，逐次開新連線不留
cookie）會被 urllib 判定為 redirect loop 直接 raise。實測只要把首次
308 回應帶的 Set-Cookie: __chtcdn=... 原樣回傳，第二次同一 URL 即回
200。本 adapter 因此自建 http.cookiejar 持久連線（僅用標準函式庫），
同一 session 內所有請求共用 cookie；不使用 harness 提供的無狀態
fetch()，改用等效但具 cookie 能力的 _fetch()（同樣具備 3 次重試與
1 req/sec 節流）。
"""
import re
import time
import http.cookiejar
import urllib.request

KEY = "pres_news"
DESC = "總統府新聞（本府新聞稿）"
SOURCE_HOME = "https://www.president.gov.tw/Page/35"
ROBOTS_VERIFIED = ("2026-08-28 親驗 https://www.president.gov.tw/robots.txt："
                    "User-agent: * / Allow: / ，全站無任何 Disallow → 允許")

LIST_URL = "https://www.president.gov.tw/Page/35"
DETAIL_URL = "https://www.president.gov.tw/NEWS/{id}"
UA = "snapshotter-research/1.0 (daily archival; public accountability; 1 req/sec; github.com/ianhomew/public-api-timeseries)"
MAX_ITEMS = 100
PARSER_VERSION = 1

ID_RE = re.compile(r'href="/NEWS/(\d+)"')
ARTICLE_MARK = 'class="article1"'
END_MARKS = ("<!-- 相關檔案 -->", "list8")

_cj = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cj))


def _fetch(url, retries=3):
    """帶 cookiejar 的 GET，用來通過 HiNetCDN 的一次性 cookie 挑戰。
    第一次請求若被 308 導回原網址（redirect loop），視為挑戰頁，
    重試時 cookiejar 已存有 __chtcdn，第二次即可取得正文。"""
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with _opener.open(req, timeout=45) as r:
                raw = r.read()
                enc = "utf-8"
                m = re.search(rb'charset=["\']?([\w-]+)', raw[:2000], re.I)
                if m:
                    enc = m.group(1).decode("ascii", "ignore")
                return raw.decode(enc, "ignore")
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(3 * (i + 1))
    raise last


def _body(raw, clean):
    i = raw.find(ARTICLE_MARK)
    if i < 0:
        return ""
    k = raw.find(">", i)
    if k < 0:
        return ""
    i = k + 1
    j = len(raw)
    for mark in END_MARKS:
        m = raw.find(mark, i)
        if m > 0:
            j = min(j, m)
    frag = raw[i:j]
    frag = re.sub(r"<[^>]*$", "", frag)
    return clean(frag)


def collect(fetch, clean):
    # 列表頁與內頁一律走本檔自建的 _fetch()（帶 cookiejar），
    # 不用 harness 傳入的無狀態 fetch，理由見檔頭說明。
    listing = _fetch(LIST_URL)
    time.sleep(1)
    ids = list(dict.fromkeys(ID_RE.findall(listing)))[:MAX_ITEMS]
    if not ids:
        raise RuntimeError("pres_news 清單 0 筆 —— 視為抓取失敗")

    items = []
    for nid in ids:
        url = DETAIL_URL.format(id=nid)
        raw = _fetch(url)

        mt = re.search(r'class="pageTitle1">(.*?)</div>', raw, re.S)
        title = clean(mt.group(1)) if mt else ""

        md = re.search(r'class="date">([^<]*)</span>', raw)
        date_roc = md.group(1).strip() if md else ""
        # 民國年轉西元年，統一格式方便下游比對；找不到就原樣保留
        mroc = re.match(r"(\d{2,3})年(\d{1,2})月(\d{1,2})日", date_roc)
        if mroc:
            y, mo, d = mroc.groups()
            date = "%d-%02d-%02d" % (int(y) + 1911, int(mo), int(d))
        else:
            date = date_roc

        body = _body(raw, clean)
        if body and title and date:
            items.append({
                "id": nid,
                "url": url,
                "title": title,
                "date": date,
                "body_text": body,
            })
        time.sleep(1)

    if not items:
        raise RuntimeError("pres_news 內頁全部解析失敗 —— 視為抓取失敗")
    return items
