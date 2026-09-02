#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/selftest.py — 離線回歸自測（見 docs/selftest.md）

依 specs/SPEC-selftest.md 撰寫，並依 specs/SPEC-selftest-fix.md 修復
mut_dd_reappeared 錨點不唯一問題、新增第二階段（GROUP_SOURCES 多子集合）
新行為的 5 條檢查，再依 specs/SPEC-selftest-gap.md 補齊 selftest-fix 收尾時
自陳的 2 個覆蓋缺口：build_group_events() 的 REAPPEARED 判定（第二階段多子集合
路徑，先前只有 process_pair() 單一清單路徑有專屬檢查）、payment_protocol_repos
的 require_empty 機制（見 track-crypto/scripts/detect_delistings.py 一節開頭說明）。
涵蓋 5 支關鍵程式的核心保護機制：
  detect_changes.py（track-gov 內容改寫/下架偵測）
  track-crypto/scripts/detect_delistings.py（x402_bazaar 下架偵測）
  cex_events.py（7 家交易所上下架事件流）
  healthcheck.py（每日巡檢 -> ALERT.md）
  daily_report.py（每日巡檢報告 -> REPORT.md）

設計原則（硬性）：
  1. 唯讀正式目錄：本檔只會「讀取」下列來源（sibling 腳本原始碼、adapters 目錄、
     track-*/data/ 內指定的歷史快照檔），從不寫入。所有輸出（合成快照、腳本副本、
     沙盒程式輸出）一律寫在 WORKDIR（預設 /tmp/selftest/，可用環境變數覆寫）。
  2. 不連外網：全程只讀本機檔案、寫本機檔案、以子行程呼叫本機 python3。
  3. 每條不變量兩段式驗證：
       a. 正常檢查：合成或既有歷史快照餵給「目前的正式程式碼」，斷言保護機制觸發，PASS。
       b. 破壞驗證（名稱以 `#mutant` 結尾）：對同一支程式的暫存副本做最小化的定向修改
          （關掉那一條保護），用同一組資料重跑，斷言結果翻盤成 FAIL——證明「如果這條
          保護哪天被誤刪或改壞，本測試真的抓得到」。
  4. 輸出格式：每項一行 `PASS`／`FAIL <name>: <detail>`，最後一行 `SUMMARY`，
     任一項 FAIL 則整體結束碼非 0。

環境變數：
  SELFTEST_SOURCE_REPO   要測試的目標 repo 根目錄（預設＝本檔案所在位置往上一層，
                         即 <repo>/scripts/selftest.py 部署時的正常行為）。
                         本檔完全「唯讀」使用這個路徑：讀取 5 支關鍵程式的目前原始碼、
                         adapters/*.py（僅供 real-replay 檢查的 ACTIVE 全量比對用）、
                         以及下列指定的既有歷史快照檔（供 real-replay 檢查固定輸入）。
  SELFTEST_WORKDIR       本檔所有輸出（沙盒、合成快照、報告用暫存檔）的根目錄，
                         預設 /tmp/selftest/selftest-run-<timestamp>-<pid>。
  SELFTEST_SKIP_MUTANTS  設為 1 時只跑「正常檢查」，略過「破壞驗證」（加速用；
                         預設兩者都跑，見 docs/selftest.md 的時間預算實測）。
"""
import argparse
import contextlib
import re
import gzip
import hashlib
import importlib.util
import itertools
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime

# --------------------------------------------------------------------------
# 路徑解析
# --------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_SELF = os.path.dirname(HERE)
SOURCE_REPO = os.environ.get("SELFTEST_SOURCE_REPO") or REPO_SELF
WORKDIR_ROOT = os.environ.get("SELFTEST_WORKDIR") or os.path.join(
    "/tmp/selftest", "run-%s-%d" % (datetime.now().strftime("%Y%m%d-%H%M%S"), os.getpid()))
SKIP_MUTANTS = os.environ.get("SELFTEST_SKIP_MUTANTS") == "1"

# 目標程式相對於 SOURCE_REPO 的路徑（與正式部署位置一致，供 __file__ 型路徑推算沿用）。
TARGET_REL = {
    "detect_changes":    "scripts/detect_changes.py",
    "detect_delistings": "track-crypto/scripts/detect_delistings.py",
    "cex_events":        "scripts/cex_events.py",
    "healthcheck":       "scripts/healthcheck.py",
    "daily_report":      "scripts/daily_report.py",
    "snap_gov":          "track-gov/scripts/snap_gov.py",   # 輔助：揮發性欄位守門實作位置見 docs/selftest.md
}


def source_path(name):
    return os.path.join(SOURCE_REPO, TARGET_REL[name])


_SOURCE_CACHE = {}


def read_source(name):
    if name not in _SOURCE_CACHE:
        with open(source_path(name), encoding="utf-8") as f:
            _SOURCE_CACHE[name] = f.read()
    return _SOURCE_CACHE[name]


# --------------------------------------------------------------------------
# 小工具：沙盒建立、寫檔、動態載入、子行程執行
# --------------------------------------------------------------------------
_sandbox_counter = itertools.count()


def new_sandbox(tag):
    """建立一個全新、乾淨的沙盒目錄。若同名目錄因為 WORKDIR 被重複使用（例如呼叫端手動
    固定 SELFTEST_WORKDIR 重跑多次）而已經存在，先整個刪除重建——不能讓上一輪殘留的輸出檔
    （例如 detect_delistings.py 的 ALERT-DELIST.md 冪等合併 marker）汙染這一輪的判定，
    這曾經在開發過程中造成一次難以理解的假陽性（同一條檢查在乾淨環境下 PASS、
    重跑同一個固定 WORKDIR 卻 FAIL），見 docs/selftest-report.md。"""
    d = os.path.join(WORKDIR_ROOT, "sandbox-%03d-%s" % (next(_sandbox_counter), tag))
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d, exist_ok=True)
    return d


def install_text(sandbox, rel_path, text):
    """把文字內容寫到 sandbox/rel_path（自動建立父目錄），回傳絕對路徑。"""
    dest = os.path.join(sandbox, rel_path)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(text)
    return dest


def install_binary_copy(src_abs, sandbox, rel_path):
    dest = os.path.join(sandbox, rel_path)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copyfile(src_abs, dest)
    return dest


def write_gz_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    return path


def read_jsonl(path):
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


_mod_counter = itertools.count()


def load_module(path):
    """以路徑動態載入一支腳本副本為獨立模組（每次呼叫用唯一模組名，避免快取互相污染）。
    這是本專案既有慣例（daily_report.py 用同一手法載入 healthcheck.py），非新發明。"""
    modname = "selftest_dyn_%d" % next(_mod_counter)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_py(script_path, cwd, extra_env=None, timeout=60, args=None):
    """以子行程執行一支 .py 檔（模擬正式排程的呼叫方式：python3 script.py）。
    env 只帶最基本的 PATH／必要變數＋呼叫端指定的 extra_env，不繼承
    SELFTEST_SOURCE_REPO／SELFTEST_WORKDIR，避免子行程誤用本測試自己的設定。"""
    env = {k: v for k, v in os.environ.items()
            if k not in ("SELFTEST_SOURCE_REPO", "SELFTEST_WORKDIR", "SELFTEST_SKIP_MUTANTS")}
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, script_path] + (args or [])
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        return 124, e.stdout or "", (e.stderr or "") + "\n[selftest] TIMEOUT after %ss" % timeout


def apply_mutation(text, anchor, replacement, label):
    """在原始碼字串裡找到唯一一段 anchor 文字並替換成 replacement。
    找不到或找到超過一次都直接丟例外（寧可讓 selftest 自己先炸開,也不要悄悄比錯東西）——
    這種情況代表正式程式碼已經改版，這段 mutation 的錨點文字需要跟著更新。"""
    n = text.count(anchor)
    if n == 0:
        raise RuntimeError("mutation anchor not found for %r: %r" % (label, anchor[:100]))
    if n > 1:
        raise RuntimeError("mutation anchor not unique (%d matches) for %r" % (n, label))
    return text.replace(anchor, replacement, 1)


# --------------------------------------------------------------------------
# Check 結果與登記
# --------------------------------------------------------------------------
class Result:
    def __init__(self, passed, detail=""):
        self.passed = bool(passed)
        self.detail = detail


CHECKS = []  # list of dict(name, fn, mutate_target, mutate)


def check(name, mutate_target=None, mutate=None):
    """裝飾器：登記一項檢查。fn(is_mutant: bool) -> Result。
    is_mutant=False 時 fn 應該用「目前的正式原始碼」跑；is_mutant=True 時 fn 應該
    對 mutate_target 那一支程式套用 mutate(text)->text 之後再跑同一組資料。
    這樣同一份檢查邏輯自動同時提供「正常檢查」與「破壞驗證」兩種輸出，不必為每條
    不變量另外寫一份重複的『壞掉版』檢查程式。"""
    def deco(fn):
        CHECKS.append(dict(name=name, fn=fn, mutate_target=mutate_target, mutate=mutate))
        return fn
    return deco


def get_script_text(name, is_mutant, mutate_target, mutate):
    text = read_source(name)
    if is_mutant and mutate_target == name:
        text = mutate(text)
    return text


# ==========================================================================
# 合成資料 schema 建構器（欄位名稱、巢狀結構均核對自 VPS 正式歷史快照，
# 見 docs/selftest.md「合成資料 schema 來源」一節；日期一律用未來年份 2030，
# 一眼可辨識為合成測試資料，不會與任何真實資料混淆——比照 docs/cex-events-audit.md 的做法）
# ==========================================================================

def gov_item(item_id, title, body_text, url=None, date="119-01-01"):
    """比照 track-gov 快照 items[] 的欄位（見 track-gov/data/*/**.json.gz 實測 schema）。"""
    return {
        "id": str(item_id),
        "url": url or ("https://example.invalid/selftest/%s" % item_id),
        "title": title,
        "date": date,
        "body_text": body_text,
        "body_sha256": hashlib.sha256(body_text.encode()).hexdigest(),
    }


def gov_snapshot(items, parser_version=1, truncated=False, total=None, errors=None, items_fetched=None):
    """比照 track-gov 快照頂層 schema：{_meta, total, errors, items}（無 data 包裝，
    detect_changes.py 的 load() 用 j.get("data", j) 相容處理）。"""
    meta = {
        "channel": "selftest-synthetic", "desc": "Selftest synthetic fixture (not a real source)",
        "parser_version": parser_version, "fetched_at": "2030-01-01T00:00:00+00:00",
        "license": "N/A (selftest synthetic fixture)", "note": "selftest 合成測試資料，非正式來源",
    }
    if truncated:
        meta["truncated"] = True
        meta["items_fetched"] = items_fetched if items_fetched is not None else len(items)
    return {"_meta": meta, "total": total if total is not None else len(items),
            "errors": errors or {}, "items": items}


DC_CFG = {"key": "id", "title": "title", "text": "body_text", "sha": "body_sha256",
          "url": "url", "label": "Selftest Synthetic Source"}


def x402_item(resource, description, l30=5):
    """比照 track-crypto/data/x402_bazaar 快照 items[] 的欄位（見實測 schema）。"""
    return {
        "resource": resource, "description": description, "type": "http", "x402Version": 1,
        "lastUpdated": "2030-01-01T00:00:00Z", "accepts": [], "extensions": {},
        "quality": {"l30DaysTotalCalls": l30},
    }


def x402_snapshot(items, total=None):
    """比照 track-crypto/data/x402_bazaar 快照頂層 schema：{_meta, data:{x402Version,total,items}}。"""
    return {"_meta": {"parser_version": 1, "fetched_at": "2030-01-01T00:00:00+00:00"},
            "data": {"x402Version": 1, "total": total if total is not None else len(items), "items": items}}


def gs_item(key_field, key, desc_field=None, desc=None, **fields):
    """比照 GROUP_SOURCES 子集合清單裡一筆項目的形狀：{key_field: key, ...}，
    可選 desc_field（比照 short_desc_generic() 用的欄位）與任意額外欄位（例如狀態旗標，
    供 status_fields／STATUS_CHANGED 檢查用）。"""
    it = {key_field: key}
    if desc_field:
        it[desc_field] = desc
    it.update(fields)
    return it


def gs_snapshot(data):
    """比照 GROUP_SOURCES 來源快照頂層 schema：{_meta, data:{...}}（與 x402_snapshot() 同構，
    但 data 內容由呼叫端自行決定——GROUP_SOURCES 8 個來源的巢狀結構差異很大，不像
    x402_bazaar 只有單一固定形狀，見 track-crypto/scripts/detect_delistings.py 的
    GROUP_SOURCES 設定表）。"""
    return {"_meta": {"parser_version": 1, "fetched_at": "2030-01-01T00:00:00+00:00"}, "data": data}


CEX_SPEC_PATH = {"bybit": ("result", "list"), "okx": ("data",), "bitget": ("data",),
                  "htx": ("data",), "gateio": None, "kucoin": ("data",), "mexc": ("symbols",)}
CEX_SYM_FIELD = {"bybit": "symbol", "okx": "instId", "bitget": "symbol", "htx": "symbol",
                 "gateio": "id", "kucoin": "symbol", "mexc": "symbol"}
CEX_ST_FIELD = {"bybit": "status", "okx": "state", "bitget": "status", "htx": "state",
                "gateio": "trade_status", "kucoin": "enableTrading", "mexc": "status"}


def cex_rows(name, pairs):
    sym_f, st_f = CEX_SYM_FIELD[name], CEX_ST_FIELD[name]
    return [{sym_f: s, st_f: st} for s, st in pairs]


def cex_nest(name, rows):
    path = CEX_SPEC_PATH[name]
    if path is None:
        return rows
    node = rows
    for key in reversed(path):
        node = {key: node}
    return node


def cex_snapshot(exchange_pairs, errors=None):
    """exchange_pairs: {exchange: [(symbol, status), ...]}；未列出的交易所＝完全缺席
    （模擬 exchanges 裡完全沒有這個 key 的情境）。比照 track-crypto/data/cex_symbols
    快照頂層 schema：{_meta, data:{exchanges:{...}, errors:{...}}}（實測核對）。"""
    exchanges = {name: cex_nest(name, cex_rows(name, pairs)) for name, pairs in exchange_pairs.items()}
    return {"_meta": {"fetched_at": "2030-01-01T00:00:00+00:00"},
            "data": {"exchanges": exchanges, "errors": errors or {}}}


def install_fake_adapter(sandbox, track, key, desc):
    text = 'KEY = "%s"\nDESC = "%s"\nPARSER_VERSION = 1\n' % (key, desc)
    install_text(sandbox, "%s/adapters/%s.py" % (track, key), text)


@contextlib.contextmanager
def temp_env(**kv):
    """暫時設定/清除環境變數，離開 with 區塊後還原（供動態 import 需要在特定
    HEALTHCHECK_NOW/HEALTHCHECK_TODAY 底下執行模組頂層程式碼時使用）。"""
    old = {k: os.environ.get(k) for k in kv}
    try:
        for k, v in kv.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ==========================================================================
# Mutation 函式（每一支對應「關掉一條保護機制」的最小定向修改）
# ==========================================================================

def mut_dc_parser_version(text):
    return apply_mutation(
        text, "if v_old != v_new:",
        "if False:  # [selftest mutant] parser-version guard disabled",
        "dc_parser_version")


def mut_dc_truncation(text):
    return apply_mutation(
        text, 'skip_removed = trunc_old or trunc_new',
        'skip_removed = False  # [selftest mutant] truncation guard disabled',
        "dc_truncation")


def mut_dc_rolling_window(text):
    return apply_mutation(
        text, 'rolled = sorted(k for k in removed_set if pos.get(k, 0) >= tail_start)',
        'rolled = []  # [selftest mutant] rolling-window tail exclusion disabled',
        "dc_rolling_window")


def mut_snap_gov_volatile(text):
    return apply_mutation(
        text, 'def strip_volatile(text):\n    out, skip_next_number = [], False',
        'def strip_volatile(text):\n    return text  # [selftest mutant] volatile stripping disabled\n'
        '    out, skip_next_number = [], False',
        "snap_gov_volatile")


def mut_dd_integrity_gate(text):
    return apply_mutation(
        text,
        '    if total != n:\n        return False, total, n, "total(%r) != len(items)(%d)" % (total, n)',
        '    if False:  # [selftest mutant] integrity gate disabled\n'
        '        return False, total, n, "total(%r) != len(items)(%d)" % (total, n)',
        "dd_integrity_gate")


def mut_dd_breaker(text):
    return apply_mutation(
        text, 'breaker = gate_ok and (removed_rate > cfg["breaker_pct"])',
        'breaker = False  # [selftest mutant] breaker disabled',
        "dd_breaker")


def mut_dd_reappeared(text):
    # 錨點修復（2026-09-02，SPEC-selftest-fix.md）：第二階段把 REAPPEARED 判定從單一清單
    # （process_pair()）擴充成也支援多子集合（build_group_events()），導致原本的錨點
    # 'if k in last_delisted:' 逐字元相同地出現在兩支函式裡，apply_mutation() 因此丟出
    # "mutation anchor not unique (2 matches)"。chk_dd_reappeared 這條檢查的合成資料是
    # x402_bazaar 單一清單形狀、只呼叫 process_pair()，不會走到 build_group_events()，
    # 所以錨點必須精確只匹配 process_pair() 那一處，才會「真的讓這條檢查測到的那個保護
    # 失效」（build_group_events() 那一份此檢查根本不會執行到，若連它一起關掉只是無意義
    # 的額外改動，不會讓檢查多驗到什麼，見 docs/selftest-fix-report.md 根因與選項比較）。
    # 修法：把錨點往前延伸到 'short_desc(r["keyed_new"].get(k))'——process_pair() 專屬
    # 呼叫（build_group_events() 用的是 short_desc_generic(...)，兩者不會互相匹配），
    # 使其在目前程式碼中唯一。
    return apply_mutation(
        text,
        '"from": None, "to": short_desc(r["keyed_new"].get(k))})\n            if k in last_delisted:',
        '"from": None, "to": short_desc(r["keyed_new"].get(k))})\n'
        '            if False and k in last_delisted:  # [selftest mutant] REAPPEARED disabled',
        "dd_reappeared")


def mut_dd_idempotency(text):
    return apply_mutation(
        text,
        'fresh = [e for e in new_events\n'
        '             if (e["date"], e["source"], e["group"], e["key"], e["event"]) not in seen]',
        'fresh = [e for e in new_events]  # [selftest mutant] idempotency (seen) filter disabled',
        "dd_idempotency")


def mut_dd_status_changed(text):
    # 目標：status_changes_for_group() 逐欄位比對 status_fields 是否翻轉的核心判斷式。
    return apply_mutation(
        text, 'if ov != nv:',
        'if False:  # [selftest mutant] STATUS_CHANGED field-diff detection disabled',
        "dd_status_changed")


def mut_dd_group_integrity_gate(text):
    # 目標：completeness_group() 的 range_check 分支（沒有 total/count 自報欄位時的
    # 完整性守門，第二階段新增，第一階段 dd_integrity_gate 測的是 total_match 分支，
    # 兩者是不同程式碼路徑）。
    return apply_mutation(
        text, 'if n_raw < lo or n_raw > hi:',
        'if False:  # [selftest mutant] group range_check gate disabled',
        "dd_group_integrity_gate")


def mut_dd_group_breaker(text):
    # 目標：compare_group() 的熔斷判定式（第二階段新增的 threshold_count 泛化公式，
    # 第一階段 dd_breaker 測的是 compare_pair() 的 removed_rate 版本，兩者程式碼互相獨立）。
    return apply_mutation(
        text, 'breaker = gate_ok and (len(removed_keys) > threshold_count)',
        'breaker = False  # [selftest mutant] group breaker disabled',
        "dd_group_breaker")


def mut_dd_group_isolation(text):
    # 目標：process_group_source_pair() 逐子集合迴圈本身。刻意注入一種寫實的「污染」
    # 錯誤——若前面已經處理過的子集合有任何一個不是 NORMAL，就強制把目前這個子集合也
    # 判成 GATE_FAIL（模擬「共用了不該共用的狀態」這類重構失誤），藉此證明目前的迴圈
    # 寫法（每個子集合的 judged 只由它自己的 compare_group() 結果決定）確實是必要的。
    return apply_mutation(
        text,
        '        judged = judge(r, gcfg)\n'
        '        last_delisted = last_delisted_by_group.setdefault(gname, {})',
        '        judged = judge(r, gcfg)\n'
        '        if any(gr["judged"] != "NORMAL" for gr in group_results.values()):  '
        '# [selftest mutant] cross-group contamination reintroduced\n'
        '            judged = "GATE_FAIL"\n'
        '        last_delisted = last_delisted_by_group.setdefault(gname, {})',
        "dd_group_isolation")


def mut_dd_ppr_breaker(text):
    # 目標：GROUP_SOURCES["payment_protocol_repos"] 的專屬熔斷參數本身（不是一段程式邏輯，
    # 是設定值）。還原成其餘子集合沿用的共通門檻（1.0% / abs_floor=5），模擬「未來重構時
    # 誤把這個來源的特例設定值也一併『統一』掉」的情境。
    return apply_mutation(
        text, '"breaker_pct": 60.0, "abs_floor": 1,',
        '"breaker_pct": 1.0, "abs_floor": 5,'
        '  # [selftest mutant] payment_protocol_repos 過半即熔斷特例已還原成共通門檻',
        "dd_ppr_breaker")


def mut_dd_group_reappeared(text):
    # 目標：build_group_events()（第二階段多子集合版本）的 REAPPEARED 判定，與
    # mut_dd_reappeared（process_pair() 專屬）是不同程式碼路徑——build_group_events()
    # 用 short_desc_generic(...)，process_pair() 用 short_desc(...)，兩者錨點字面
    # 不會互相匹配（撞名根因見 docs/selftest-fix-report.md §1.2，覆蓋缺口緣起見該報告
    # §3.5；本函式與 mut_dd_reappeared 都改「if k in last_delisted:」這句判斷式，
    # 但取的是各自函式專屬的前導字串，確保只精確命中其中一處）。
    return apply_mutation(
        text,
        '"from": None, "to": short_desc_generic(r["keyed_new"].get(k), desc_field)})\n'
        '        if k in last_delisted:',
        '"from": None, "to": short_desc_generic(r["keyed_new"].get(k), desc_field)})\n'
        '        if False and k in last_delisted:  # [selftest mutant] group REAPPEARED disabled',
        "dd_group_reappeared")


def mut_dd_ppr_require_empty(text):
    # 目標：completeness_group() 的 require_empty 檢查迴圈——第二階段新增的第二道
    # 完整性防線（payment_protocol_repos adapter MIN_SUCCESS=2，count==len(repos)
    # 單獨不足以保證完整，見 docs/detect-phase2-report.md §2.8／§5.5）。
    return apply_mutation(
        text,
        'for rf in gcfg.get("require_empty", ()):\n'
        '            rv = data_root.get(rf)\n'
        '            if rv:\n'
        '                return False, n_raw, "%s 非空（%r），視為部分抓取失敗" % (rf, rv)',
        'for rf in gcfg.get("require_empty", ()):\n'
        '            rv = data_root.get(rf)\n'
        '            if False:  # [selftest mutant] require_empty check disabled\n'
        '                return False, n_raw, "%s 非空（%r），視為部分抓取失敗" % (rf, rv)',
        "dd_ppr_require_empty")


def mut_ce_daily_dedup(text):
    return apply_mutation(
        text, 'return [per_day[k] for k in sorted(per_day)]',
        'return sorted(glob.glob(os.path.join(SRC, "*.json.gz")))  # [selftest mutant] daily dedup disabled',
        "ce_daily_dedup")


def mut_ce_exchange_gate(text):
    return apply_mutation(
        text, '            if reasons:\n                msg = (',
        '            if False:  # [selftest mutant] exchange-level gate disabled\n                msg = (',
        "ce_exchange_gate")


def mut_ce_anomaly(text):
    return apply_mutation(
        text, 'anomalous = len(removed) > threshold',
        'anomalous = False  # [selftest mutant] anomaly annotation disabled',
        "ce_anomaly")


def mut_hc_streak(text):
    return apply_mutation(
        text, 'if len(streak) < TRUNC_STREAK_N:\n            continue',
        'if len(streak) < 1:  # [selftest mutant] streak threshold forced to 1\n            continue',
        "hc_streak")


def mut_hc_grace(text):
    return apply_mutation(
        text,
        '避免漏檢真異常。"""\n    exp = EXPECTED_DONE_TAIPEI.get(track)',
        '避免漏檢真異常。"""\n    return True  # [selftest mutant] grace period forced always-passed\n'
        '    exp = EXPECTED_DONE_TAIPEI.get(track)',
        "hc_grace")


def mut_dr_all_listed(text):
    return apply_mutation(
        text,
        'if ok is False or truncated or parse_failed:\n            anomaly_count += 1\n\n        rows.append({',
        'if ok is False or truncated or parse_failed:\n            anomaly_count += 1\n\n'
        '        if m_today is None:  # [selftest mutant] silent-drop bug reintroduced\n            continue\n\n'
        '        rows.append({',
        "dr_all_listed")


def mut_dr_alert_consistency(text):
    return apply_mutation(
        text, 'except Exception:\n        return None, None\n    return issues, pending',
        'except Exception:\n        return None, None\n'
        '    return (issues[:-1] if issues else issues), pending  # [selftest mutant] silently drop last issue',
        "dr_alert_consistency")


# ==========================================================================
# detect_changes.py — 4 條不變量
# ==========================================================================

@check("detect_changes.parser_version_skip", mutate_target="detect_changes", mutate=mut_dc_parser_version)
def chk_dc_parser_version(is_mutant):
    sandbox = new_sandbox("dc_parserver_mut" if is_mutant else "dc_parserver")
    text = read_source("detect_changes")
    if is_mutant:
        text = mut_dc_parser_version(text)
    script_path = install_text(sandbox, "scripts/detect_changes.py", text)
    install_fake_adapter(sandbox, "track-gov", "synthsrc", "Selftest synthetic source (fixture)")
    old = gov_snapshot([
        gov_item("A1", "T-A1", "body A1 original text (selftest synthetic)"),
        gov_item("B1", "T-B1", "body B1 (selftest synthetic, would vanish if compared)"),
    ], parser_version=1)
    new = gov_snapshot([
        gov_item("A1", "T-A1", "body A1 REWRITTEN text (selftest synthetic, sha differs)"),
        gov_item("C1", "T-C1", "body C1 (selftest synthetic, brand new)"),
    ], parser_version=2)
    write_gz_json(os.path.join(sandbox, "track-gov/data/synthsrc/2030-01-01.json.gz"), old)
    write_gz_json(os.path.join(sandbox, "track-gov/data/synthsrc/2030-01-02.json.gz"), new)
    rc, out, err = run_py(script_path, cwd=sandbox)
    changes_file = os.path.join(sandbox, "changes/synthsrc/2030-01-02.md")
    skip_msg = "跳過本次比對" in out
    file_written = os.path.exists(changes_file)
    guard_active = (rc == 0) and skip_msg and not file_written
    return Result(guard_active,
                  "rc=%d skip_msg_seen=%s changes_file_written=%s stdout_tail=%r"
                  % (rc, skip_msg, file_written, out.strip()[-200:]))


@check("detect_changes.parser_version_skip.real_replay",
       mutate_target="detect_changes", mutate=mut_dc_parser_version)
def chk_dc_parser_version_real(is_mutant):
    """real-replay：track-gov/moi_press 真實歷史快照 2026-08-28（parser_version 缺欄位，
    預設 1）→ 2026-08-31（parser_version=2），VPS 正式資料裡確實發生過的一次解析器改版。"""
    sandbox = new_sandbox("dc_parserver_real_mut" if is_mutant else "dc_parserver_real")
    text = read_source("detect_changes")
    if is_mutant:
        text = mut_dc_parser_version(text)
    script_path = install_text(sandbox, "scripts/detect_changes.py", text)
    install_binary_copy(os.path.join(SOURCE_REPO, "track-gov/adapters/moi_press.py"),
                         sandbox, "track-gov/adapters/moi_press.py")
    install_binary_copy(os.path.join(SOURCE_REPO, "track-gov/data/moi_press/2026-08-28.json.gz"),
                         sandbox, "track-gov/data/moi_press/2026-08-28.json.gz")
    install_binary_copy(os.path.join(SOURCE_REPO, "track-gov/data/moi_press/2026-08-31.json.gz"),
                         sandbox, "track-gov/data/moi_press/2026-08-31.json.gz")
    rc, out, err = run_py(script_path, cwd=sandbox)
    skip_msg = "跳過本次比對" in out
    guard_active = (rc == 0) and skip_msg
    return Result(guard_active, "real-replay moi_press 2026-08-28->2026-08-31; rc=%d skip_msg_seen=%s "
                  "stdout_tail=%r" % (rc, skip_msg, out.strip()[-200:]))


@check("detect_changes.truncation_skips_removed", mutate_target="detect_changes", mutate=mut_dc_truncation)
def chk_dc_truncation(is_mutant):
    sandbox = new_sandbox("dc_trunc_mut" if is_mutant else "dc_trunc")
    text = read_source("detect_changes")
    if is_mutant:
        text = mut_dc_truncation(text)
    script_path = install_text(sandbox, "scripts/detect_changes.py", text)
    old = gov_snapshot([gov_item("I%d" % i, "T%d" % i, "body %d unchanged" % i) for i in range(30)])
    new_items = [gov_item("I%d" % i, "T%d" % i, "body %d unchanged" % i) for i in range(20)]  # 10 vanished
    new = gov_snapshot(new_items, truncated=True, items_fetched=20)
    f_old = write_gz_json(os.path.join(sandbox, "old.json.gz"), old)
    f_new = write_gz_json(os.path.join(sandbox, "new.json.gz"), new)
    mod = load_module(script_path)
    a, b, added, removed, changed, rolled, skip_removed = mod.compare("synthsrc", DC_CFG, f_old, f_new)
    guard_active = skip_removed is True and removed == [] and rolled == []
    return Result(guard_active,
                  "skip_removed=%r removed=%d rolled=%d (expect skip_removed=True, removed=0)"
                  % (skip_removed, len(removed), len(rolled)))


@check("detect_changes.truncation_skips_removed.real_replay",
       mutate_target="detect_changes", mutate=mut_dc_truncation)
def chk_dc_truncation_real(is_mutant):
    """real-replay：track-gov/fda_clarify 真實歷史快照 2026-08-30（未截斷,100 筆）→
    2026-08-31（因每來源時間預算被中止，truncated=true, 33 筆），VPS 正式資料裡確實
    發生過的一次截斷（PERF_FIX_SPEC.md 修正 3）。"""
    sandbox = new_sandbox("dc_trunc_real_mut" if is_mutant else "dc_trunc_real")
    text = read_source("detect_changes")
    if is_mutant:
        text = mut_dc_truncation(text)
    script_path = install_text(sandbox, "scripts/detect_changes.py", text)
    f_old = install_binary_copy(os.path.join(SOURCE_REPO, "track-gov/data/fda_clarify/2026-08-30.json.gz"),
                                 sandbox, "old.json.gz")
    f_new = install_binary_copy(os.path.join(SOURCE_REPO, "track-gov/data/fda_clarify/2026-08-31.json.gz"),
                                 sandbox, "new.json.gz")
    mod = load_module(script_path)
    a, b, added, removed, changed, rolled, skip_removed = mod.compare("fda_clarify", DC_CFG, f_old, f_new)
    guard_active = skip_removed is True and removed == []
    return Result(guard_active,
                  "real-replay fda_clarify 2026-08-30->2026-08-31; skip_removed=%r removed=%d "
                  "(100->33 items，VPS 正式歷史真實發生的截斷；期望 skip_removed=True)"
                  % (skip_removed, len(removed)))


@check("detect_changes.rolling_window_tail_not_removed",
       mutate_target="detect_changes", mutate=mut_dc_rolling_window)
def chk_dc_rolling_window(is_mutant):
    sandbox = new_sandbox("dc_roll_mut" if is_mutant else "dc_roll")
    text = read_source("detect_changes")
    if is_mutant:
        text = mut_dc_rolling_window(text)
    script_path = install_text(sandbox, "scripts/detect_changes.py", text)
    # 100 筆滾動視窗（比照真實來源慣例：陣列 index 0＝最新，index 尾端＝最舊）：
    # 新一天新增 5 筆（I100..I104，排在陣列最前面＝最新），
    # 原本排在陣列尾端（position 95..99＝最舊）的 5 筆被擠出視窗，不計為下架。
    old_items = [gov_item("I%d" % i, "T%d" % i, "body %d unchanged" % i) for i in range(100)]
    new_items = ([gov_item("I%d" % i, "T%d" % i, "body %d unchanged" % i) for i in range(100, 105)]
                 + [gov_item("I%d" % i, "T%d" % i, "body %d unchanged" % i) for i in range(0, 95)])
    old = gov_snapshot(old_items)
    new = gov_snapshot(new_items)
    f_old = write_gz_json(os.path.join(sandbox, "old.json.gz"), old)
    f_new = write_gz_json(os.path.join(sandbox, "new.json.gz"), new)
    mod = load_module(script_path)
    a, b, added, removed, changed, rolled, skip_removed = mod.compare("synthsrc", DC_CFG, f_old, f_new)
    guard_active = (len(added) == 5 and len(rolled) == 5 and len(removed) == 0 and skip_removed is False)
    return Result(guard_active,
                  "added=%d rolled=%d removed=%d (expect added=5 rolled=5 removed=0：尾端移出不算下架)"
                  % (len(added), len(rolled), len(removed)))


@check("detect_changes.rolling_window_tail_not_removed.real_replay",
       mutate_target="detect_changes", mutate=mut_dc_rolling_window)
def chk_dc_rolling_window_real(is_mutant):
    """real-replay：track-gov/mol_press 真實歷史快照 2026-08-28→2026-08-29，
    VPS 正式 logs/detect.log 記錄「新增3（另有3筆滾動移出視窗，不計為下架）」，本檢查
    重放同一組真實快照，確認 compare() 重算出完全相同的數字。"""
    sandbox = new_sandbox("dc_roll_real_mut" if is_mutant else "dc_roll_real")
    text = read_source("detect_changes")
    if is_mutant:
        text = mut_dc_rolling_window(text)
    script_path = install_text(sandbox, "scripts/detect_changes.py", text)
    f_old = install_binary_copy(os.path.join(SOURCE_REPO, "track-gov/data/mol_press/2026-08-28.json.gz"),
                                 sandbox, "old.json.gz")
    f_new = install_binary_copy(os.path.join(SOURCE_REPO, "track-gov/data/mol_press/2026-08-29.json.gz"),
                                 sandbox, "new.json.gz")
    mod = load_module(script_path)
    a, b, added, removed, changed, rolled, skip_removed = mod.compare("mol_press", DC_CFG, f_old, f_new)
    guard_active = (len(added) == 3 and len(rolled) == 3 and len(removed) == 0)
    return Result(guard_active,
                  "real-replay mol_press 2026-08-28->2026-08-29; added=%d rolled=%d removed=%d "
                  "(VPS logs/detect.log 原始記錄：新增3/另有3筆滾動移出視窗/下架0)"
                  % (len(added), len(rolled), len(removed)))


@check("detect_changes.volatile_fields_excluded", mutate_target="snap_gov", mutate=mut_snap_gov_volatile)
def chk_dc_volatile(is_mutant):
    """揮發性欄位不進正文比對。實作位於 track-gov/scripts/snap_gov.py 的 strip_volatile()
    （見 docs/selftest.md 的歸屬澄清），本檢查串接 snap_gov.normalize() 與
    detect_changes.compare() 兩支程式，驗證「只有瀏覽人次不同」不會被誤判為內容改寫。"""
    sandbox = new_sandbox("dc_volatile_mut" if is_mutant else "dc_volatile")
    sg_text = read_source("snap_gov")
    if is_mutant:
        sg_text = mut_snap_gov_volatile(sg_text)
    sg_path = install_text(sandbox, "track-gov/scripts/snap_gov.py", sg_text)
    dc_path = install_text(sandbox, "scripts/detect_changes.py", read_source("detect_changes"))
    sg_mod = load_module(sg_path)
    raw_old = [{"id": "V1", "url": "https://example.invalid/selftest/V1", "title": "T-V1", "date": "119-01-01",
                "body_text": "真正的公告內容不變。\n瀏覽人次：100"}]
    raw_new = [{"id": "V1", "url": "https://example.invalid/selftest/V1", "title": "T-V1", "date": "119-01-01",
                "body_text": "真正的公告內容不變。\n瀏覽人次：987654"}]
    norm_old, norm_new = sg_mod.normalize(raw_old), sg_mod.normalize(raw_new)
    old = gov_snapshot(norm_old)
    new = gov_snapshot(norm_new)
    f_old = write_gz_json(os.path.join(sandbox, "old.json.gz"), old)
    f_new = write_gz_json(os.path.join(sandbox, "new.json.gz"), new)
    mod = load_module(dc_path)
    a, b, added, removed, changed, rolled, skip_removed = mod.compare("synthsrc", DC_CFG, f_old, f_new)
    guard_active = (changed == [])
    return Result(guard_active,
                  "changed=%r sha_old=%s sha_new=%s (只有瀏覽人次不同，期望 changed=[]；"
                  "揮發性欄位守門實作於 track-gov/scripts/snap_gov.py:strip_volatile，非 detect_changes.py 本身)"
                  % (changed, norm_old[0]["body_sha256"][:12], norm_new[0]["body_sha256"][:12]))


# ==========================================================================
# track-crypto/scripts/detect_delistings.py — 11 條不變量（第一階段 4 條 + 第二階段新行為 5 條 + 覆蓋缺口補齊 2 條，SPEC-selftest-gap.md）
# ==========================================================================

def _install_dd(sandbox, text):
    """detect_delistings.py 用 __file__ 動態推算 TRACK_CRYPTO/REPO，必須放在
    <sandbox>/track-crypto/scripts/ 底下（兩層），輸出才會落在 sandbox 內。"""
    return install_text(sandbox, "track-crypto/scripts/detect_delistings.py", text)


@check("detect_delistings.integrity_gate_skips", mutate_target="detect_delistings", mutate=mut_dd_integrity_gate)
def chk_dd_integrity_gate(is_mutant):
    sandbox = new_sandbox("dd_gate_mut" if is_mutant else "dd_gate")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_integrity_gate(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    cfg = mod.SOURCES["x402_bazaar"]
    old = x402_snapshot([x402_item("R%d" % i, "d%d" % i) for i in range(100)])  # total=100，正確
    new_items = [x402_item("R%d" % i, "d%d" % i) for i in range(98)]  # 只剩 98 筆（R98,R99 消失）
    new = x402_snapshot(new_items, total=100)  # 刻意造假：total 仍宣稱 100，但 len(items)=98 → 不一致
    f_old = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-02-01.json.gz"), old)
    f_new = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-02-02.json.gz"), new)
    r = mod.compare_pair("x402_bazaar", cfg, f_old, f_new)
    judged = mod.judge(r, cfg)
    seen, last_delisted = set(), {}
    judged2, r2, fresh, entries, alert_written = mod.process_pair("x402_bazaar", cfg, f_old, f_new, seen, last_delisted)
    guard_active = (judged == "GATE_FAIL") and (fresh == [])
    return Result(guard_active,
                  "total=100 vs len(items)=98（不一致）；judged=%s fresh_events=%d "
                  "(期望 judged=GATE_FAIL，不寫任何事件；removed_rate 若未被此守門攔截將只有 2%%，"
                  "刻意設計在熔斷門檻 5%% 之下，確保這條檢查只測完整性守門本身)"
                  % (judged, len(fresh)))


@check("detect_delistings.breaker_threshold", mutate_target="detect_delistings", mutate=mut_dd_breaker)
def chk_dd_breaker(is_mutant):
    sandbox = new_sandbox("dd_breaker_mut" if is_mutant else "dd_breaker")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_breaker(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    cfg = mod.SOURCES["x402_bazaar"]
    old = x402_snapshot([x402_item("R%d" % i, "d%d" % i) for i in range(100)])
    new_items = [x402_item("R%d" % i, "d%d" % i) for i in range(70)]  # 30 筆消失＝30%，遠超熔斷門檻 5%
    new = x402_snapshot(new_items, total=70)  # total 與 len(items) 一致，完整性守門本身通過
    f_old = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-02-11.json.gz"), old)
    f_new = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-02-12.json.gz"), new)
    seen, last_delisted = {}, {}
    seen = set()
    judged, r, fresh, entries, alert_written = mod.process_pair("x402_bazaar", cfg, f_old, f_new, seen, last_delisted)
    guard_active = (judged == "BREAKER") and (fresh == []) and alert_written
    return Result(guard_active,
                  "removed_rate=%.1f%% (門檻 %.1f%%)；judged=%s fresh_events=%d alert_written=%s "
                  "(期望 judged=BREAKER，不寫事件，改寫 ALERT-DELIST.md)"
                  % (r["removed_rate"], cfg["breaker_pct"], judged, len(fresh), alert_written))


@check("detect_delistings.reappeared_detection", mutate_target="detect_delistings", mutate=mut_dd_reappeared)
def chk_dd_reappeared(is_mutant):
    sandbox = new_sandbox("dd_reappear_mut" if is_mutant else "dd_reappear")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_reappeared(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    cfg = mod.SOURCES["x402_bazaar"]
    day1 = x402_snapshot([x402_item("R%d" % i, "d%d" % i) for i in range(100)])            # R0..R99
    day2 = x402_snapshot([x402_item("R%d" % i, "d%d" % i) for i in range(99)])              # R99 消失
    day3 = x402_snapshot([x402_item("R%d" % i, "d%d" % i) for i in range(100)])             # R99 又出現
    f1 = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-03-01.json.gz"), day1)
    f2 = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-03-02.json.gz"), day2)
    f3 = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-03-03.json.gz"), day3)
    seen, last_delisted = set(), {}
    j12, r12, fresh12, e12, a12 = mod.process_pair("x402_bazaar", cfg, f1, f2, seen, last_delisted)
    j23, r23, fresh23, e23, a23 = mod.process_pair("x402_bazaar", cfg, f2, f3, seen, last_delisted)
    reappeared = [e for e in fresh23 if e["event"] == "REAPPEARED" and e["key"] == "R99"]
    guard_active = (j12 == "NORMAL" and j23 == "NORMAL" and len(reappeared) == 1
                    and reappeared[0]["from"] == "2030-03-02")
    return Result(guard_active,
                  "day1->day2: R99 DELISTED；day2->day3: R99 重新出現；REAPPEARED 事件數=%d %r "
                  "(期望剛好 1 筆，from=2030-03-02)" % (len(reappeared), reappeared))


@check("detect_delistings.idempotent_rerun", mutate_target="detect_delistings", mutate=mut_dd_idempotency)
def chk_dd_idempotent(is_mutant):
    sandbox = new_sandbox("dd_idem_mut" if is_mutant else "dd_idem")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_idempotency(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    cfg = mod.SOURCES["x402_bazaar"]
    # 100 筆基準、只移除 2 筆（2%），確保遠低於熔斷門檻 5%，這條檢查才單純測冪等性本身。
    old = x402_snapshot([x402_item("R%d" % i, "d%d" % i) for i in range(100)])
    new = x402_snapshot([x402_item("R%d" % i, "d%d" % i) for i in range(98)])  # R98,R99 消失
    f_old = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-04-01.json.gz"), old)
    f_new = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-04-02.json.gz"), new)
    seen, last_delisted = set(), {}
    j1, r1, fresh1, e1, a1 = mod.process_pair("x402_bazaar", cfg, f_old, f_new, seen, last_delisted)
    j2, r2, fresh2, e2, a2 = mod.process_pair("x402_bazaar", cfg, f_old, f_new, seen, last_delisted)
    guard_active = (j1 == "NORMAL" and len(fresh1) == 2) and (len(fresh2) == 0)
    return Result(guard_active,
                  "第一次執行新事件=%d，同區間重跑新事件=%d (期望第一次=2、重跑=0：冪等)"
                  % (len(fresh1), len(fresh2)))


@check("detect_delistings.status_changed_detection", mutate_target="detect_delistings",
       mutate=mut_dd_status_changed)
def chk_dd_status_changed(is_mutant):
    """第二階段新增（docs/detect-phase2-report.md §3.3）：主鍵仍在清單中、但
    status_fields 追蹤的欄位值改變時，必須額外產生一筆 STATUS_CHANGED 事件——
    這是全新事件型別，第一階段（x402_bazaar 沒有狀態旗標）完全沒有對應的檢查。"""
    sandbox = new_sandbox("dd_status_mut" if is_mutant else "dd_status")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_status_changed(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg = {"path": ("items",), "shape": "list", "key_field": "key", "desc_field": "name",
            "completeness": "total_match", "total_fields": ("count",),
            "status_fields": ("flag",), "breaker_pct": 50.0, "abs_floor": 5}
    day1 = [gs_item("key", "K%d" % i, "name", "n%d" % i, flag=False) for i in range(10)]
    day2 = [gs_item("key", "K%d" % i, "name", "n%d" % i, flag=(i == 3)) for i in range(10)]  # 只有 K3 旗標翻轉
    data1 = {"items": day1, "count": len(day1)}
    data2 = {"items": day2, "count": len(day2)}
    r = mod.compare_group("selftest_status_src", "grp", gcfg, data1, data2)
    judged = mod.judge(r, gcfg)
    events, _ = mod.build_group_events("selftest_status_src", "grp", gcfg, r, judged, "2030-05-02", {})
    sc_events = [e for e in events if e["event"] == "STATUS_CHANGED"]
    guard_active = (judged == "NORMAL" and len(sc_events) == 1 and sc_events[0]["key"] == "K3"
                    and sc_events[0]["from"] == {"flag": False} and sc_events[0]["to"] == {"flag": True})
    return Result(guard_active,
                  "judged=%s STATUS_CHANGED事件=%d %r "
                  "(期望剛好1筆，key=K3，from={'flag':False}→to={'flag':True})"
                  % (judged, len(sc_events), sc_events))


@check("detect_delistings.group_integrity_gate", mutate_target="detect_delistings",
       mutate=mut_dd_group_integrity_gate)
def chk_dd_group_integrity_gate(is_mutant):
    """第二階段新增（docs/detect-phase2-report.md §3.4）：沒有 total/count 自報欄位的
    子集合改用 range_check（依實測 min/max 各加 10% 邊界訂出合理區間），原始筆數落在
    區間外要視為不完整、跳過判定。這是 completeness_group() 的 range_check 分支，是
    全新程式碼——第一階段 detect_delistings.integrity_gate_skips 測的是 total_match
    分支（completeness()，x402_bazaar 專用），兩者是不同函式、不同程式碼路徑，
    彼此不能互相涵蓋。"""
    sandbox = new_sandbox("dd_grange_mut" if is_mutant else "dd_grange")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_group_integrity_gate(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg = {"path": ("items",), "shape": "list", "key_field": "id", "desc_field": "name",
            "completeness": "range_check", "range": (90, 110),
            "status_fields": (), "breaker_pct": 50.0, "abs_floor": 5}
    day1 = [gs_item("id", "R%d" % i, "name", "r%d" % i) for i in range(100)]  # 100，落在[90,110]內
    day2 = [gs_item("id", "R%d" % i, "name", "r%d" % i) for i in range(50)]   # 50，跌破下界90（模擬分頁只抓一半）
    r = mod.compare_group("selftest_range_src", "grp", gcfg, {"items": day1}, {"items": day2})
    judged = mod.judge(r, gcfg)
    guard_active = (judged == "GATE_FAIL")
    return Result(guard_active,
                  "n_old=100 n_new=50（合理區間[90,110]）；judged=%s (期望 GATE_FAIL，50 跌破下界)" % judged)


@check("detect_delistings.group_breaker_threshold", mutate_target="detect_delistings",
       mutate=mut_dd_group_breaker)
def chk_dd_group_breaker(is_mutant):
    """第二階段新增（docs/detect-phase2-report.md §3.5）：compare_group() 的熔斷公式
    breaker = removed_count > max(abs_floor, breaker_pct/100 × 前日筆數)，是全新的
    threshold_count 計算路徑——第一階段 detect_delistings.breaker_threshold 測的是
    compare_pair() 的 removed_rate 版本（百分比直接比較，沒有 threshold_count 這個
    中間值），兩者程式碼互相獨立，見 docs/selftest-fix-report.md 錨點稽核章節。"""
    sandbox = new_sandbox("dd_gbreak_mut" if is_mutant else "dd_gbreak")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_group_breaker(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg = {"path": ("items",), "shape": "list", "key_field": "id", "desc_field": "name",
            "completeness": "total_match", "total_fields": ("count",),
            "status_fields": (), "breaker_pct": 5.0, "abs_floor": 5}
    day1 = [gs_item("id", "K%d" % i, "name", "k%d" % i) for i in range(100)]
    day2 = [gs_item("id", "K%d" % i, "name", "k%d" % i) for i in range(70)]  # 30% 移除，遠超 5% 門檻
    r = mod.compare_group("selftest_gbreak_src", "grp", gcfg,
                           {"items": day1, "count": len(day1)}, {"items": day2, "count": len(day2)})
    judged = mod.judge(r, gcfg)
    guard_active = (judged == "BREAKER")
    return Result(guard_active,
                  "removed=%d/100（門檻 max(5, 5%%×100)=%.1f）；judged=%s (期望 BREAKER)"
                  % (len(r["removed_keys"]), r["threshold_count"], judged))


@check("detect_delistings.group_isolation", mutate_target="detect_delistings",
       mutate=mut_dd_group_isolation)
def chk_dd_group_isolation(is_mutant):
    """第二階段新增（docs/detect-phase2-report.md §5.2「情境2」）：process_group_source_pair()
    逐子集合各自判定 gate_ok／breaker，某子集合完整性失敗或熔斷，不能連帶讓同一來源的
    其他子集合也不判定（「不能互相污染」，SPEC-selftest-fix.md 任務 3）。用 3 個子集合
    （bad_gate、bad_breaker 刻意排在 good 之前，確保「污染」型 mutant 若被重新引入會
    影響到最後處理的 good）驗證：即使前兩個子集合都判定失敗，good 仍必須是 NORMAL
    並正常寫入事件。"""
    sandbox = new_sandbox("dd_iso_mut" if is_mutant else "dd_iso")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_group_isolation(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg_good = {"path": ("good",), "shape": "list", "key_field": "id", "desc_field": "name",
                 "completeness": "total_match", "total_fields": ("good_count",),
                 "status_fields": (), "breaker_pct": 50.0, "abs_floor": 5}
    gcfg_bad_gate = {"path": ("bad_gate",), "shape": "list", "key_field": "id", "desc_field": "name",
                      "completeness": "total_match", "total_fields": ("bad_gate_count",),
                      "status_fields": (), "breaker_pct": 50.0, "abs_floor": 5}
    gcfg_bad_breaker = {"path": ("bad_breaker",), "shape": "list", "key_field": "id", "desc_field": "name",
                         "completeness": "total_match", "total_fields": ("bad_breaker_count",),
                         "status_fields": (), "breaker_pct": 5.0, "abs_floor": 5}
    scfg = {"label": "selftest 隔離測試", "groups": {  # 順序見上方 docstring：bad 系列必須先於 good
        "bad_gate": gcfg_bad_gate, "bad_breaker": gcfg_bad_breaker, "good": gcfg_good}}
    good_d1 = [gs_item("id", "G%d" % i, "name", "g%d" % i) for i in range(20)]
    good_d2 = [gs_item("id", "G%d" % i, "name", "g%d" % i) for i in range(19)]  # 5% 移除，低於 50% 門檻
    bg_d1 = [gs_item("id", "BG%d" % i, "name", "bg%d" % i) for i in range(10)]
    bg_d2 = [gs_item("id", "BG%d" % i, "name", "bg%d" % i) for i in range(9)]
    bb_d1 = [gs_item("id", "BB%d" % i, "name", "bb%d" % i) for i in range(100)]
    bb_d2 = [gs_item("id", "BB%d" % i, "name", "bb%d" % i) for i in range(60)]  # 40% 移除，超過 5% 門檻
    data1 = {"good": good_d1, "good_count": len(good_d1),
             "bad_gate": bg_d1, "bad_gate_count": len(bg_d1),
             "bad_breaker": bb_d1, "bad_breaker_count": len(bb_d1)}
    data2 = {"good": good_d2, "good_count": len(good_d2),
             "bad_gate": bg_d2, "bad_gate_count": len(bg_d1),  # count 刻意不同步 -> GATE_FAIL
             "bad_breaker": bb_d2, "bad_breaker_count": len(bb_d2)}
    f1 = write_gz_json(os.path.join(sandbox, "track-crypto/data/selftest_iso/2030-07-01.json.gz"), gs_snapshot(data1))
    f2 = write_gz_json(os.path.join(sandbox, "track-crypto/data/selftest_iso/2030-07-02.json.gz"), gs_snapshot(data2))
    seen, last_delisted_by_group = set(), {}
    group_results, fresh, entries, alert_written = mod.process_group_source_pair(
        "selftest_iso", scfg, f1, f2, seen, last_delisted_by_group)
    judged_map = {g: gr["judged"] for g, gr in group_results.items()}
    good_events = [e for e in fresh if e["group"] == "good"]
    guard_active = (judged_map.get("bad_gate") == "GATE_FAIL" and judged_map.get("bad_breaker") == "BREAKER"
                    and judged_map.get("good") == "NORMAL" and len(good_events) == 1)
    return Result(guard_active,
                  "judged=%r good事件數=%d (期望 bad_gate=GATE_FAIL、bad_breaker=BREAKER、"
                  "good=NORMAL 且仍有 1 筆事件，證明前兩個子集合失敗不會污染 good)"
                  % (judged_map, len(good_events)))


@check("detect_delistings.payment_protocol_repos_majority_breaker", mutate_target="detect_delistings",
       mutate=mut_dd_ppr_breaker)
def chk_dd_ppr_breaker(is_mutant):
    """第二階段新增（docs/detect-phase2-report.md §2.8、§5.4）：payment_protocol_repos
    只有 3 筆（人工維護清單），套用共通熔斷公式 max(abs_floor=5, 1.0%×3≈0.03)=5 會讓
    熔斷永遠不可能觸發（最多只有 3 筆可移除）。GROUP_SOURCES 對這個來源另訂
    breaker_pct=60.0／abs_floor=1 的「過半即熔斷」專屬值（SPEC-selftest-fix.md 任務 3）。
    本檢查直接讀真實 GROUP_SOURCES["payment_protocol_repos"] 設定（不是自建合成
    config），驗證負控制組（消失1/3應為NORMAL）與正控制組（消失2/3應為BREAKER）都正確；
    mutant 版本把這兩個數字還原成共通門檻預設值後，正控制組會錯誤地判成 NORMAL，
    證明這組專屬設定值確實必要，不是可有可無的保守設計。"""
    sandbox = new_sandbox("dd_ppr_mut" if is_mutant else "dd_ppr")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_ppr_breaker(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg = mod.GROUP_SOURCES["payment_protocol_repos"]["groups"]["_repos"]

    def repo(rid, name):
        return gs_item("id", rid, "full_name", name, archived=False)

    day1 = [repo(1, "x402-foundation/x402"), repo(2, "google-agentic-commerce/AP2"), repo(3, "lightninglabs/L402")]
    day2_minor = [repo(1, "x402-foundation/x402"), repo(2, "google-agentic-commerce/AP2")]  # 消失1筆(1/3)
    day2_major = [repo(1, "x402-foundation/x402")]  # 消失2筆(2/3，過半)
    data1 = {"repos": day1, "count": len(day1), "errors": {}}
    data2_minor = {"repos": day2_minor, "count": len(day2_minor), "errors": {}}
    data2_major = {"repos": day2_major, "count": len(day2_major), "errors": {}}
    r_minor = mod.compare_group("payment_protocol_repos", "_repos", gcfg, data1, data2_minor)
    judged_minor = mod.judge(r_minor, gcfg)
    r_major = mod.compare_group("payment_protocol_repos", "_repos", gcfg, data1, data2_major)
    judged_major = mod.judge(r_major, gcfg)
    guard_active = (judged_minor == "NORMAL" and judged_major == "BREAKER")
    return Result(guard_active,
                  "breaker_pct=%.1f abs_floor=%d；消失1/3judged=%s(期望NORMAL) 消失2/3judged=%s(期望BREAKER)"
                  % (gcfg["breaker_pct"], gcfg["abs_floor"], judged_minor, judged_major))


@check("detect_delistings.group_reappeared_detection", mutate_target="detect_delistings",
       mutate=mut_dd_group_reappeared)
def chk_dd_group_reappeared(is_mutant):
    """覆蓋缺口補齊（SPEC-selftest-gap.md，selftest-fix 收尾§9 自陳事項1／
    docs/selftest-fix-report.md §3.5）：build_group_events()（第二階段多子集合版本）
    的 REAPPEARED 判定，先前只有 process_pair()（單一清單路徑，對應
    detect_delistings.reappeared_detection）有專屬檢查——第二階段主要的多子集合
    資料路徑（cex_currency_status／cex_symbols_ext／openrouter_models 等 8 個來源）
    反而沒被測到。比照 chk_dd_reappeared 的 day1->day2->day3 手法，改用
    compare_group()／judge()／build_group_events() 三個 group 路徑函式直接測
    （不經 process_group_source_pair() 的檔案讀寫，比照 chk_dd_status_changed 的
    函式層級測試風格），驗證「消失後又出現」在 group 路徑一樣會補寫 REAPPEARED 事件，
    且 from 欄位正確記錄上一次消失的日期。"""
    sandbox = new_sandbox("dd_greappear_mut" if is_mutant else "dd_greappear")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_group_reappeared(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg = {"path": ("items",), "shape": "list", "key_field": "key", "desc_field": "name",
            "completeness": "total_match", "total_fields": ("count",),
            "status_fields": (), "breaker_pct": 50.0, "abs_floor": 5}
    day1 = [gs_item("key", "K%d" % i, "name", "n%d" % i) for i in range(10)]  # K0..K9
    day2 = [gs_item("key", "K%d" % i, "name", "n%d" % i) for i in range(9)]   # K9 消失
    day3 = [gs_item("key", "K%d" % i, "name", "n%d" % i) for i in range(10)]  # K9 又出現
    data1 = {"items": day1, "count": len(day1)}
    data2 = {"items": day2, "count": len(day2)}
    data3 = {"items": day3, "count": len(day3)}
    last_delisted = {}
    r12 = mod.compare_group("selftest_greappear_src", "grp", gcfg, data1, data2)
    judged12 = mod.judge(r12, gcfg)
    mod.build_group_events("selftest_greappear_src", "grp", gcfg, r12, judged12,
                            "2030-06-02", last_delisted)
    r23 = mod.compare_group("selftest_greappear_src", "grp", gcfg, data2, data3)
    judged23 = mod.judge(r23, gcfg)
    events23, _ = mod.build_group_events("selftest_greappear_src", "grp", gcfg, r23, judged23,
                                          "2030-06-03", last_delisted)
    reappeared = [e for e in events23 if e["event"] == "REAPPEARED" and e["key"] == "K9"]
    guard_active = (judged12 == "NORMAL" and judged23 == "NORMAL" and len(reappeared) == 1
                    and reappeared[0]["from"] == "2030-06-02")
    return Result(guard_active,
                  "day1->day2: K9 DELISTED；day2->day3: K9 重新出現；REAPPEARED 事件數=%d %r "
                  "(期望剛好 1 筆，from=2030-06-02；測 build_group_events() 而非 process_pair())"
                  % (len(reappeared), reappeared))


@check("detect_delistings.payment_protocol_repos_require_empty", mutate_target="detect_delistings",
       mutate=mut_dd_ppr_require_empty)
def chk_dd_ppr_require_empty(is_mutant):
    """覆蓋缺口補齊（SPEC-selftest-gap.md，selftest-fix 收尾§9 自陳事項3／
    docs/detect-phase2-report.md §2.8／§5.5「情境6」）：completeness_group() 的
    require_empty 機制——payment_protocol_repos adapter 有 MIN_SUCCESS=2（3 選 2
    即成功），count==len(repos) 單獨不足以保證完整（可能只是 2/3 成功但仍自我一致），
    GROUP_SOURCES 對這個來源額外設定 require_empty=("errors",)，要求 errors 欄位
    必須為空字典才算完整性通過。本檢查直接讀真實
    GROUP_SOURCES["payment_protocol_repos"] 設定（比照 chk_dd_ppr_breaker 的既有
    慣例），直接呼叫 completeness_group() 做函式層級測試（比照
    docs/detect-phase2-report.md §5.5「情境6」的一次性驗證手法，本次轉為永久回歸
    檢查）：errors 非空時必須 ok=False（即使 count 與 len(repos) 相符），errors 為空
    時必須 ok=True（正負對照組都要成立，確保不是過嚴、誤傷正常情況）。"""
    sandbox = new_sandbox("dd_ppr_reqempty_mut" if is_mutant else "dd_ppr_reqempty")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_ppr_require_empty(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg = mod.GROUP_SOURCES["payment_protocol_repos"]["groups"]["_repos"]

    def repo(rid, name):
        return gs_item("id", rid, "full_name", name, archived=False)

    repos2 = [repo(1, "x402-foundation/x402"), repo(2, "google-agentic-commerce/AP2")]  # 3選2成功情境
    data_with_errors = {"repos": repos2, "count": len(repos2),
                         "errors": {"lightninglabs/L402": "HTTP 503"}}
    data_without_errors = {"repos": repos2, "count": len(repos2), "errors": {}}
    ok_bad, n_bad, reason_bad = mod.completeness_group(data_with_errors, gcfg)
    ok_good, n_good, reason_good = mod.completeness_group(data_without_errors, gcfg)
    guard_active = (ok_bad is False and ok_good is True)
    return Result(guard_active,
                  "count(%d)==len(repos)(%d) 兩者相符；errors非空時ok=%s reason=%r(期望False) "
                  "errors為空時ok=%s(期望True)"
                  % (n_bad, len(repos2), ok_bad, reason_bad, ok_good))


# ==========================================================================
# scripts/cex_events.py — 3 條不變量 + 1 項 real-replay
# ==========================================================================

ALL_EXCHANGES = list(CEX_SPEC_PATH.keys())


def _install_ce(sandbox, text):
    return install_text(sandbox, "scripts/cex_events.py", text)


def _run_ce(sandbox, script_path):
    rc, out, err = run_py(script_path, cwd=sandbox)
    events = read_jsonl(os.path.join(sandbox, "track-crypto/data/cex_events/events.jsonl"))
    gate_skips = read_jsonl(os.path.join(sandbox, "track-crypto/data/cex_events/gate_skips.jsonl"))
    return rc, out, err, events, gate_skips


@check("cex_events.daily_last_snapshot_only", mutate_target="cex_events", mutate=mut_ce_daily_dedup)
def chk_ce_daily_dedup(is_mutant):
    """比照 docs/cex-events-audit.md §6.2 Test B：同日暫時消失又恢復（flicker）不應產生事件；
    真實下架仍應被偵測到。"""
    sandbox = new_sandbox("ce_dedup_mut" if is_mutant else "ce_dedup")
    text = read_source("cex_events")
    if is_mutant:
        text = mut_ce_daily_dedup(text)
    script_path = _install_ce(sandbox, text)
    stable = {ex: [("STABLE1", "ok")] for ex in ALL_EXCHANGES if ex != "bybit"}

    def bybit(flicker, realdelist):
        pairs = [("STABLE1", "ok")]
        if flicker:
            pairs.append(("FLICKERUSDT", "Trading"))
        if realdelist:
            pairs.append(("REALDELISTUSDT", "Trading"))
        return pairs

    day1 = cex_snapshot(dict(stable, bybit=bybit(True, True)))
    day2_early = cex_snapshot(dict(stable, bybit=bybit(False, True)))   # FLICKER 暫時消失
    day2_final = cex_snapshot(dict(stable, bybit=bybit(True, True)))    # 當日稍後恢復
    day3 = cex_snapshot(dict(stable, bybit=bybit(True, False)))         # REALDELIST 真正消失
    write_gz_json(os.path.join(sandbox, "track-crypto/data/cex_symbols/2030-05-01.json.gz"), day1)
    write_gz_json(os.path.join(sandbox, "track-crypto/data/cex_symbols/2030-05-02.json.gz"), day2_early)
    write_gz_json(os.path.join(sandbox, "track-crypto/data/cex_symbols/2030-05-02T120000.json.gz"), day2_final)
    write_gz_json(os.path.join(sandbox, "track-crypto/data/cex_symbols/2030-05-03.json.gz"), day3)
    rc, out, err, events, gate_skips = _run_ce(sandbox, script_path)
    flicker_events = [e for e in events if e["symbol"] == "FLICKERUSDT"]
    real_delisted = [e for e in events if e["symbol"] == "REALDELISTUSDT" and e["event"] == "DELISTED"]
    guard_active = (rc == 0) and (len(flicker_events) == 0) and (len(real_delisted) == 1)
    return Result(guard_active,
                  "rc=%d flicker偽事件數=%d 真下架事件數=%d (期望 0 / 1)"
                  % (rc, len(flicker_events), len(real_delisted)))


@check("cex_events.daily_last_snapshot_only.real_replay")
def chk_ce_daily_dedup_real(is_mutant):
    """real-replay：VPS 正式 track-crypto/data/cex_symbols 目前全部既有快照
    （唯一同日重複＝08-28，比照 docs/cex-events-audit.md §1.2/§6.1 Test A），
    全量重算應與正式已提交的 events.jsonl 核心欄位集合完全相同（未破壞任何既有事件）。
    本項不做破壞驗證（沒有 mutate）：真實 08-28 同日重複是否會因為停用去重而製造出
    可觀測差異，取決於當時兩份快照本身內容是否剛好有別，無法保證每次重跑都踩得到，
    真正保證「破壞會被抓到」的是上面的合成資料版本（cex_events.daily_last_snapshot_only）。"""
    if is_mutant:
        return Result(True, "本項無破壞驗證，見 docstring 說明（避免依賴不保證存在的真實資料巧合）")
    sandbox = new_sandbox("ce_dedup_real")
    script_path = _install_ce(sandbox, read_source("cex_events"))
    real_dir = os.path.join(SOURCE_REPO, "track-crypto/data/cex_symbols")
    n_copied = 0
    if os.path.isdir(real_dir):
        for fn in sorted(os.listdir(real_dir)):
            if fn.endswith(".json.gz"):
                install_binary_copy(os.path.join(real_dir, fn), sandbox, "track-crypto/data/cex_symbols/" + fn)
                n_copied += 1
    rc, out, err, events, gate_skips = _run_ce(sandbox, script_path)
    real_events_path = os.path.join(SOURCE_REPO, "track-crypto/data/cex_events/events.jsonl")
    real_events = read_jsonl(real_events_path)
    core = lambda e: (e["date"], e["exchange"], e["symbol"], e["event"])
    fresh_set = set(core(e) for e in events)
    real_set = set(core(e) for e in real_events)
    missing = real_set - fresh_set
    extra = fresh_set - real_set
    guard_active = (rc == 0) and (n_copied >= 2) and not missing and not extra
    return Result(guard_active,
                  "real-replay：複製 %d 份正式快照重算；核心欄位差集 real-fresh=%d fresh-real=%d "
                  "(期望兩者皆 0，即與正式 events.jsonl %d 筆完全一致)"
                  % (n_copied, len(missing), len(extra), len(real_events)))


@check("cex_events.exchange_level_gate", mutate_target="cex_events", mutate=mut_ce_exchange_gate)
def chk_ce_exchange_gate(is_mutant):
    """比照 docs/cex-events-audit.md §6.3 Test C：okx（回報 errors 但仍殘留局部資料）、
    kucoin（exchanges 裡完全沒有這個 key，errors 也沒記到）兩種異常態樣同時發生，
    完整性守門應逐交易所獨立跳過判定，且不影響同一時間 bybit 的真實下架被偵測到。"""
    sandbox = new_sandbox("ce_gate_mut" if is_mutant else "ce_gate")
    text = read_source("cex_events")
    if is_mutant:
        text = mut_ce_exchange_gate(text)
    script_path = _install_ce(sandbox, text)
    stable = {ex: [("STABLE1", "ok")] for ex in ALL_EXCHANGES if ex not in ("bybit", "okx", "kucoin")}
    okx_full = [("OKXB-USDT", "live"), ("OKXC-USDT", "live"), ("OKXD-USDT", "live"),
                ("OKXE-USDT", "live"), ("OKXF-USDT", "live")]
    day1 = cex_snapshot(dict(stable, bybit=[("RGENUINEUSDT", "Trading"), ("STABLE1", "ok")],
                              okx=okx_full, kucoin=[("KC1", "ok"), ("KC2", "ok"), ("KC3", "ok")]))
    day2 = cex_snapshot(dict(stable, bybit=[("STABLE1", "ok")],   # RGENUINEUSDT 真的下架
                              okx=[("OKXB-USDT", "live")]),        # 只殘留 1 檔，且下面記錄 errors
                         errors={"okx": "timeout (selftest synthetic)"})
    # kucoin 完全沒放進 day2 的 exchange_pairs -> exchanges 字典裡完全沒有這個 key（非 errors 內）
    day3 = cex_snapshot(dict(stable, bybit=[("STABLE1", "ok")], okx=okx_full,
                              kucoin=[("KC1", "ok"), ("KC2", "ok"), ("KC3", "ok")]))
    write_gz_json(os.path.join(sandbox, "track-crypto/data/cex_symbols/2030-06-01.json.gz"), day1)
    write_gz_json(os.path.join(sandbox, "track-crypto/data/cex_symbols/2030-06-02.json.gz"), day2)
    write_gz_json(os.path.join(sandbox, "track-crypto/data/cex_symbols/2030-06-03.json.gz"), day3)
    rc, out, err, events, gate_skips = _run_ce(sandbox, script_path)
    if rc != 0:
        return Result(False, "子行程非 0 結束碼（rc=%d），視為守門失效：%s" % (rc, err.strip()[-300:]))
    bybit_delisted = [e for e in events if e["exchange"] == "bybit" and e["event"] == "DELISTED"]
    okx_spurious = [e for e in events if e["exchange"] == "okx"]
    kucoin_spurious = [e for e in events if e["exchange"] == "kucoin"]
    guard_active = (len(bybit_delisted) == 1 and bybit_delisted[0]["symbol"] == "RGENUINEUSDT"
                    and len(okx_spurious) == 0 and len(kucoin_spurious) == 0 and len(gate_skips) >= 4)
    return Result(guard_active,
                  "bybit真下架事件=%d okx偽事件=%d kucoin偽事件=%d gate_skips筆數=%d "
                  "(期望 1 / 0 / 0 / >=4)" % (len(bybit_delisted), len(okx_spurious),
                                              len(kucoin_spurious), len(gate_skips)))


@check("cex_events.anomalous_scale_annotation", mutate_target="cex_events", mutate=mut_ce_anomaly)
def chk_ce_anomaly(is_mutant):
    sandbox = new_sandbox("ce_anom_mut" if is_mutant else "ce_anom")
    text = read_source("cex_events")
    if is_mutant:
        text = mut_ce_anomaly(text)
    script_path = _install_ce(sandbox, text)
    stable = {ex: [("STABLE1", "ok")] for ex in ALL_EXCHANGES if ex not in ("mexc", "bybit")}
    mexc_old = [("M%d" % i, "1") for i in range(200)]
    mexc_new = [("M%d" % i, "1") for i in range(150)]           # 50/200=25% 移除，遠超門檻 max(10,2)
    bybit_old = [("B%d" % i, "Trading") for i in range(50)]
    bybit_new = [("B%d" % i, "Trading") for i in range(49)]     # 1/50=2% 移除，低於門檻 max(10,0.5)=10
    old = cex_snapshot(dict(stable, mexc=mexc_old, bybit=bybit_old))
    new = cex_snapshot(dict(stable, mexc=mexc_new, bybit=bybit_new))
    write_gz_json(os.path.join(sandbox, "track-crypto/data/cex_symbols/2030-07-01.json.gz"), old)
    write_gz_json(os.path.join(sandbox, "track-crypto/data/cex_symbols/2030-07-02.json.gz"), new)
    rc, out, err, events, gate_skips = _run_ce(sandbox, script_path)
    mexc_delisted = [e for e in events if e["exchange"] == "mexc" and e["event"] == "DELISTED"]
    mexc_annotated = [e for e in mexc_delisted if e.get("note") == "anomalous_scale"]
    bybit_delisted = [e for e in events if e["exchange"] == "bybit" and e["event"] == "DELISTED"]
    bybit_annotated = [e for e in bybit_delisted if e.get("note") == "anomalous_scale"]
    guard_active = (rc == 0 and len(mexc_delisted) == 50 and len(mexc_annotated) == 50
                    and len(bybit_delisted) == 1 and len(bybit_annotated) == 0)
    return Result(guard_active,
                  "mexc DELISTED=%d(已加註=%d) bybit DELISTED=%d(已加註=%d) "
                  "(期望 mexc 50/50 全加註；bybit 1/0 完全不加註，因低於門檻)"
                  % (len(mexc_delisted), len(mexc_annotated), len(bybit_delisted), len(bybit_annotated)))


# ==========================================================================
# scripts/healthcheck.py — 2 條不變量
# ==========================================================================

@check("healthcheck.truncation_streak_n2", mutate_target="healthcheck", mutate=mut_hc_streak)
def chk_hc_streak(is_mutant):
    sandbox = new_sandbox("hc_streak_mut" if is_mutant else "hc_streak")
    text = read_source("healthcheck")
    if is_mutant:
        text = mut_hc_streak(text)
    script_path = install_text(sandbox, "scripts/healthcheck.py", text)
    dm2, dm1, d0 = "2030-07-01", "2030-07-02", "2030-07-03"
    m_dm2 = {"date": dm2, "channels": {
        "synth_streak2": {"ok": True, "n": 100, "secs": 8, "truncated": False},
        "synth_streak1": {"ok": True, "n": 100, "secs": 8, "truncated": False}}}
    m_dm1 = {"date": dm1, "channels": {
        "synth_streak2": {"ok": True, "n": 30, "secs": 10, "truncated": True, "items_fetched": 30},
        "synth_streak1": {"ok": True, "n": 98, "secs": 8, "truncated": False}}}
    m_d0 = {"date": d0, "channels": {
        "synth_streak2": {"ok": True, "n": 25, "secs": 12, "truncated": True, "items_fetched": 25},
        "synth_streak1": {"ok": True, "n": 20, "secs": 12, "truncated": True, "items_fetched": 20}}}
    for d, m in [(dm2, m_dm2), (dm1, m_dm1), (d0, m_d0)]:
        install_text(sandbox, "track-gov/data/_manifest/%s.json" % d, json.dumps(m))
    with temp_env(HEALTHCHECK_TODAY=d0, HEALTHCHECK_NOW=d0 + "T12:00:00+00:00"):
        mod = load_module(script_path)
        issues = []
        mod.check_truncation_streak("track-gov", issues)
    names = [a for a, b in issues]
    guard_active = ("track-gov/synth_streak2" in names) and ("track-gov/synth_streak1" not in names)
    return Result(guard_active,
                  "連續2天截斷來源 issues=%r (期望含 synth_streak2，不含僅1天的 synth_streak1)" % (names,))


@check("healthcheck.schedule_grace_period", mutate_target="healthcheck", mutate=mut_hc_grace)
def chk_hc_grace(is_mutant):
    sandbox = new_sandbox("hc_grace_mut" if is_mutant else "hc_grace")
    text = read_source("healthcheck")
    if is_mutant:
        text = mut_hc_grace(text)
    script_path = install_text(sandbox, "scripts/healthcheck.py", text)
    today = "2030-07-10"
    # 完全不建立 track-gov/data/_manifest/2030-07-10.json，模擬「今日排程尚未產生 manifest」。
    before_utc = today + "T02:00:00+00:00"   # 台北 10:00，track-gov 預期完成時間 11:15 之前
    after_utc = today + "T04:30:00+00:00"    # 台北 12:30，已過 11:15
    with temp_env(HEALTHCHECK_TODAY=today, HEALTHCHECK_NOW=before_utc):
        mod_b = load_module(script_path)
        issues_b, pending_b = [], []
        mod_b.check_manifest("track-gov", issues_b, pending_b)
    with temp_env(HEALTHCHECK_TODAY=today, HEALTHCHECK_NOW=after_utc):
        mod_a = load_module(script_path)
        issues_a, pending_a = [], []
        mod_a.check_manifest("track-gov", issues_a, pending_a)
    guard_active = (len(issues_b) == 0 and len(pending_b) == 1
                    and len(issues_a) == 1 and len(pending_a) == 0)
    return Result(guard_active,
                  "寬限前 issues=%d/pending=%d；寬限後 issues=%d/pending=%d (期望 0/1 -> 1/0)"
                  % (len(issues_b), len(pending_b), len(issues_a), len(pending_a)))


# ==========================================================================
# scripts/daily_report.py — 2 條不變量
# ==========================================================================

@check("daily_report.all_sources_listed", mutate_target="daily_report", mutate=mut_dr_all_listed)
def chk_dr_all_listed(is_mutant):
    sandbox = new_sandbox("dr_listed_mut" if is_mutant else "dr_listed")
    dr_text = read_source("daily_report")
    if is_mutant:
        dr_text = mut_dr_all_listed(dr_text)
    install_text(sandbox, "scripts/healthcheck.py", read_source("healthcheck"))
    dr_path = install_text(sandbox, "scripts/daily_report.py", dr_text)
    fake_sources = [
        ("track-crypto", "synthA", "Synthetic A"), ("track-crypto", "synthB", "Synthetic B"),
        ("track-crypto", "synthC", "Synthetic C"),
        ("track-gov", "synthD", "Synthetic D"), ("track-gov", "synthE", "Synthetic E"),
    ]
    for track, key, desc in fake_sources:
        install_fake_adapter(sandbox, track, key, desc)
    today, yday = "2030-08-02", "2030-08-01"
    # 刻意只給 4/5 個來源當日 manifest 資料；synthE 完全沒有任何 manifest 紀錄
    # （模擬 daily_report.py 檔頭 docstring 描述的舊 bug 情境：adapter 已部署但 manifest 還沒提到）。
    crypto_manifest = {"date": today, "sources": {
        "synthA": {"ok": True, "bytes": 100, "secs": 1.0, "parser_version": 1, "attempts": 1},
        "synthB": {"ok": True, "bytes": 200, "secs": 1.0, "parser_version": 1, "attempts": 1},
        "synthC": {"ok": False, "bytes": 0, "secs": 1.0, "parser_version": 1, "attempts": 1, "error": "boom"},
    }}
    gov_manifest = {"date": today, "channels": {
        "synthD": {"ok": True, "n": 10, "bytes": 300, "secs": 1.0, "attempts": 1, "truncated": False},
    }}
    install_text(sandbox, "track-crypto/data/_manifest/%s.json" % today, json.dumps(crypto_manifest))
    install_text(sandbox, "track-gov/data/_manifest/%s.json" % today, json.dumps(gov_manifest))
    mod = load_module(dr_path)
    rows, anomaly_count = mod.build_source_table(today, yday)
    active_keys = sorted(k for _, k in mod.ACTIVE)
    row_keys = sorted(r["來源"] for r in rows)
    guard_active = (len(mod.ACTIVE) == 5 and len(rows) == 5 and row_keys == active_keys
                    and "synthE" in row_keys)
    return Result(guard_active,
                  "ACTIVE=%d rows=%d row_keys=%r (期望 5/5，且 synthE 即使完全沒有 manifest 資料也仍列出)"
                  % (len(mod.ACTIVE), len(rows), row_keys))


@check("daily_report.anomaly_count_matches_alert", mutate_target="daily_report", mutate=mut_dr_alert_consistency)
def chk_dr_alert_consistency(is_mutant):
    sandbox = new_sandbox("dr_alert_mut" if is_mutant else "dr_alert")
    dr_text = read_source("daily_report")
    if is_mutant:
        dr_text = mut_dr_alert_consistency(dr_text)
    install_text(sandbox, "scripts/healthcheck.py", read_source("healthcheck"))
    dr_path = install_text(sandbox, "scripts/daily_report.py", dr_text)
    hc_path = os.path.join(sandbox, "scripts/healthcheck.py")
    fake_sources = [("track-crypto", "synthA", "Synthetic A"), ("track-crypto", "synthB", "Synthetic B"),
                    ("track-gov", "synthC", "Synthetic C")]
    for track, key, desc in fake_sources:
        install_fake_adapter(sandbox, track, key, desc)
    today = "2030-08-12"
    crypto_manifest = {"date": today, "sources": {
        "synthA": {"ok": False, "bytes": 0, "secs": 1.0, "parser_version": 1, "attempts": 3, "error": "boom-A"},
        "synthB": {"ok": False, "bytes": 0, "secs": 1.0, "parser_version": 1, "attempts": 3, "error": "boom-B"},
    }}
    gov_manifest = {"date": today, "channels": {
        "synthC": {"ok": True, "n": 10, "bytes": 500, "secs": 1.0, "attempts": 1, "truncated": False},
    }}
    install_text(sandbox, "track-crypto/data/_manifest/%s.json" % today, json.dumps(crypto_manifest))
    install_text(sandbox, "track-gov/data/_manifest/%s.json" % today, json.dumps(gov_manifest))
    env = {"HEALTHCHECK_TODAY": today, "HEALTHCHECK_NOW": today + "T12:00:00+00:00"}
    rc_hc, out_hc, err_hc = run_py(hc_path, cwd=sandbox, extra_env=env)
    rc_dr, out_dr, err_dr = run_py(dr_path, cwd=sandbox, extra_env=env)
    alert_path = os.path.join(sandbox, "ALERT.md")
    report_path = os.path.join(sandbox, "REPORT.md")
    alert_rows = 0
    if os.path.exists(alert_path):
        with open(alert_path, encoding="utf-8") as f:
            alert_rows = sum(1 for line in f if line.startswith("| `"))
    report_n = None
    if os.path.exists(report_path):
        with open(report_path, encoding="utf-8") as f:
            report_text = f.read()
        m = re.search(r"有\s*(\d+)\s*項異常", report_text)
        if m:
            report_n = int(m.group(1))
        elif "一切正常" in report_text:
            report_n = 0
    guard_active = (rc_hc == 0 and rc_dr == 0 and report_n is not None
                    and report_n == alert_rows and alert_rows >= 2)
    return Result(guard_active,
                  "rc_hc=%d rc_dr=%d ALERT.md異常列數=%d REPORT.md解析異常數=%r (期望相等且 >=2)"
                  % (rc_hc, rc_dr, alert_rows, report_n))


# ==========================================================================
# 執行器
# ==========================================================================

def run_all(filter_substr=None):
    t0 = time.time()
    os.makedirs(WORKDIR_ROOT, exist_ok=True)
    results = []
    any_fail = False
    for entry in CHECKS:
        name = entry["name"]
        if filter_substr and filter_substr not in name:
            continue
        try:
            res_normal = entry["fn"](False)
        except Exception:
            res_normal = Result(False, "EXCEPTION: " + traceback.format_exc(limit=4).replace("\n", " | "))
        results.append((name, res_normal))
        if not res_normal.passed:
            any_fail = True
        if entry["mutate"] and not SKIP_MUTANTS:
            mutant_name = name + "#mutant"
            try:
                res_mutant = entry["fn"](True)
                mutant_ok = res_normal.passed and (not res_mutant.passed)
                detail = "guard 需要「正常=PASS、破壞後=FAIL」才算本項 PASS；破壞後實測：%s" % res_mutant.detail
            except Exception:
                mutant_ok = False
                detail = "EXCEPTION during mutant run: " + traceback.format_exc(limit=4).replace("\n", " | ")
            results.append((mutant_name, Result(mutant_ok, detail)))
            if not mutant_ok:
                any_fail = True
    elapsed = time.time() - t0
    return results, any_fail, elapsed


def main(argv=None):
    parser = argparse.ArgumentParser(description="離線回歸自測（見 docs/selftest.md）")
    parser.add_argument("--filter", default=None, help="只跑名稱包含此子字串的檢查")
    parser.add_argument("--list", action="store_true", help="列出所有登記的檢查後結束（不執行）")
    args = parser.parse_args(argv)

    if args.list:
        for entry in CHECKS:
            print(entry["name"], "[有破壞驗證]" if entry["mutate"] else "[無破壞驗證]")
        return 0

    print("== scripts/selftest.py 離線回歸自測 ==")
    print("SOURCE_REPO = %s" % SOURCE_REPO)
    print("WORKDIR     = %s" % WORKDIR_ROOT)
    if SKIP_MUTANTS:
        print("SELFTEST_SKIP_MUTANTS=1：本次只跑正常檢查，略過破壞驗證")
    print("")

    results, any_fail, elapsed = run_all(args.filter)
    for name, r in results:
        detail_line = r.detail.replace("\n", " | ")
        print("%s  %-62s %s" % ("PASS" if r.passed else "FAIL", name, detail_line))

    n_pass = sum(1 for _, r in results if r.passed)
    n_fail = sum(1 for _, r in results if not r.passed)
    print("")
    print("SUMMARY total=%d pass=%d fail=%d elapsed=%.1fs workdir=%s"
          % (len(results), n_pass, n_fail, elapsed, WORKDIR_ROOT))
    if elapsed > 120:
        print("WARNING 執行時間超過 2 分鐘預算（SPEC-selftest.md 第 5 點），請檢視是否有檢查變慢")
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
