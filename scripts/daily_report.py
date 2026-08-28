#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_report.py

依 REPORT_SPEC.md 產生 <REPO>/REPORT.md。
只用 Python 標準函式庫；只讀取資料，唯一寫入的檔案是 REPORT.md。
任何一段資料缺失都不可讓程式崩潰：一律顯示「—」或「無紀錄」並繼續下一段。
"""

import os
import sys
import json
import glob
import re
import statistics
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

UTC = timezone.utc
TPE = timezone(timedelta(hours=8))

CRYPTO_SOURCES = ["x402_bazaar", "cex_symbols", "vast_gpu"]
GOV_CHANNELS = [
    "fsc_clarification", "moe_clarify", "moj_press", "cbc_press",
    "mof_press", "mol_press", "moda_press", "moi_press",
    "ey_press", "mohw_press", "moe_press", "moea_press",
]

NAME_MAP = {
    "fsc_clarification": "金管會即時新聞澄清",
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
    "x402_bazaar": "x402 協議掛牌",
    "cex_symbols": "交易所交易對",
    "vast_gpu": "vast.ai GPU 報價",
}

DASH = "—"


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
    回傳 (rows, anomaly_count)
    rows: list of dict，欄位：來源, 中文名, 今日筆數, 昨日筆數, 增減, 今日體積, 體積增減%, 耗時
    """
    rows = []
    anomalies = 0

    crypto_dir = os.path.join(REPO, "track-crypto")
    gov_dir = os.path.join(REPO, "track-gov")

    crypto_manifest_today = load_manifest(crypto_dir, today_str)
    crypto_manifest_yday = load_manifest(crypto_dir, yesterday_str)
    gov_manifest_today = load_manifest(gov_dir, today_str)
    gov_manifest_yday = load_manifest(gov_dir, yesterday_str)

    # 軌一：crypto，3 個來源
    for src in CRYPTO_SOURCES:
        cn = NAME_MAP.get(src, src)
        today_n = None
        today_bytes = None
        secs = None
        ok = None

        m_today = None
        if crypto_manifest_today and isinstance(crypto_manifest_today.get("sources"), dict):
            m_today = crypto_manifest_today["sources"].get(src)
        if m_today:
            today_bytes = m_today.get("bytes")
            secs = m_today.get("secs")
            ok = m_today.get("ok")

        # 筆數：crypto 從 stats.json 的 total 取
        source_dir = os.path.join(crypto_dir, "data", src)
        _, stats_path = latest_snapshot_for_date(source_dir, today_str)
        if stats_path:
            stats = safe(lambda: read_json(stats_path))
            if stats:
                today_n = stats.get("total")

        yday_n = None
        yday_source_dir = os.path.join(crypto_dir, "data", src)
        _, yday_stats_path = latest_snapshot_for_date(yday_source_dir, yesterday_str)
        if yday_stats_path:
            yday_stats = safe(lambda: read_json(yday_stats_path))
            if yday_stats:
                yday_n = yday_stats.get("total")

        yday_bytes = None
        if crypto_manifest_yday and isinstance(crypto_manifest_yday.get("sources"), dict):
            m_yday = crypto_manifest_yday["sources"].get(src)
            if m_yday:
                yday_bytes = m_yday.get("bytes")

        if ok is False:
            anomalies += 1

        rows.append({
            "來源": src,
            "中文名": cn,
            "今日筆數": fmt_num(today_n),
            "昨日筆數": fmt_num(yday_n),
            "增減": diff_str(today_n, yday_n),
            "今日體積": fmt_bytes(today_bytes),
            "體積增減%": pct_change(today_bytes, yday_bytes),
            "耗時": fmt_secs(secs),
            "軌": "軌一",
        })

    # 軌二：gov，12 個機關，筆數一律讀 manifest 的 n（stats.total 是 null，不可用）
    for ch in GOV_CHANNELS:
        cn = NAME_MAP.get(ch, ch)
        today_n = None
        today_bytes = None
        secs = None
        ok = None

        if gov_manifest_today and isinstance(gov_manifest_today.get("channels"), dict):
            m_today = gov_manifest_today["channels"].get(ch)
            if m_today:
                today_n = m_today.get("n")
                today_bytes = m_today.get("bytes")
                secs = m_today.get("secs")
                ok = m_today.get("ok")

        yday_n = None
        yday_bytes = None
        if gov_manifest_yday and isinstance(gov_manifest_yday.get("channels"), dict):
            m_yday = gov_manifest_yday["channels"].get(ch)
            if m_yday:
                yday_n = m_yday.get("n")
                yday_bytes = m_yday.get("bytes")

        if ok is False:
            anomalies += 1

        rows.append({
            "來源": ch,
            "中文名": cn,
            "今日筆數": fmt_num(today_n),
            "昨日筆數": fmt_num(yday_n),
            "增減": diff_str(today_n, yday_n),
            "今日體積": fmt_bytes(today_bytes),
            "體積增減%": pct_change(today_bytes, yday_bytes),
            "耗時": fmt_secs(secs),
            "軌": "軌二",
        })

    return rows, anomalies


def render_source_table(rows):
    header = "| 軌 | 來源 | 中文名 | 今日筆數 | 昨日筆數 | 增減 | 今日體積 | 體積增減% | 耗時 |"
    sep = "|---|---|---|---|---|---|---|---|---|"
    lines = [header, sep]
    for r in rows:
        lines.append(
            f"| {r['軌']} | {r['來源']} | {r['中文名']} | {r['今日筆數']} | "
            f"{r['昨日筆數']} | {r['增減']} | {r['今日體積']} | {r['體積增減%']} | {r['耗時']} |"
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


CHANGE_LINE_RE = re.compile(
    r"^(?P<key>[^:]+): (?P<d1>\d{4}-\d{2}-\d{2})→(?P<d2>\d{4}-\d{2}-\d{2}) "
    r"改寫(?P<changed>\d+) 下架(?P<removed>\d+) 新增(?P<added>\d+)"
    r"(?:（另有 (?P<rolled>\d+) 筆滾動移出視窗，不計為下架）)?$"
)
SKIP_LINE_RE = re.compile(r"^(?P<key>[^:]+): 快照不足 2 份，略過$")
SUMMARY_LINE_RE = re.compile(r"^SUMMARY changed=(?P<changed>\d+) removed=(?P<removed>\d+)$")


def parse_change_detection_rows(block):
    """把 detect.log 一輪的行解析成結構化資料：(rows, skipped_keys, summary_dict)。"""
    rows = []
    skipped = []
    summary = None
    for line in block:
        m = CHANGE_LINE_RE.match(line)
        if m:
            rows.append({
                "來源": m.group("key"),
                "區間": f"{m.group('d1')}→{m.group('d2')}",
                "改寫": int(m.group("changed")),
                "下架": int(m.group("removed")),
                "新增": int(m.group("added")),
                "滾動移出": int(m.group("rolled")) if m.group("rolled") else 0,
            })
            continue
        m = SKIP_LINE_RE.match(line)
        if m:
            skipped.append(m.group("key"))
            continue
        m = SUMMARY_LINE_RE.match(line)
        if m:
            summary = {"changed": int(m.group("changed")), "removed": int(m.group("removed"))}
            continue
        # 無法辨識的行：忽略但不崩潰
    return rows, skipped, summary


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
        total_removed += r["下架"]
        total_added += r["新增"]
        total_rolled += r["滾動移出"]
    lines.append(f"| **總計** |  | {total_changed} | {total_removed} | {total_added} | {total_rolled} |")
    return "\n".join(lines)


def build_change_detection_section():
    lines = []
    detect_log = os.path.join(REPO, "logs", "detect.log")   # 實際位置在 repo 根的 logs/，不在 track-gov/logs/
    block, _unused_summary = safe(lambda: parse_detect_log_last_round(detect_log), (None, None))
    if block:
        rows, skipped, summary = safe(lambda: parse_change_detection_rows(block), ([], [], None))
        if rows:
            lines.append("最近一輪變動偵測：")
            lines.append("")
            lines.append(render_change_table(rows))
        if skipped:
            lines.append("")
            lines.append("略過（快照不足 2 份）：" + "、".join(skipped))
        if summary:
            lines.append("")
            lines.append(f"本輪彙總：changed={summary.get('changed', DASH)}，removed={summary.get('removed', DASH)}。")
        if not rows and not skipped and not summary:
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
    """
    lines = []
    anomalies = 0
    for track, label, key_field, expected_sources in [
        ("track-crypto", "軌一（track-crypto）", "sources", CRYPTO_SOURCES),
        ("track-gov", "軌二（track-gov）", "channels", GOV_CHANNELS),
    ]:
        track_dir = os.path.join(REPO, track)
        log_path = os.path.join(track_dir, "logs", "cron.log")
        info = safe(lambda lp=log_path: parse_cron_log(lp, None), {"today_found": False, "today_summary": None, "history": []})
        lines.append(f"**{label}**：")

        manifest_today = safe(lambda td=track_dir: load_manifest(td, today_str))
        fetched_date = manifest_fetched_at_date(manifest_today)
        channel_count = manifest_source_count(manifest_today, key_field)
        runs = manifest_runs(manifest_today)

        if manifest_today is not None and fetched_date == today_str:
            count_str = channel_count if channel_count is not None else DASH
            lines.append(f"- 今日已執行（依 manifest `fetched_at`={fetched_date} 判斷），manifest 記錄 {count_str} 個來源。")
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
    alert_files = ["ALERT.md", "ALERT-DETECT.md", "ALERT-HEALTH.md"]
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


def main():
    now_utc = datetime.now(UTC)
    now_tpe = now_utc.astimezone(TPE)

    today_str = now_utc.strftime("%Y-%m-%d")
    yesterday_str = (now_utc - timedelta(days=1)).strftime("%Y-%m-%d")

    sections = []

    rows, source_anomalies = safe(lambda: build_source_table(today_str, yesterday_str), ([], 0))
    cron_section, cron_anomalies = safe(lambda: build_cron_section(today_str), ("無法讀取 cron 紀錄。", 0))
    ts_section, ts_missing = safe(build_timestamp_section, ("無法讀取時間戳紀錄。", 0))
    alert_section, has_alert = safe(build_alert_section, ("無法讀取異常摘要。", False))
    cex_section, cex_count = safe(lambda: build_cex_events_section(today_str), ("無法讀取交易所事件。", 0))
    change_section = safe(build_change_detection_section, "無法讀取變動偵測紀錄。")
    cumulative_section = safe(build_cumulative_stats, "無法計算累積統計。")

    total_anomalies = 0
    try:
        total_anomalies += int(source_anomalies or 0)
    except Exception:
        pass
    try:
        total_anomalies += int(cron_anomalies or 0)
    except Exception:
        pass
    try:
        total_anomalies += int(ts_missing or 0)
    except Exception:
        pass
    if has_alert:
        total_anomalies += 1

    conclusion = "一切正常。" if total_anomalies == 0 else f"有 {total_anomalies} 項異常，詳見下方各節。"

    sections.append(f"# 每日資料蒐集報告\n")
    sections.append(
        f"產生時間：{now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        f"（台北時間 {now_tpe.strftime('%Y-%m-%d %H:%M:%S')} UTC+8）\n"
    )
    sections.append(f"## 一句話結論\n\n{conclusion}\n")

    sections.append("## 來源對照表\n")
    sections.append(render_source_table(rows) if rows else "無法讀取來源資料。")
    sections.append("")

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
    sections.append(alert_section)
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
