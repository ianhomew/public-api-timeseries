"""總統府新聞（本府新聞稿，Page/35 分類）— v2：反解 POST /WebAPI/News/List 分頁

【v2 反解結果摘要，2026-09-01，詳見 docs/pres-news-plan.md】
清單頁 /Page/35 由前端 ViewComponents/News/index.js 的 Search() 呼叫
POST /WebAPI/News/List 做真分頁（detailno=頁碼，每頁固定 15 筆，最新在前）。

v1（舊版）誤判為「需要瀏覽器端才會產生的安全性 token」而放棄，只抓清單首頁 15 筆。
重新逐一比對前端原始碼（未執行 JS，純讀取 formUtility.js / headerUtility.js /
webMenuUtility.js / getUtility.js）後找到根因：v1 送出的 payload 只有
`lang/country/detailno` 三個欄位，**少了 4 個欄位**：
formUtility.js 的 SetPostAjaxObject() 在送出前一律呼叫 callbackParseDataEvent()，
若 data.tag／data.no 未設定，會用 WebMenuUtility.Parse(location.pathname) 解析目前
路徑，注入 tag/no/dno/dtitle 四個欄位；對 /Page/35 而言即
{Tag:"Page", TagNo:"35", DNo:"", DTitle:""}。
另外 headerUtility.js 的 GetDefaultHeaders() 會送出 CUSTOMER-CSRF-HEADER2 header，
但頁面上並不存在對應的 CustomerFieldName/CustomerFieldName2 隱藏欄位，
故此 header 對匿名訪客恆為**空字串**——不是動態計算的 token，純 HTTP 可完全重現。

實測驗證（2026-09-01，唯讀、每次請求間隔 >= 1 秒）：
1. 用還原後的完整 payload 直接 POST，HTTP 200，頁與頁之間 id 無縫銜接、零重複
   （page1 最後一筆與 page2 第一筆恰好相差 1）。
2. 全新 session（不訪問清單頁、無任何 cookie）直接跳頁一樣成功 → 此 API 對這個
   payload 完全無狀態，不需要先訪問清單頁換 cookie，也不需要維持 session。
3. 重覆查詢同一頁（間隔數分鐘）id 集合完全相同 → 排序穩定，可放心用於重試/續抓。
4. SSR 清單頁的 `.pageBar` 分頁列標記 data-page="1960" 為「最末頁」；實測該頁僅 8 筆，
   官方精確總筆數 = 1959*15+8 = 29,393 筆（遠超過 latest100 政策上限，只抓最新 100 筆）。
5. 內頁 /NEWS/<id> 用純 requests.Session().get()（無任何自訂 cookie 邏輯，等效於本檔
   collect() 收到的驅動程式 fetch()）連續測 3 篇（橫跨新舊）皆一次 200、零重導向，
   v1 檔頭記載的 HiNetCDN 一次性 cookie 挑戰本輪未重現，故 v2 內頁直接改用驅動程式
   fetch()，不再自建 cookiejar／opener（同時符合 SPEC 對『沿用驅動程式 fetch、不要
   自己開連線』的要求）。

【架構】
分頁用的 POST /WebAPI/News/List 驅動程式的 fetch() 不支援（fetch() 只做 GET），
故沿用本專案既有慣例（見 moea_press.py／ftc_decision.py 皆為同樣情境）：分頁另建
一個只用標準函式庫 urllib 的輕量請求函式 _fetch_list_page()，內頁一律用驅動程式
傳入的 fetch()。分頁 POST 已證實無狀態，不需要 cookie/session 接續，每次請求各自
獨立、帶 3 次重試（與驅動程式 fetch() 的重試次數一致）。
"""
import re
import time
import urllib.request
import urllib.parse

KEY = "pres_news"
DESC = "總統府新聞（本府新聞稿）"
SOURCE_HOME = "https://www.president.gov.tw/Page/35"
ROBOTS_VERIFIED = ("2026-09-01 親驗 https://www.president.gov.tw/robots.txt："
                    "User-agent: * / Allow: / ，全站無 Disallow → 允許（含 /WebAPI/）")

LIST_API = "https://www.president.gov.tw/WebAPI/News/List"
LIST_REFERER = "https://www.president.gov.tw/Page/35"
DETAIL_URL = "https://www.president.gov.tw/NEWS/{id}"
UA = ("snapshotter-research/1.0 (daily archival; public accountability; 1 req/sec; "
      "github.com/ianhomew/public-api-timeseries)")

MAX_ITEMS = 100
MAX_PAGES = 7          # ceil(100/15)：每頁固定 15 筆，7 頁 = 105 筆 >= 100（latest100 政策）
PARSER_VERSION = 2      # v1=1（僅首頁 15 筆／自建 cookiejar）；v2=改真分頁＋改用驅動程式 fetch()

ID_RE = re.compile(r'href="/NEWS/(\d+)"')
ARTICLE_MARK = 'class="article1"'
END_MARKS = ("<!-- 相關檔案 -->", "list8")


def _fetch_list_page(detailno, retries=3):
    """POST /WebAPI/News/List 取得第 detailno 頁（1 起算，每頁固定 15 筆，最新在前）。
    payload 反解自前端 index.js 的 Search() + formUtility.js 的
    SetPostAjaxObject()／webMenuUtility.js 的 WebMenuUtility.Parse("/Page/35")，
    詳見檔頭說明。已實測此端點對此 payload 完全無狀態，每次獨立請求即可，
    不需要携帶前一次回應的 cookie。只用標準函式庫，與 moea_press.py／
    ftc_decision.py 的既有慣例一致。"""
    data = urllib.parse.urlencode({
        "sdate": "", "edate": "", "searchby": "",
        "lang": "zh-tw", "country": "TW", "detailno": detailno,
        "tag": "Page", "no": "35", "dno": "", "dtitle": "",
    }).encode("utf-8")
    req = urllib.request.Request(
        LIST_API, data=data,
        headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": LIST_REFERER,
            "Origin": "https://www.president.gov.tw",
            # 頁面上沒有 CustomerFieldName/2 隱藏欄位，前端一律送空字串，
            # 不是需要瀏覽器運算的動態 token，見檔頭「關鍵發現 1」。
            "CUSTOMER-CSRF-HEADER2": "",
        },
    )
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(2 * (i + 1))
    raise last


def _deadline_hit(deadline):
    return deadline is not None and time.time() >= deadline


def _list_ids(deadline=None):
    """依序翻頁蒐集最新 MAX_ITEMS 筆 id（去重、保序）。任何一頁 0 筆新 id 視為到底，停止。"""
    ids, seen = [], set()
    page = 1
    while len(ids) < MAX_ITEMS and page <= MAX_PAGES:
        if _deadline_hit(deadline):
            break
        raw = _fetch_list_page(page)
        time.sleep(1)
        new = [i for i in dict.fromkeys(ID_RE.findall(raw)) if i not in seen]
        if not new:
            break
        for nid in new:
            seen.add(nid)
            ids.append(nid)
        page += 1
    return ids[:MAX_ITEMS]


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


def collect(fetch, clean, deadline=None):
    ids = _list_ids(deadline)
    if not ids:
        raise RuntimeError("pres_news 清單 0 筆 —— 視為抓取失敗")

    items = []
    for nid in ids:
        if _deadline_hit(deadline):
            break
        url = DETAIL_URL.format(id=nid)
        raw = fetch(url)

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
