#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_report.py

依 REPORT_SPEC.md 產生 <REPO>/REPORT.md。
只用 Python 標準函式庫；只讀取資料，唯一寫入的檔案是 REPORT.md。
任何一段資料缺失都不可讓程式崩潰：一律顯示「—」或「無紀錄」並繼續下一段。

2026-08-31 改版（SPEC-daily-report.md）：
1. 來源清單改為「自動探索」：直接沿用 healthcheck.py 既有的
   `<track>/adapters/*.py` 掃描寫法（本檔不重新發明一套），新增或移除來源
   （新增／搬移 adapter 檔）不必再改這支程式。可探索到的來源數量會隨
   `track-crypto/adapters/`、`track-gov/adapters/` 目錄下實際檔案數量變動，
   本檔不寫死具體數字（避免註解與實際目錄狀態不同步）；執行時的實際數量
   由下方 `ACTIVE = _discover_sources()` 動態計算，並直接顯示於產出的
   `REPORT.md`（「一句話結論」段落）。
2. 修正「悄悄漏列」：
   - 舊版硬編碼的來源清單漏了 fda_clarify／fsc_lawnotice／fsc_penalty／
     ftc_decision／pres_news／tpe_clarify 六個軌二來源，這些來源從未出現在
     報告的來源對照表——本版改為自動探索後不會再發生。
   - 舊版 `logs/detect.log` 解析器只認得「改寫/下架/新增」與「快照不足 2 份，
     略過」兩種行；「解析器版本 X→Y，跳過本次比對」（moi_press 等）與
     「下架截斷，不判定」（fda_clarify／moj_press／tpe_clarify 截斷當天）
     這兩種行格式都無法比對到既有 regex，會被目前的「無法辨識的行：忽略但
     不崩潰」機制悄悄吃掉——本版新增對應 regex，兩者都會明確列出並標註原因。
3. 異常總數改為「與 ALERT.md 採用完全相同的判定函式」：直接呼叫
   healthcheck.py 的 check_timestamps / check_manifest /
   check_truncation_streak / check_source（唯讀，不寫檔），取得的 issues
   清單即為 ALERT.md 產生所用的同一份清單，因此本報告「一句話結論」與
   「異常摘要」的異常數會與當日 ALERT.md 完全一致（同一套邏輯，非另外估算）。
   來源對照表另外顯示 ok/truncated/attempts/parse_failed 供人工判讀，
   這屬於補充資訊，不重複計入異常總數（避免同一件事被算兩次）。
4. 新增欄位：`parse_failed`（v5 空正文守門新增，尚未在任何 manifest 出現過，
   欄位已就緒，屆時會自動顯示，不需再改本檔）、`truncated`、`attempts`。
5. 相容 track-gov 用 `channels` 鍵、track-crypto 用 `sources` 鍵。

2026-09-03 改版（SPEC-notice-and-dr.md）：
  healthcheck.py（commit 641e9d3）新增「parser_version 變更期間跳過體積判定」
  時會印出 NOTICE，但只印在 stdout，實務上沒人看得到（不進 ALERT.md 是刻意
  設計，那是異常檔；也從未出現在 REPORT.md）。本版在 REPORT.md 新增「暫不
  判定／基準重建中」資訊區塊（render_notice_section()），明確標示為非異常：
  不計入 total_anomalies、不寫入 ALERT.md。資料來源是 build_health_issues()
  呼叫 healthcheck.check_source() 時用 contextlib.redirect_stdout 擷取的
  NOTICE 訊息，與〈異常摘要〉同一次函式呼叫，避免另一套邏輯各算各的。

回放測試（不影響正式排程行為）：
  可用環境變數 HEALTHCHECK_NOW（ISO8601 UTC）／HEALTHCHECK_TODAY（YYYY-MM-DD）
  覆寫「現在時刻」／「今天日期」——這兩個變數與 healthcheck.py 共用同一套
  機制（本檔透過 import healthcheck 直接讀 healthcheck.NOW_UTC / TODAY，
  確保回放時兩邊日期判斷完全同步，不會出現「report 用今天、healthcheck 用
  昨天」的錯位）。正式環境（cron）不會設定這兩個變數，行為與改動前一致。
"""

import os
import sys
import json
import glob
import re
import importlib.util
import statistics
import io
import contextlib
from datetime import datetime, date, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

UTC = timezone.utc
TPE = timezone(timedelta(hours=8))

DASH = "—"


def _load_healthcheck_module():
    """以路徑載入 healthcheck.py（不透過 sys.path，避免與其他同名模組衝突）。
    只讀取其模組層級常數與純函式（check_* 系列都只寫入呼叫端傳入的 list，
    不寫檔；main() 才會寫 ALERT.md，本檔完全不呼叫 main()）。"""
    path = os.path.join(SCRIPT_DIR, "healthcheck.py")
    spec = importlib.util.spec_from_file_location("healthcheck", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    healthcheck = _load_healthcheck_module()
except Exception:
    healthcheck = None


def _discover_sources():
    """回傳 (active, name_hint)：
    active：[(track, key), ...]，直接沿用 healthcheck.ACTIVE（若載入失敗則退回
            健檢模組同一套 _adapter_keys 邏輯的最小複製版，仍然是「掃描
            adapters 目錄」而非另一份寫死清單）。
    """
    if healthcheck is not None and getattr(healthcheck, "ACTIVE", None):
        return list(healthcheck.ACTIVE)

    # 降級路徑：healthcheck.py 載入失敗時，仍用同一種「掃描 adapters」寫法，
    # 不退回寫死清單，避免重蹈舊版「硬編碼漏列」的覆轍。
    def adapter_keys(track):
        adir = os.path.join(REPO, track, "adapters")
        if not os.path.isdir(adir):
            return []
        out = []
        for fn in sorted(os.listdir(adir)):
            if fn.endswith(".py") and not fn.startswith("_"):
                try:
                    txt = open(os.path.join(adir, fn), encoding="utf-8").read()
                except Exception:
                    continue
                m = re.search(r'^KEY\s*=\s*["\'](.+?)["\']', txt, re.M)
                if m:
                    out.append(m.group(1))
        return out

    active = [("track-crypto", k) for k in adapter_keys("track-crypto")]
    active += [("track-gov", k) for k in adapter_keys("track-gov")]
    return active


ACTIVE = _discover_sources()
TRACK_KEY_FIELD = {"track-crypto": "sources", "track-gov": "channels"}
TRACK_LABEL = {"track-crypto": "軌一", "track-gov": "軌二"}

NAME_MAP = {
    # 軌二（track-gov）
    "fsc_clarification": "金管會即時新聞澄清",
    "fsc_lawnotice": "金管會法令函釋",
    "fsc_penalty": "金管會裁罰案件",
    "moe_clarify": "教育部即時新聞澄清",
    "moj_press": "法務部新聞發布",
    "cbc_press": "中央銀行新聞稿",
    "mof_press": "財政部本部新聞",
    "mol_press": "勞動部新聞稿",
    "moda_press": "數位發展部新聞發布",
    "moi_press": "內政部新聞稿",
    "ey_press": "行政院本院新聞",
    "mohw_press": "衛生福利部焦點新聞",
    "moe_press": "教育部即時新聞",
    "moea_press": "經濟部本部新聞",
    "fda_clarify": "食藥署即時新聞澄清",
    "ftc_decision": "公平會決議案件",
    "pres_news": "總統府新聞稿",
    "tpe_clarify": "台北市政府即時新聞澄清",
    # 軌一（track-crypto）
    "x402_bazaar": "x402 協議掛牌",
    "cex_symbols": "交易所交易對",
    "vast_gpu": "vast.ai GPU 報價",
    "agent_virtuals": "Virtuals Protocol agent 清單",
    "airdrop_claim_pages": "空投領取頁面",
    "audit_registry_certik": "CertiK 稽核登錄",
    "cex_announcements": "交易所公告",
    "cex_currency_status": "交易所幣別狀態",
    "cex_earn_apr": "交易所理財年化利率",
    "cex_symbols_ext": "交易所交易對（擴充）",
    "cex_withdrawal_limits": "交易所提領限額",
    "crypto_project_liveness": "加密專案存活狀態",
    "dao_proposal_snapshot": "DAO 提案快照",
    "defi_yield_rates": "DeFi 收益率",
    "eth_validator_queue": "以太坊驗證者佇列",
    "hf_trending_models": "HuggingFace 熱門模型",
    "mcp_smithery": "MCP Smithery 註冊表",
    "ofac_sanctions_crypto": "OFAC 加密制裁清單",
    "openrouter_models": "OpenRouter 模型清單",
    "openrouter_providers": "OpenRouter 供應商清單",
    "oracle_feed_directory": "預言機餵價目錄",
    "payment_protocol_repos": "支付協議程式庫",
    "project_tokenomics_docs": "專案代幣經濟文件",
    "x402_index_thirdparty": "x402 第三方索引",
}


_DESC_CACHE = {}


def adapter_desc(track, key):
    """來源中文名以 adapter 自己的 DESC 常數為準（單一事實來源），
    取第一個全形括號或逗號之前的短名；讀不到就回 None，由 NAME_MAP 兜底。"""
    ck = (track, key)
    if ck in _DESC_CACHE:
        return _DESC_CACHE[ck]
    name = None
    try:
        path = os.path.join(REPO, track, "adapters", key + ".py")
        with open(path, "r", encoding="utf-8") as f:
            m = re.search(r'^DESC\s*=\s*["\'](.+?)["\']', f.read(), re.M)
        if m:
            name = re.split(r'[（(,，]', m.group(1))[0].strip() or None
    except Exception:
        name = None
    _DESC_CACHE[ck] = name
    return name


def safe(fn, default=None):
    """執行 fn()，任何例外都吞掉並回傳 default。"""
    try:
        return fn()
    except Exception:
        return default


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_json_gz(path):
    import gzip
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def fmt_num(n):
    if n is None:
        return DASH
    try:
        return f"{int(n):,}"
    except Exception:
        return DASH


def fmt_bytes(n):
    if n is None:
        return DASH
    try:
        return f"{int(n):,} B"
    except Exception:
        return DASH


def fmt_bytes_human(n):
    """人類可讀單位（KB/MB/GB），用於推算類數字（例如 1 年/5 年累積量）。"""
    if n is None:
        return DASH
    try:
        n = float(n)
    except Exception:
        return DASH
    sign = "-" if n < 0 else ""
    n = abs(n)
    for unit, factor in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if n >= factor:
            return f"{sign}{n / factor:.1f} {unit}"
    return f"{sign}{n:.0f} B"


def fmt_secs(n):
    if n is None:
        return DASH
    try:
        return f"{float(n):.1f}s"
    except Exception:
        return DASH


def fmt_bool(v):
    if v is None:
        return DASH
    return "是" if v else "否"


def pct_change(today, yesterday):
    if today is None or yesterday is None:
        return DASH
    try:
        today = float(today)
        yesterday = float(yesterday)
    except Exception:
        return DASH
    if yesterday == 0:
        return DASH
    change = (today - yesterday) / yesterday * 100.0
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.1f}%"


def diff_str(today, yesterday):
    if today is None or yesterday is None:
        return DASH
    try:
        d = int(today) - int(yesterday)
    except Exception:
        return DASH
    sign = "+" if d >= 0 else ""
    return f"{sign}{d}"


def latest_snapshot_for_date(source_dir, date_str):
    """
    某個來源目錄下，找出「當日最後一份」快照檔。
    檔名可能是 YYYY-MM-DD.json.gz 或 YYYY-MM-DDTHHMMSS.json.gz。
    回傳 (data_path, stats_path) 或 (None, None)。
    """
    if not os.path.isdir(source_dir):
        return None, None
    candidates = []
    for fn in os.listdir(source_dir):
        if fn.startswith(date_str) and fn.endswith(".json.gz"):
            candidates.append(fn)
    if not candidates:
        return None, None
    candidates.sort()
    chosen = candidates[-1]
    data_path = os.path.join(source_dir, chosen)
    # stats 檔名慣例：<date_part>.stats.json，date_part 去掉 .json.gz
    stem = chosen[: -len(".json.gz")]
    stats_path = os.path.join(source_dir, stem + ".stats.json")
    if not os.path.isfile(stats_path):
        # 有些情境 stats 檔名固定用純日期
        alt = os.path.join(source_dir, date_str + ".stats.json")
        stats_path = alt if os.path.isfile(alt) else None
    return data_path, (stats_path if stats_path and os.path.isfile(stats_path) else None)


def load_manifest(track_dir, date_str):
    path = os.path.join(track_dir, "data", "_manifest", f"{date_str}.json")
    if not os.path.isfile(path):
        return None
    return safe(lambda: read_json(path))


def manifest_fetched_at_date(manifest):
    """從 manifest 的 fetched_at 欄位（可靠的 UTC 時間戳）取出日期字串（YYYY-MM-DD）。"""
    if not isinstance(manifest, dict):
        return None
    fa = manifest.get("fetched_at")
    if not isinstance(fa, str):
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", fa)
    return m.group(1) if m else None


def manifest_source_count(manifest, key_field):
    """回傳 manifest 內 sources/channels 字典的 key 數量。"""
    if not isinstance(manifest, dict):
        return None
    container = manifest.get(key_field)
    if not isinstance(container, dict):
        return None
    return len(container)


def manifest_runs(manifest):
    """回傳 manifest 的 runs 陣列（記錄每次執行涵蓋哪些來源），沒有則回傳 None。"""
    if not isinstance(manifest, dict):
        return None
    r = manifest.get("runs")
    return r if isinstance(r, list) else None


def all_manifest_dates(track_dir):
    pattern = os.path.join(track_dir, "data", "_manifest", "*.json")
    dates = []
    for p in glob.glob(pattern):
        fn = os.path.basename(p)
        m = re.match(r"(\d{4}-\d{2}-\d{2})\.json$", fn)
        if m:
            dates.append(m.group(1))
    return sorted(dates)


def build_source_table(today_str, yesterday_str):
    """
    回傳 (rows, anomaly_count)。
    rows 涵蓋 `ACTIVE`（自動探索得到的全部來源，數量隨 adapters/ 目錄實際檔案數變動，不寫死），逐一標註：
    今日筆數／昨日筆數／增減／今日體積／體積增減%／耗時／嘗試次數／截斷／
    解析失敗（parse_failed）／備註（缺 manifest 紀錄、抓取失敗原因等，
    確保「截斷／解析器改版/抓取失敗」都明確列出、不靜默略過）。

    anomaly_count 為本表自行統計的「ok=false 或 truncated=true 或
    parse_failed=true」筆數，僅供本節內部參考；報告的官方異常總數改用
    build_health_issues() 取得的 healthcheck 同源清單，兩者用途不同見
    main() 內說明，避免同一件事被算兩次。
    """
    rows = []
    anomaly_count = 0

    track_dirs = {t: os.path.join(REPO, t) for t in TRACK_KEY_FIELD}
    manifest_today = {t: load_manifest(d, today_str) for t, d in track_dirs.items()}
    manifest_yday = {t: load_manifest(d, yesterday_str) for t, d in track_dirs.items()}

    for track, key in ACTIVE:
        key_field = TRACK_KEY_FIELD.get(track, "sources")
        track_dir = track_dirs.get(track, os.path.join(REPO, track))
        cn = adapter_desc(track, key) or NAME_MAP.get(key, key)

        m_today_container = (manifest_today.get(track) or {}).get(key_field) if manifest_today.get(track) else None
        m_yday_container = (manifest_yday.get(track) or {}).get(key_field) if manifest_yday.get(track) else None
        m_today = m_today_container.get(key) if isinstance(m_today_container, dict) else None
        m_yday = m_yday_container.get(key) if isinstance(m_yday_container, dict) else None

        today_bytes = m_today.get("bytes") if m_today else None
        secs = m_today.get("secs") if m_today else None
        ok = m_today.get("ok") if m_today else None
        attempts = m_today.get("attempts") if m_today else None
        truncated = m_today.get("truncated") if m_today else None
        parse_failed = m_today.get("parse_failed") if m_today else None

        yday_bytes = m_yday.get("bytes") if m_yday else None

        # 筆數：軌二直接讀 manifest 的 n（stats.total 是 null，不可用）；
        # 軌一目前 manifest 沒有 n 欄位，改讀當日快照的 stats.json 的 total。
        if key_field == "channels":
            today_n = m_today.get("n") if m_today else None
            yday_n = m_yday.get("n") if m_yday else None
        else:
            today_n = None
            source_dir = os.path.join(track_dir, "data", key)
            _, stats_path = latest_snapshot_for_date(source_dir, today_str)
            if stats_path:
                stats = safe(lambda p=stats_path: read_json(p))
                if stats:
                    today_n = stats.get("total")
            yday_n = None
            _, yday_stats_path = latest_snapshot_for_date(source_dir, yesterday_str)
            if yday_stats_path:
                yday_stats = safe(lambda p=yday_stats_path: read_json(p))
                if yday_stats:
                    yday_n = yday_stats.get("total")

        notes = []
        if m_today is None:
            container_exists = isinstance(m_today_container, dict)
            if container_exists:
                notes.append("今日 manifest 未列出此來源（可能新增 adapter 尚未跑過，或本次執行未涵蓋）")
            else:
                notes.append(f"今日（{today_str}）manifest 不存在或無法解析")
        else:
            if ok is False:
                notes.append(f"抓取失敗：{m_today.get('error', '(manifest 未附錯誤訊息)')}")
            if truncated:
                items_fetched = m_today.get("items_fetched")
                extra = f"，已取得 {fmt_num(items_fetched)} 筆" if items_fetched is not None else ""
                notes.append(f"今日截斷（truncated=true{extra}，未跑滿目標筆數）")
            if parse_failed:
                notes.append("解析失敗（parse_failed=true，空正文守門攔截）")

        if ok is False or truncated or parse_failed:
            anomaly_count += 1

        rows.append({
            "軌": TRACK_LABEL.get(track, track),
            "來源": key,
            "中文名": cn,
            "今日筆數": fmt_num(today_n),
            "昨日筆數": fmt_num(yday_n),
            "增減": diff_str(today_n, yday_n),
            "今日體積": fmt_bytes(today_bytes),
            "體積增減%": pct_change(today_bytes, yday_bytes),
            "耗時": fmt_secs(secs),
            "嘗試": fmt_num(attempts) if attempts is not None else DASH,
            "截斷": fmt_bool(truncated),
            "解析失敗": fmt_bool(parse_failed),
            "備註": "；".join(notes) if notes else "",
        })

    return rows, anomaly_count


def render_source_table(rows):
    header = ("| 軌 | 來源 | 中文名 | 今日筆數 | 昨日筆數 | 增減 | 今日體積 | 體積增減% | "
              "耗時 | 嘗試 | 截斷 | 解析失敗 | 備註 |")
    sep = "|---|---|---|---|---|---|---|---|---|---|---|---|---|"
    lines = [header, sep]
    for r in rows:
        lines.append(
            f"| {r['軌']} | {r['來源']} | {r['中文名']} | {r['今日筆數']} | "
            f"{r['昨日筆數']} | {r['增減']} | {r['今日體積']} | {r['體積增減%']} | {r['耗時']} | "
            f"{r['嘗試']} | {r['截斷']} | {r['解析失敗']} | {r['備註']} |"
        )
    return "\n".join(lines)


def parse_detect_log_last_round(path):
    """
    讀 logs/detect.log 最後一輪（以最後一行 SUMMARY 為結尾，往上找到上一個 SUMMARY 之後的區塊；
    若只有一個 SUMMARY，就從檔頭算起）。
    回傳 (lines, summary_dict) 或 (None, None)。
    """
    if not os.path.isfile(path):
        return None, None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        all_lines = [l.rstrip("\n") for l in f if l.strip()]
    if not all_lines:
        return None, None
    summary_idxs = [i for i, l in enumerate(all_lines) if l.startswith("SUMMARY")]
    if not summary_idxs:
        return all_lines, None
    last_summary_idx = summary_idxs[-1]
    if len(summary_idxs) >= 2:
        start = summary_idxs[-2] + 1
    else:
        start = 0
    block = all_lines[start:last_summary_idx + 1]
    summary_line = all_lines[last_summary_idx]
    summary = {}
    m = re.search(r"changed=(\d+)", summary_line)
    if m:
        summary["changed"] = int(m.group(1))
    m = re.search(r"removed=(\d+)", summary_line)
    if m:
        summary["removed"] = int(m.group(1))
    return block, summary


# 一般改寫/下架/新增行；「下架」欄位可能是數字，也可能因本日快照截斷而是
# 「截斷，不判定」（detect_changes.py 的 skip_removed 分支）——舊版 regex
# 只認數字，截斷當天的這行會整行比對失敗、被「無法辨識」機制悄悄吃掉
# （2026-08-31 實證：fda_clarify／moj_press／tpe_clarify 皆屬此況），
# 這裡改成兩種都能比對到。
CHANGE_LINE_RE = re.compile(
    r"^(?P<key>[^:]+): (?P<d1>\d{4}-\d{2}-\d{2})→(?P<d2>\d{4}-\d{2}-\d{2}) "
    r"改寫(?P<changed>\d+) 下架(?P<removed>截斷，不判定|\d+) 新增(?P<added>\d+)"
    r"(?:（另有 (?P<rolled>\d+) 筆滾動移出視窗，不計為下架）)?"
    r"(?P<trunc_marker>（⚠️ 本日快照截斷，下架判定已跳過）)?$"
)
SKIP_LINE_RE = re.compile(r"^(?P<key>[^:]+): 快照不足 2 份，略過$")
# 解析器改版時 detect_changes.py 會整批跳過比對（避免假警報），舊版沒有對應
# regex，這種行也會被「無法辨識」機制悄悄吃掉（2026-08-31 實證：moi_press／
# ey_press／fsc_clarification／moda_press 皆曾出現）。
PARSER_SKIP_LINE_RE = re.compile(
    r"^(?P<key>[^:]+): 解析器版本 (?P<v1>\S+)→(?P<v2>\S+)，跳過本次比對（非內容改寫）$"
)
SUMMARY_LINE_RE = re.compile(r"^SUMMARY changed=(?P<changed>\d+) removed=(?P<removed>\d+)$")


def parse_change_detection_rows(block):
    """把 detect.log 一輪的行解析成結構化資料：
    (rows, skipped_keys, parser_skipped, summary_dict)。"""
    rows = []
    skipped = []
    parser_skipped = []
    summary = None
    for line in block:
        m = CHANGE_LINE_RE.match(line)
        if m:
            truncated_line = m.group("removed") == "截斷，不判定"
            rows.append({
                "來源": m.group("key"),
                "區間": f"{m.group('d1')}→{m.group('d2')}",
                "改寫": int(m.group("changed")),
                "下架": "N/A（截斷）" if truncated_line else int(m.group("removed")),
                "下架數值": 0 if truncated_line else int(m.group("removed")),
                "新增": int(m.group("added")),
                "滾動移出": int(m.group("rolled")) if m.group("rolled") else 0,
                "截斷": truncated_line,
            })
            continue
        m = SKIP_LINE_RE.match(line)
        if m:
            skipped.append(m.group("key"))
            continue
        m = PARSER_SKIP_LINE_RE.match(line)
        if m:
            parser_skipped.append((m.group("key"), m.group("v1"), m.group("v2")))
            continue
        m = SUMMARY_LINE_RE.match(line)
        if m:
            summary = {"changed": int(m.group("changed")), "removed": int(m.group("removed"))}
            continue
        # 無法辨識的行：忽略但不崩潰
    return rows, skipped, parser_skipped, summary


def render_change_table(rows):
    header = "| 來源 | 區間 | 改寫 | 下架 | 新增 | 滾動移出 |"
    sep = "|---|---|---|---|---|---|"
    lines = [header, sep]
    total_changed = total_removed = total_added = total_rolled = 0
    for r in rows:
        lines.append(
            f"| {r['來源']} | {r['區間']} | {r['改寫']} | {r['下架']} | {r['新增']} | {r['滾動移出']} |"
        )
        total_changed += r["改寫"]
        total_removed += r["下架數值"]
        total_added += r["新增"]
        total_rolled += r["滾動移出"]
    lines.append(f"| **總計** |  | {total_changed} | {total_removed} | {total_added} | {total_rolled} |")
    return "\n".join(lines)


def build_change_detection_section():
    lines = []
    detect_log = os.path.join(REPO, "logs", "detect.log")   # 實際位置在 repo 根的 logs/，不在 track-gov/logs/
    block, _unused_summary = safe(lambda: parse_detect_log_last_round(detect_log), (None, None))
    if block:
        rows, skipped, parser_skipped, summary = safe(
            lambda: parse_change_detection_rows(block), ([], [], [], None))
        if rows:
            lines.append("最近一輪變動偵測：")
            lines.append("")
            lines.append(render_change_table(rows))
            truncated_keys = [r["來源"] for r in rows if r.get("截斷")]
            if truncated_keys:
                lines.append("")
                lines.append(
                    "⚠️ 以下來源今日快照截斷（truncated=true），下架判定已跳過、"
                    "非「零下架」：" + "、".join(truncated_keys))
        if skipped:
            lines.append("")
            lines.append("略過（快照不足 2 份）：" + "、".join(skipped))
        if parser_skipped:
            lines.append("")
            lines.append(
                "因解析器改版跳過本次比對（非內容改寫，非異常）：" +
                "、".join(f"{k}（v{v1}→v{v2}）" for k, v1, v2 in parser_skipped))
        if summary:
            lines.append("")
            lines.append(f"本輪彙總：changed={summary.get('changed', DASH)}，removed={summary.get('removed', DASH)}。")
        if not rows and not skipped and not parser_skipped and not summary:
            lines.append("`logs/detect.log` 有內容但無法解析任何一行，原始內容如下：")
            lines.append("")
            lines.append("```")
            lines.extend(block)
            lines.append("```")
    else:
        lines.append("無 `logs/detect.log` 紀錄或無法解析。")

    changes_dir = os.path.join(REPO, "changes")
    if os.path.isdir(changes_dir):
        entries = safe(lambda: sorted(os.listdir(changes_dir)), [])
        if entries:
            lines.append("")
            lines.append(f"`changes/` 目錄下有 {len(entries)} 個來源目錄記錄改寫內容：")
            for e in entries:
                lines.append(f"- {e}")
        else:
            lines.append("")
            lines.append("`changes/` 目錄存在但目前無內容。")
    else:
        lines.append("")
        lines.append("`changes/` 目錄目前不存在（尚無偵測到改寫）。")

    changes_md = os.path.join(REPO, "CHANGES.md")
    if os.path.isfile(changes_md):
        lines.append("")
        lines.append("`CHANGES.md` 存在，內容請參閱該檔案。")
    else:
        lines.append("")
        lines.append("`CHANGES.md` 目前不存在。")

    return "\n".join(lines)


def build_cex_events_section(today_str):
    path = os.path.join(REPO, "track-crypto", "data", "cex_events", "events.jsonl")
    if not os.path.isfile(path):
        return "無 `cex_events.jsonl` 紀錄。", 0

    events_today = []

    def load():
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("date") == today_str:
                    events_today.append(obj)

    safe(load)

    if not events_today:
        return f"今日（{today_str}）無交易所事件。", 0

    grouped = {}
    for ev in events_today:
        key = (ev.get("exchange", DASH), ev.get("event", DASH))
        grouped.setdefault(key, []).append(ev)

    lines = [f"今日（{today_str}）共 {len(events_today)} 筆事件，依交易所與事件類型分組："]
    lines.append("")
    for (exch, etype), evs in sorted(grouped.items()):
        lines.append(f"- {exch} / {etype}：{len(evs)} 筆")
        for sample in evs[:5]:
            sym = sample.get("symbol", DASH)
            frm = sample.get("from", DASH)
            to = sample.get("to", DASH)
            lines.append(f"  - {sym}：{frm} → {to}")

    return "\n".join(lines), len(events_today)


def parse_cron_log(path, today_str):
    """
    回傳 (今日是否有紀錄, 今日成功/總數, 過去 7 日的成功率清單)。
    格式如：
      OK   cex_symbols       404,938B 13.4s
      --- 3/3 成功 ---
    """
    result = {
        "today_found": False,
        "today_summary": None,
        "history": [],
    }
    if not os.path.isfile(path):
        return result

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        all_lines = [l.rstrip("\n") for l in f]

    summary_pattern = re.compile(r"---\s*(\d+)/(\d+)\s*成功\s*---")
    summaries = []
    for l in all_lines:
        m = summary_pattern.search(l)
        if m:
            summaries.append((int(m.group(1)), int(m.group(2))))

    if summaries:
        result["today_found"] = True
        result["today_summary"] = summaries[-1]
        result["history"] = summaries[-7:]

    return result


def build_cron_section(today_str):
    """
    今日是否執行：改用 manifest 的 fetched_at 欄位判斷（可靠的 UTC 時間戳），
    不再用 cron.log 最後一個摘要列判斷（cron.log 只 append、無日期欄位，不可靠）。
    cron.log 僅用來取「耗時」與歷史成功率比較，以及與 manifest 來源數互相對照。

    本節統計的「疑似問題」數字（回傳值第二項）僅供本節內部參考，
    不計入報告的官方異常總數（見 main() 說明），避免與 healthcheck 判定重複計數。
    """
    lines = []
    anomalies = 0
    for track, label, key_field, expected_sources in [
        ("track-crypto", "軌一（track-crypto）", "sources",
         [k for t, k in ACTIVE if t == "track-crypto"]),
        ("track-gov", "軌二（track-gov）", "channels",
         [k for t, k in ACTIVE if t == "track-gov"]),
    ]:
        track_dir = os.path.join(REPO, track)
        log_path = os.path.join(track_dir, "logs", "cron.log")
        info = safe(lambda lp=log_path: parse_cron_log(lp, None), {"today_found": False, "today_summary": None, "history": []})
        lines.append(f"**{label}**（自動探索到 {len(expected_sources)} 個來源）：")

        manifest_today = safe(lambda td=track_dir: load_manifest(td, today_str))
        fetched_date = manifest_fetched_at_date(manifest_today)
        channel_count = manifest_source_count(manifest_today, key_field)
        runs = manifest_runs(manifest_today)

        if manifest_today is not None and fetched_date == today_str:
            count_str = channel_count if channel_count is not None else DASH
            lines.append(f"- 今日已執行（依 manifest `fetched_at`={fetched_date} 判斷），manifest 記錄 {count_str} 個來源。")
            if channel_count is not None and channel_count < len(expected_sources):
                lines.append(
                    f"- ⚠️ manifest 來源數（{channel_count}）少於目前已部署的 adapter 數（{len(expected_sources)}），"
                    f"可能有新增來源尚未執行過，或本次執行未涵蓋全部來源。")
            if runs:
                lines.append(f"- manifest 由 {len(runs)} 次執行合併寫入（`runs` 陣列）。")
        elif manifest_today is not None:
            lines.append(
                f"- manifest 存在但 `fetched_at` 日期（{fetched_date or DASH}）與今日（{today_str}）不符，"
                f"可能為殘留檔案，視為今日未確認執行。"
            )
            anomalies += 1
        else:
            lines.append(f"- 今日（{today_str}）尚無 manifest 紀錄，視為未執行。")
            anomalies += 1

        if not os.path.isfile(log_path):
            lines.append("- 無 `cron.log` 紀錄（僅供耗時／歷史比較參考，不影響上述今日執行判斷）。")
            continue

        if info["today_summary"]:
            ok_n, total_n = info["today_summary"]
            lines.append(f"- cron.log 最近一次摘要（僅供耗時／歷史參考）：{ok_n}/{total_n} 成功")
            if channel_count is not None and channel_count != total_n:
                diff = channel_count - total_n
                if diff > 0:
                    lines.append(
                        f"- manifest 來源數（{channel_count}）多於 cron.log 摘要（{total_n}），"
                        f"其中 {diff} 個為另次執行補齊。"
                    )
                else:
                    lines.append(
                        f"- manifest 來源數（{channel_count}）少於 cron.log 摘要（{total_n}），"
                        f"可能有來源尚未合併寫入 manifest。"
                    )
            if ok_n < total_n:
                anomalies += 1
            if info["history"]:
                hist_str = "、".join(f"{a}/{b}" for a, b in info["history"])
                lines.append(f"- 近 {len(info['history'])} 次執行成功率（cron.log 歷史）：{hist_str}")
        else:
            lines.append("- cron.log 找不到執行摘要（`--- N/M 成功 ---`），僅影響耗時／歷史資訊。")

    return "\n".join(lines), anomalies


def build_timestamp_section():
    ts_dir = os.path.join(REPO, "timestamps")
    if not os.path.isdir(ts_dir):
        return "`timestamps/` 目錄不存在。", 0

    sums_files = sorted(glob.glob(os.path.join(ts_dir, "SHA256SUMS-*.txt")))
    if not sums_files:
        return "`timestamps/` 目錄下無 `SHA256SUMS-*.txt` 檔案。", 0

    lines = []
    missing = 0
    for f in sums_files:
        fn = os.path.basename(f)
        ots = f + ".ots"
        has_ots = os.path.isfile(ots)
        if not has_ots:
            missing += 1
        lines.append(f"- {fn}：{'有' if has_ots else '**無**'} 對應 `.ots`")

    return "\n".join(lines), missing


def build_cumulative_stats():
    lines = []
    crypto_dir = os.path.join(REPO, "track-crypto")
    gov_dir = os.path.join(REPO, "track-gov")

    crypto_dates = safe(lambda: all_manifest_dates(crypto_dir), [])
    gov_dates = safe(lambda: all_manifest_dates(gov_dir), [])
    all_dates = sorted(set(crypto_dates) | set(gov_dates))

    if not all_dates:
        return "無足夠 manifest 紀錄以計算累積統計。"

    start_date = all_dates[0]
    end_date = all_dates[-1]
    try:
        d1 = datetime.strptime(start_date, "%Y-%m-%d")
        d2 = datetime.strptime(end_date, "%Y-%m-%d")
        total_days = (d2 - d1).days + 1
    except Exception:
        total_days = len(all_dates)

    lines.append(f"- 資料起訖日期：{start_date} ～ {end_date}（共 {total_days} 天，實際有紀錄 {len(all_dates)} 天）")

    def sum_bytes_over_dates(track_dir, dates, key_field):
        total = 0
        found = False
        for d in dates:
            m = load_manifest(track_dir, d)
            if not m:
                continue
            container = m.get(key_field)
            if not isinstance(container, dict):
                continue
            for v in container.values():
                b = v.get("bytes")
                if isinstance(b, (int, float)):
                    total += b
                    found = True
        return total if found else None

    crypto_total_bytes = safe(lambda: sum_bytes_over_dates(crypto_dir, crypto_dates, "sources"))
    gov_total_bytes = safe(lambda: sum_bytes_over_dates(gov_dir, gov_dates, "channels"))

    def project(total_bytes, days, years):
        if total_bytes is None or not days:
            return DASH
        try:
            daily_rate = total_bytes / days
            return fmt_bytes_human(daily_rate * 365 * years)
        except Exception:
            return DASH

    lines.append(f"- track-crypto 累積體積：{fmt_bytes(crypto_total_bytes)}（{len(crypto_dates)} 天有 manifest）")
    if crypto_dates:
        lines.append(
            f"  - 依現速率推算：1 年約 {project(crypto_total_bytes, len(crypto_dates), 1)}，"
            f"5 年約 {project(crypto_total_bytes, len(crypto_dates), 5)}"
        )

    lines.append(f"- track-gov 累積體積：{fmt_bytes(gov_total_bytes)}（{len(gov_dates)} 天有 manifest）")
    if gov_dates:
        lines.append(
            f"  - 依現速率推算：1 年約 {project(gov_total_bytes, len(gov_dates), 1)}，"
            f"5 年約 {project(gov_total_bytes, len(gov_dates), 5)}"
        )

    return "\n".join(lines)


def build_alert_section():
    alert_files = ["ALERT.md", "ALERT-DETECT.md", "ALERT-HEALTH.md", "ALERT-DELIST.md", "ALERT-BACKUP.md", "ALERT-CEXGATE.md"]
    lines = []
    any_alert = False
    for fn in alert_files:
        path = os.path.join(REPO, fn)
        if os.path.isfile(path):
            any_alert = True
            lines.append(f"**{fn}**（存在）：")
            content = safe(lambda p=path: open(p, "r", encoding="utf-8", errors="replace").read().splitlines(), [])
            for l in content[:10]:
                lines.append(f"> {l}")
            lines.append("")
        else:
            lines.append(f"- {fn}：不存在")
    return "\n".join(lines), any_alert


def build_health_issues():
    """呼叫 healthcheck.py 產生 ALERT.md 所用的**同一套**唯讀判定函式，
    取得 (issues, pending, notices)。這是本報告「官方異常總數」的唯一依據，
    確保與 ALERT.md 逐項一致（同一套邏輯，同一份程式碼路徑）。
    healthcheck.py 載入失敗時回傳 (None, None, None)，呼叫端要能處理。

    2026-09-03 新增 notices（SPEC-notice-and-dr.md）：check_source() 對
    parser_version 於比較視窗內改變過的來源，會印出 NOTICE 訊息並直接 return
    （不寫入 issues／pending，也不寫入 ALERT.md，見 healthcheck.py 該節註解）。
    這裡不重新判斷「是否該跳過」——那個決定完全由 healthcheck.check_source()
    做出；本函式只是在同一次呼叫裡用 contextlib.redirect_stdout 擷取它印出的
    NOTICE 訊息，交給 _parse_notice_lines() 解析成結構化資料，避免另外用一套
    邏輯自行重算 parser_version 是否改變（本專案已因兩邊算法不同出過事，
    見 docs/healthcheck-parserver-report.md 第 10 節）。"""
    if healthcheck is None:
        return None, None, None
    issues = []
    pending = []
    notices = []
    try:
        healthcheck.check_timestamps(issues)
        for track in ("track-crypto", "track-gov"):
            healthcheck.check_manifest(track, issues, pending)
            healthcheck.check_truncation_streak(track, issues)
        notice_buf = io.StringIO()
        with contextlib.redirect_stdout(notice_buf):
            for track, key in healthcheck.ACTIVE:
                healthcheck.check_source(track, key, issues, pending)
        notices = _parse_notice_lines(notice_buf.getvalue())
    except Exception:
        return None, None, None
    return issues, pending, notices


# NOTICE 行格式固定由 healthcheck.py 的 check_source() 印出（見該檔案「體積檢查：
# parser_version 改版時跳過判定」一節），本檔不重新產生文字，只解析，避免兩邊
# 各算各的（SPEC-notice-and-dr.md 硬性要求，本專案已因此出過事）。
_NOTICE_RE = re.compile(
    r"^NOTICE (?P<label>\S+): parser_version (?P<old>\S+)→(?P<new>\S+)，"
    r"體積基準重建中，暫不判定（第 (?P<day>\d+)/(?P<of>\d+) 天"
)


def _parse_notice_lines(text):
    """把 check_source() 印出的 NOTICE 行解析成結構化資料
    [{"label","old","new","day","of","raw"}, ...]，供 render_notice_section()
    使用。只做文字解析，不重新判斷是否該跳過（判斷本身由 healthcheck.py 做出，
    見 build_health_issues() 說明）。格式若未來變動導致無法解析，仍保留完整
    原始整行文字（raw），不靜默丟棄資訊。"""
    out = []
    for line in text.splitlines():
        if not line.startswith("NOTICE "):
            continue
        m = _NOTICE_RE.match(line)
        if m:
            out.append({"label": m.group("label"), "old": m.group("old"),
                        "new": m.group("new"), "day": m.group("day"), "of": m.group("of"),
                        "raw": line})
        else:
            m2 = re.match(r"^NOTICE (\S+):", line)
            out.append({"label": m2.group(1) if m2 else "?", "old": None,
                        "new": None, "day": None, "of": None, "raw": line})
    return out


def render_notice_section(notices):
    """SPEC-notice-and-dr.md 任務一：把「暫不判定／基準重建中」的 NOTICE 來源
    列成 REPORT.md 的資訊區塊。明確非異常：呼叫端（main()）不得把這裡的筆數
    計入 total_anomalies；本函式本身也絕對不寫入 ALERT.md——本檔從未呼叫
    healthcheck.main()，全檔唯一的寫入動作是檔尾寫 REPORT.md（見檔頭說明）。"""
    intro = (
        "以下來源的 `parser_version` 在體積比較視窗（最近 7 天）內發生變更，"
        "`healthcheck.py` 的 `check_source()`（與 `ALERT.md` 同一套判定函式，"
        "見上方〈異常摘要〉呼叫的 `build_health_issues()`）依既有原則（比照 "
        "`detect_changes.py`）暫時跳過本次體積判定，等視窗內全部天數都變成新"
        "版本後自動恢復判定，不需人工介入、不留白名單。**這是資訊性狀態，"
        "不是異常**：不計入本報告與 `ALERT.md` 的異常總數，也不會寫入 "
        "`ALERT.md`。下表直接解析自 `check_source()` 本次執行時印出的 NOTICE "
        "訊息，與〈異常摘要〉同一次呼叫、非本檔另行計算。"
    )
    lines = [intro, ""]
    if notices is None:
        lines.append("（healthcheck.py 無法載入，本次無法取得此清單。）")
        return "\n".join(lines)
    if not notices:
        lines.append("目前沒有來源處於此狀態。")
        return "\n".join(lines)
    lines.append("| 來源 | parser_version 變化 | 進度（第幾天／共幾天） |")
    lines.append("|---|---|---|")
    for n in notices:
        if n["day"] is not None:
            change = f"{n['old']} → {n['new']}"
            progress = f"第 {n['day']}／{n['of']} 天"
        else:
            change = "（格式未預期，見原文）"
            progress = "—"
        lines.append(f"| `{n['label']}` | {change} | {progress} |")
        if n["day"] is None:
            lines.append(f"| | | 原文：{n['raw']} |")
    return "\n".join(lines)


def render_health_issues_table(issues):
    header = "| 來源 | 問題（與 healthcheck.py / ALERT.md 同一套判定） |"
    sep = "|---|---|"
    lines = [header, sep]
    for a, b in issues:
        lines.append(f"| `{a}` | {b} |")
    return "\n".join(lines)


def main():
    if healthcheck is not None:
        now_utc = healthcheck.NOW_UTC
        today_str = healthcheck.TODAY
    else:
        now_utc = datetime.now(UTC)
        today_str = now_utc.strftime("%Y-%m-%d")
    now_tpe = now_utc.astimezone(TPE)
    yesterday_str = (date.fromisoformat(today_str) - timedelta(days=1)).strftime("%Y-%m-%d")

    sections = []

    rows, source_anomalies = safe(lambda: build_source_table(today_str, yesterday_str), ([], 0))
    cron_section, cron_anomalies = safe(lambda: build_cron_section(today_str), ("無法讀取 cron 紀錄。", 0))
    ts_section, ts_missing = safe(build_timestamp_section, ("無法讀取時間戳紀錄。", 0))
    alert_section, has_alert = safe(build_alert_section, ("無法讀取異常摘要。", False))
    cex_section, cex_count = safe(lambda: build_cex_events_section(today_str), ("無法讀取交易所事件。", 0))
    change_section = safe(build_change_detection_section, "無法讀取變動偵測紀錄。")
    cumulative_section = safe(build_cumulative_stats, "無法計算累積統計。")
    health_issues, health_pending, health_notices = safe(build_health_issues, (None, None, None))

    # 官方異常總數：優先採用與 healthcheck.py／ALERT.md 完全相同的判定結果
    # （見 build_health_issues 說明）。只有在 healthcheck.py 無法載入／執行時
    # （理論上不應發生，屬防禦性後備），才退回舊版的加總方式，並在結論註明
    # 這是後備估計值，避免程式崩潰或報告開天窗。
    if health_issues is not None:
        total_anomalies = len(health_issues)
        anomaly_source_note = "（與 ALERT.md 採同一套 healthcheck.py 判定邏輯，逐項一致）"
    else:
        total_anomalies = 0
        for v in (source_anomalies, cron_anomalies, ts_missing):
            try:
                total_anomalies += int(v or 0)
            except Exception:
                pass
        if has_alert:
            total_anomalies += 1
        anomaly_source_note = "（⚠️ healthcheck.py 無法載入，改用本檔後備估計，可能與 ALERT.md 不一致，請人工核對）"

    conclusion = ("一切正常。" if total_anomalies == 0
                  else f"有 {total_anomalies} 項異常{anomaly_source_note}，詳見下方各節。")

    sections.append(f"# 每日資料蒐集報告\n")
    sections.append(
        f"產生時間：{now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        f"（台北時間 {now_tpe.strftime('%Y-%m-%d %H:%M:%S')} UTC+8）\n"
    )
    sections.append(f"## 一句話結論\n\n{conclusion}\n")
    sections.append(
        f"（本輪自動探索到 {len(ACTIVE)} 個來源：軌一 "
        f"{len([1 for t, _ in ACTIVE if t == 'track-crypto'])} 個、軌二 "
        f"{len([1 for t, _ in ACTIVE if t == 'track-gov'])} 個；新增來源不需再修改本程式。）\n"
    )

    sections.append("## 來源對照表\n")
    sections.append(render_source_table(rows) if rows else "無法讀取來源資料。")
    sections.append(
        "\n註：本表「截斷」「解析失敗」欄位標記的來源屬於資料品質提示；"
        "官方異常總數以下方〈異常摘要〉為準，避免同一件事重複計數。\n"
    )

    sections.append("## 變動偵測\n")
    sections.append(change_section)
    sections.append("")

    sections.append("## 交易所事件流\n")
    sections.append(cex_section)
    sections.append("")

    sections.append("## 排程執行狀況\n")
    sections.append(cron_section)
    sections.append("")

    sections.append("## 時間戳\n")
    sections.append(ts_section)
    sections.append("")

    sections.append("## 累積統計\n")
    sections.append(cumulative_section)
    sections.append("")

    sections.append("## 異常摘要\n")
    if health_issues is not None:
        sections.append(
            f"以下 {len(health_issues)} 項為官方異常清單，判定邏輯直接呼叫 "
            f"`healthcheck.py` 的 `check_timestamps`／`check_manifest`／"
            f"`check_truncation_streak`／`check_source`（唯讀，本檔不寫入 ALERT.md），"
            f"與當日 ALERT.md 逐項一致：\n"
        )
        if health_issues:
            sections.append(render_health_issues_table(health_issues))
        else:
            sections.append("（無異常）")
        if health_pending:
            sections.append("")
            sections.append(f"另有 {len(health_pending)} 項尚在排程寬限期內（非異常）：")
            sections.append("")
            sections.append("| 來源 | 狀態 |")
            sections.append("|---|---|")
            for a, b in health_pending:
                sections.append(f"| `{a}` | {b} |")
        sections.append("")
        sections.append("以下為 ALERT.md 等檔案的原始內容（供交叉核對）：")
        sections.append("")
    sections.append(alert_section)
    sections.append("")

    sections.append(
        "## 暫不判定／基準重建中（資訊，非異常，不計入異常數，不寫入 ALERT.md）\n"
    )
    sections.append(render_notice_section(health_notices))
    sections.append("")

    sections.append(
        "\n---\n本報告僅陳述資料蒐集流程的技術事實（筆數、體積、耗時、排程狀態），"
        "不構成任何投資建議或市場判斷。\n"
    )

    report = "\n".join(sections)

    out_path = os.path.join(REPO, "REPORT.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"REPORT.md written to {out_path}")


if __name__ == "__main__":
    main()
