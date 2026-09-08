# -*- coding: utf-8 -*-
"""ofac_sanctions_crypto：OFAC（美國財政部海外資產控制辦公室）SDN 制裁名單，含加密貨幣地址欄位。

對應規格：/Users/monica/Documents/temp/終端機/vps-161.97.82.83/adapters-wip/specs/batch4.md 4-A（A26）

已知的坑（2026-08-28 VPS 實測）：
    1. sdn.csv **沒有標頭列**，固定 12 欄，順序為：
       ent_num, SDN_Name, SDN_Type, Program, Title, Call_Sign, Vess_type,
       Tonnage, GRT, Vess_flag, Vess_owner, Remarks。
       空值一律填 "-0- "（含尾隨空白），不是真的空字串，取值時需 strip 並判斷是否等於 "-0-"。
    2. 沒有獨立的「Digital Currency Address」欄位——加密貨幣地址是**內嵌在 Remarks 自由文字裡**，
       格式如 "Digital Currency Address - TRX TNiq9AXBp9EjUqhDhrwrfvAA8U3GUQZH81; alt. Digital
       Currency Address - TRX TTiDLWE6...;"，須用正規表示式從 Remarks 解析出
       (幣別代碼, 地址) 配對。本輪實測 19,320 筆中僅 98 筆的 Remarks 含此欄位，其餘 SDN 名單筆數
       沒有登記加密貨幣地址（規格書已預告此為正常現象，不可視為解析失敗）。
    3. `www.treasury.gov/robots.txt` 本輪實測回 HTTP 200 但內容是一般 HTML 頁面（78,495B，
       非傳統 robots.txt 格式），無法解析出 Disallow 規則；依標準慣例（無法解析＝視同不存在＝
       無限制）處理。已另外實測確認 `/ofac/downloads/sdn.csv` 這個路徑本身能直接 200 下載，
       不會被導向首頁。
    4. 檔案較大（本輪實測 5,669,539B，下載耗時約 11.4 秒），fetch() 的 timeout 需由呼叫端設
       60 秒以上。

PARSER_VERSION 2（2026-09-08，恆真式守門修正第二批，見本機
docs/0908-4-tautological-gates-report.md §3.1）：
    先前 collect() 只回傳 `"count": len(items)`，而 track-crypto/scripts/detect_delistings.py
    的完整性守門就是拿這個 count 去比 len(items) —— **自報值與被檢查對象是同一個數字，
    判斷式恆為假、守門恆為真，對「CSV 只下載到一半」零防護力**。
    本輪親打上游查明：OFAC 對**同一次發布**另外提供 SDN.XML，檔頭有
        <publshInformation><Publish_Date>09/04/2026</Publish_Date>
                           <Record_Count>19329</Record_Count></publshInformation>
    這是一個**獨立於本 adapter 計算結果**的上游自報總數。2026-09-08 實測驗證：
        sdn.csv 資料列數 19,329 ＝ SDN.XML sdnEntry 元素數 19,329 ＝ Record_Count 19,329，
        兩邊 uid 集合互相差集皆為 0（完全相同的 19,329 個 ent_num）。
    因此本版新增 `reported_total` 欄位（值＝Record_Count），供守門做**真正的**比對。
    成本控制：SDN.XML 全檔 28,978,335B，但本 adapter 只用 HTTP Range 取前 4KB
    （實測回 206 Partial Content，Content-Range: bytes 0-2047/28978335），
    Record_Count 一定落在檔頭前 512B 內（實測 512B 即可解析出）。
    fail-open 設計：這是**次要訊號**，任何失敗（Range 不被支援、逾時、格式改變）
    一律讓 reported_total = None、把原因記在 reported_total_error，
    **絕不讓主要資料（sdn.csv）的抓取因此失敗**；守門讀不到這個欄位時會退回
    區間檢查（detect_delistings.py 的 legacy_range 分支）。
"""
import csv
import io
import re

KEY = "ofac_sanctions_crypto"
DESC = "OFAC SDN 制裁名單（美國財政部），含內嵌於 Remarks 的加密貨幣地址欄位"
SOURCE_HOME = "https://www.treasury.gov/ofac/downloads/sdn.csv"
# 同一次發布的 XML 版本，只用 HTTP Range 取檔頭解析 <Record_Count>（見模組說明）。
# 主選 sanctionslistservice：2026-09-08 實測 `www.treasury.gov/ofac/downloads/sdn.csv`
# 本身就是 302 轉到 `sanctionslistservice.ofac.treas.gov/api/publicationpreview/exports/sdn.csv`
# 再轉 S3 預簽網址 —— **兩個網址供應的是同一份位元組**（Content-Range 全長、
# Digest(sha-256)、Last-Modified 三者皆一致，實測見 evidence/ofac/PROBE-ofac.md §4.4／§5），
# 所以走 sanctionslistservice 不是「換一套發布管線」，只是**跳過 Akamai 那層轉址殼**：
# 實測 Range 請求 1.52s vs 9.62～10.87s（後者的 ttfb 有 9.07s 花在 302 本身）。
# 兩個主機的 robots 皆無限制（前者 404、後者回 HTML 非 robots 格式）。
SDN_XML_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.XML"
# 備援：主選失敗時改打 Akamai 這一份（同一份檔案，只是慢 ~9 秒）。
SDN_XML_URL_FALLBACK = "https://www.treasury.gov/ofac/downloads/sdn.xml"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗：www.treasury.gov/robots.txt 回 HTTP 200 但為一般 HTML 頁面"
    "（78,495B，非傳統 robots.txt 格式，無法解析出 Disallow 規則，依慣例視同無限制）；"
    "sanctionslistservice.ofac.treas.gov/robots.txt 回 404（無限制，備選端點未採用）；"
    "已另外實測確認 /ofac/downloads/sdn.csv 本身可直接 200 下載，不會被導向首頁。"
    "2026-09-08 複驗（新增 sdn.xml 檔頭 Range 請求前）：www.treasury.gov/robots.txt "
    "仍為 HTML 頁面（78,839B，無 Disallow 規則）；home.treasury.gov/robots.txt 為 "
    "'User-agent: * / Allow: /'；/ofac/downloads/sdn.xml 與 sdn.csv 同主機同目錄，"
    "適用同一份（無限制的）判定，且該路徑實測可直接 200/206 下載"
)
PARSER_VERSION = 2

# SDN.CSV 固定 12 欄、無標頭列（本輪實測確認），順序如下：
_COLS = (
    "ent_num", "sdn_name", "sdn_type", "program", "title", "call_sign",
    "vess_type", "tonnage", "grt", "vess_flag", "vess_owner", "remarks",
)

MIN_ROWS = 15000

_DCA_RE = re.compile(r"Digital Currency Address\s*-\s*([A-Za-z0-9]+)\s+([A-Za-z0-9]+)")

# SDN.XML 檔頭的發布中繼資料（PARSER_VERSION 2 新增）。
# 實測檔頭（前 512B）長這樣：
#   <?xml version="1.0" encoding="UTF-8"?><sdnList xmlns=...><publshInformation>
#   <Publish_Date>09/04/2026</Publish_Date><Record_Count>19329</Record_Count>
#   </publshInformation><sdnEntry>...
_XML_HEAD_RANGE = "bytes=0-4095"   # 只取前 4KB；實測 512B 就夠，留 8 倍餘裕
_RECORD_COUNT_RE = re.compile(r"<Record_Count>\s*(\d+)\s*</Record_Count>")
_PUBLISH_DATE_RE = re.compile(r"<Publish_Date>\s*([^<]{1,40}?)\s*</Publish_Date>")


def _fetch_reported_total(fetch):
    """用 HTTP Range 取 SDN.XML 檔頭，解析出上游自報的 (Record_Count, Publish_Date)。

    回傳 dict：{"reported_total": int|None, "publish_date": str|None,
                "head_bytes": int|None, "error": str|None}

    **fail-open**：這是次要訊號（給下架偵測的完整性守門用），任何失敗都只回 None
    並記下原因，絕不拋例外——主要資料是 sdn.csv，不可以因為這個附加請求而整個來源失敗。
    守門端讀不到 reported_total 時會退回區間檢查（見 detect_delistings.py
    completeness_group() 的 reported_total_match 分支）。
    """
    out = {"reported_total": None, "publish_date": None, "head_bytes": None,
           "url": None, "error": None}
    errors = []
    for url in (SDN_XML_URL, SDN_XML_URL_FALLBACK):
        try:
            head = fetch(url, headers={"Range": _XML_HEAD_RANGE}, timeout=60)
        except Exception as e:                                # noqa: BLE001（fail-open，見上）
            errors.append("%s -> %s: %s" % (url, type(e).__name__, e))
            continue
        if not isinstance(head, str):
            errors.append("%s -> 回應型別非字串：%s" % (url, type(head).__name__))
            continue
        m = _RECORD_COUNT_RE.search(head)
        if not m:
            # Range 不被支援時上游會回整份 29MB（HTTP 200），此時 Record_Count 仍在最前面
            # 一定找得到；真的找不到代表 XML 格式改變了 -> 誠實記錄，不猜。
            errors.append("%s -> 檔頭前 %d 字元內找不到 <Record_Count>" % (url, len(head)))
            continue
        out["reported_total"] = int(m.group(1))
        out["head_bytes"] = len(head)
        out["url"] = url
        md = _PUBLISH_DATE_RE.search(head)
        if md:
            out["publish_date"] = md.group(1)
        if errors:                       # 主選失敗、備援成功：保留主選的失敗原因供稽核
            out["error"] = "已改用備援網址；" + "；".join(errors)
        return out
    out["error"] = "；".join(errors) or "未知失敗"
    return out


def _cell(v):
    v = (v or "").strip()
    return "" if v == "-0-" else v


def _parse_digital_currency_addresses(remarks):
    """從 Remarks 自由文字解析出 [(幣別代碼, 地址), ...]，可能為空清單。"""
    return [(m.group(1), m.group(2)) for m in _DCA_RE.finditer(remarks or "")]


def collect(fetch) -> dict:
    """抓取 OFAC SDN CSV 清單並解析出加密貨幣地址欄位。

    fetch(url) 需回傳已解碼的 CSV 全文字串（沿用本專案 fetch() 的 GET+解碼慣例）。
    失敗一律讓例外往上拋，不吞例外、不回傳空資料。
    """
    raw = fetch(SOURCE_HOME)
    # OFAC sdn.csv 尾端帶 DOS 時代的 EOF 控制字元 \x1a（Ctrl-Z），
    # 先清掉字串尾端的 \x1a 與空白，避免它被 csv reader 解析成殘缺的一列。
    raw = raw.rstrip().rstrip("\x1a").rstrip()
    reader = csv.reader(io.StringIO(raw))
    rows = []
    for r in reader:
        if not r:
            continue
        # 整列只有控制字元（如單獨的 \x1a）或空白字串，視為檔案尾端雜訊，跳過不當格式錯誤。
        # 但只跳過「這種特定情況」：整列只有 1 欄，且該欄去除控制字元/空白後為空。
        if len(r) == 1 and r[0].strip("\x1a \t\r\n") == "":
            continue
        rows.append(r)

    if len(rows) < MIN_ROWS:
        raise RuntimeError(
            f"ofac_sanctions_crypto：僅取得 {len(rows)} 筆，低於驗收下限 {MIN_ROWS}，"
            "視為下載不完整"
        )

    items = []
    uids = set()
    with_dca = 0
    for r in rows:
        if len(r) < len(_COLS):
            # 個別行欄位數不足是格式異常（且已排除上方的尾端雜訊列），直接拋出，
            # 避免下游拿到殘缺資料，也避免掩蓋真實的格式變更。
            raise RuntimeError(f"ofac_sanctions_crypto：某列欄位數不足 12：{r!r}")
        rec = dict(zip(_COLS, (_cell(v) for v in r)))
        uid = rec["ent_num"]
        name = rec["sdn_name"]
        if not uid or not name:
            raise RuntimeError(f"ofac_sanctions_crypto：某筆缺少 UID 或姓名/實體名稱：{r!r}")
        if uid in uids:
            raise RuntimeError(f"ofac_sanctions_crypto：UID 重複 {uid!r}")
        uids.add(uid)

        dca = _parse_digital_currency_addresses(rec["remarks"])
        if dca:
            with_dca += 1

        items.append({
            "uid": uid,
            "sdn_name": name,
            "sdn_type": rec["sdn_type"],
            "program": rec["program"],
            "title": rec["title"],
            "remarks": rec["remarks"],
            "digital_currency_addresses": [
                {"currency": c, "address": a} for c, a in dca
            ],
        })

    # PARSER_VERSION 2（2026-09-08）：抓完 CSV 之後**立刻**取 XML 檔頭，讓兩個數字
    # 在時間上盡量貼近（兩次請求相隔數秒；OFAC 若正好在這中間發布新版，
    # 兩邊會落在不同版本上 —— 守門的容忍度 max(5, 0.1%×total) 就是為此保留的）。
    rt = _fetch_reported_total(fetch)

    return {
        "count": len(items),                       # 本次實際解析出幾筆（＝len(items)）。
                                                   # ⚠️ 這個數字**不可以**拿來當完整性守門的
                                                   # 比對基準（那是恆真式），只是誠實回報本次筆數。
        "with_digital_currency_address": with_dca,
        # 以下三個欄位為 PARSER_VERSION 2 新增：上游（SDN.XML 檔頭）自報的總數與發布日期。
        # reported_total 為 None 代表本次取不到（原因見 reported_total_error），
        # 守門會自動退回區間檢查，不會因此判定失敗。
        "reported_total": rt["reported_total"],
        "reported_total_source": (rt["url"] or SDN_XML_URL) + " #publshInformation/Record_Count",
        "sdn_publish_date": rt["publish_date"],
        "reported_total_error": rt["error"],
        "items": items,
    }
