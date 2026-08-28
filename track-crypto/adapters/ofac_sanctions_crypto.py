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
"""
import csv
import io
import re

KEY = "ofac_sanctions_crypto"
DESC = "OFAC SDN 制裁名單（美國財政部），含內嵌於 Remarks 的加密貨幣地址欄位"
SOURCE_HOME = "https://www.treasury.gov/ofac/downloads/sdn.csv"
ROBOTS_VERIFIED = (
    "2026-08-28 親驗：www.treasury.gov/robots.txt 回 HTTP 200 但為一般 HTML 頁面"
    "（78,495B，非傳統 robots.txt 格式，無法解析出 Disallow 規則，依慣例視同無限制）；"
    "sanctionslistservice.ofac.treas.gov/robots.txt 回 404（無限制，備選端點未採用）；"
    "已另外實測確認 /ofac/downloads/sdn.csv 本身可直接 200 下載，不會被導向首頁"
)
PARSER_VERSION = 1

# SDN.CSV 固定 12 欄、無標頭列（本輪實測確認），順序如下：
_COLS = (
    "ent_num", "sdn_name", "sdn_type", "program", "title", "call_sign",
    "vess_type", "tonnage", "grt", "vess_flag", "vess_owner", "remarks",
)

MIN_ROWS = 15000

_DCA_RE = re.compile(r"Digital Currency Address\s*-\s*([A-Za-z0-9]+)\s+([A-Za-z0-9]+)")


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

    return {
        "count": len(items),
        "with_digital_currency_address": with_dca,
        "items": items,
    }
