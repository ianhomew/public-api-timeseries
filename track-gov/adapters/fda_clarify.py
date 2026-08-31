"""食藥署 食藥闢謠專區（news.aspx/newsContent.aspx GSP 類架構）

2026-08-31 因站方回應變慢（同一 URL 耗時從 2.76 秒飆到 14.77 秒），依 PERF_FIX_SPEC.md 修正 4，
MAX_ITEMS 由 100 降為 50；本站日增量約數筆，50 筆仍足以偵測改寫（重疊視窗遠大於日增量）。
同時依修正 2 支援 collect(fetch, clean, deadline=None)：deadline 為驅動程式傳入的 UNIX 時間戳，
本 adapter 在每次翻頁／每抓一筆內頁前檢查 time.time() < deadline，超過就停止並回傳已取得的資料
（向下相容：deadline 為 None 時視為無時間限制，行為與舊版完全相同）。
"""
import re, time

KEY = "fda_clarify"
DESC = "食藥署 食藥闢謠專區"
SOURCE_HOME = "https://www.fda.gov.tw/TC/news.aspx?cid=5049"
ROBOTS_VERIFIED = ("2026-08-28 親驗 https://www.fda.gov.tw/robots.txt："
                    "User-agent: * 僅 Disallow /TC/personalized*.aspx /TC/pwd.aspx /TraceClick.aspx，"
                    "目標 news.aspx / newsContent.aspx 不在其下 → 允許"
                    "（另有 User-agent: ClaudeBot / GPTBot 具名 Disallow: /，"
                    "本 adapter 使用自訂識別性 UA，非 ClaudeBot/GPTBot，不受此條款拘束）")
LIST_URL = "https://www.fda.gov.tw/TC/news.aspx?cid=5049&pn={page}"
DETAIL_URL = "https://www.fda.gov.tw/TC/newsContent.aspx?cid=5049&id={id}"
MAX_ITEMS = 50    # 2026-08-31：因站方回應變慢，由 100 降為 50；日增量約數筆，50 筆仍足以偵測改寫
PARSER_VERSION = 1

ROW_RE = re.compile(r'newsContent\.aspx\?cid=5049&id=(\d+)')


def _deadline_hit(deadline):
    return deadline is not None and time.time() >= deadline


def _list_ids(fetch, deadline=None):
    ids, seen, page = [], set(), 1
    while len(ids) < MAX_ITEMS:
        if _deadline_hit(deadline):
            break
        raw = fetch(LIST_URL.format(page=page))
        found = ROW_RE.findall(raw)
        new = [i for i in dict.fromkeys(found) if i not in seen]
        if not new:
            break
        for i in new:
            seen.add(i)
            ids.append(i)
        page += 1
        time.sleep(1)
    return ids[:MAX_ITEMS]


def _body(raw, clean):
    """正文只取 PnlCms 內的 <div class="edit marginBot">…</div>，
    切到 QRCode <img id="...imgQR"> 前為止，避免混入分享列、電子報訂閱、評分表單、導覽選單。
    注意：i 必須落在該 div 的開始標籤「之後」，否則裸露的 `class="edit marginBot">`
    字串前面沒有 `<`，clean() 的 <[^>]+> 規則抓不到，會殘留裸標籤片段。"""
    i = raw.find('class="edit marginBot"')
    if i < 0:
        return ""
    k = raw.find(">", i)
    if k < 0:
        return ""
    i = k + 1
    j = raw.find('imgQR', i)
    if j < 0:
        j = len(raw)
    frag = raw[i:j]
    frag = re.sub(r"<[^>]*$", "", frag)
    return clean(frag)


def collect(fetch, clean, deadline=None):
    ids = _list_ids(fetch, deadline)
    if not ids:
        raise RuntimeError("fda_clarify 清單 0 筆 —— 視為抓取失敗")

    items = []
    for nid in ids:
        if _deadline_hit(deadline):
            break
        url = DETAIL_URL.format(id=nid)
        raw = fetch(url)

        mt = re.search(r'<span class="fdtitle">(.*?)</span>', raw, re.S)
        title = clean(mt.group(1)) if mt else ""

        md = re.search(r'發布日期[：:]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})', raw)
        date = md.group(1) if md else ""

        body = _body(raw, clean)
        if body and title and date:
            # 標題本身即『傳言原文』的完整摘述（食藥署官方格式固定為
            # 「網傳『…』為假訊息，…」），與正文的『解答』互補，兩者合併
            # 才是完整記錄；也順帶避免極少數頁面正文只剩共用制式短句
            # （例如「食藥署提醒，沒有根據的傳言…」）在不同傳言間重複。
            body_full = title + "\n" + body
            items.append({
                "id": nid,
                "url": url,
                "title": title,
                "date": date,
                "body_text": body_full,
            })
        time.sleep(1)

    if not items:
        raise RuntimeError("fda_clarify 內頁全部解析失敗 —— 視為抓取失敗")
    return items
