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
  SELFTEST_KEEP          設為 1 時不論全數 PASS 或有 FAIL，一律保留 WORKDIR。
                         預設行為（2026-09-08 新增）：全數 PASS 時執行結束自動
                         shutil.rmtree(WORKDIR)；有 FAIL 時本來就會保留供除錯，
                         不受這個旗標影響。這個旗標是給「PASS 也想留著手動核對
                         沙盒內容」的情境，見 docs/selftest.md「WORKDIR 自清」一節。
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
    "snap_crypto":       "track-crypto/scripts/snap_crypto.py",  # SPEC-manifest-fields.md，2026-09-03 新增
    "selftest":          "scripts/selftest.py",  # 2026-09-08 新增：WORKDIR 自清防呆的自測用（見檔案尾端）
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



def _pv_items(n, tag, words=30):
    """產生 n 筆合成 track-gov 項目，body_text 長度可控、內容依 n 決定，供
    healthcheck.parser_version_skip 系列檢查控制快照體積用（見該節說明）。
    同一 (n, tag) 組合永遠產生一模一樣的內容 → gzip 後體積穩定可重現，不會有測試間歇性失敗。"""
    filler = " ".join("filler%d" % i for i in range(words))
    return [gov_item("PV-%s-%03d" % (tag, i), "PV Title %s %d" % (tag, i),
                      "%s body-%s-%d %s" % (filler, tag, i, filler))
            for i in range(n)]

DC_CFG = {"key": "id", "title": "title", "text": "body_text", "sha": "body_sha256",
          "url": "url", "label": "Selftest Synthetic Source"}


def x402_item(resource, description, l30=5):
    """比照 track-crypto/data/x402_bazaar 快照 items[] 的欄位（見實測 schema）。"""
    return {
        "resource": resource, "description": description, "type": "http", "x402Version": 1,
        "lastUpdated": "2030-01-01T00:00:00Z", "accepts": [], "extensions": {},
        "quality": {"l30DaysTotalCalls": l30},
    }


_AUTO = object()  # x402_snapshot() 的「未指定」哨兵值（None 是合法的 reported_total 值，不能拿來當預設）


def x402_snapshot(items, total=None, reported_total=_AUTO, truncated=False, legacy=False):
    """比照 track-crypto/data/x402_bazaar 快照頂層 schema。

    2026-09-07 更新（恆真式守門修正，見 track-crypto/adapters/x402_bazaar.py 檔頭）：
    adapter PARSER_VERSION 2 起，data 除既有的 x402Version／total／items 之外，
    多了 reported_total（上游 pagination.total）與 truncated（本次分頁是否沒抓完）。

      total          ：本次抓到幾筆（adapter 自己算的 len(items)；預設＝len(items)）。
                       **注意：這個欄位不可以拿來當完整性守門的比對基準**（那就是本輪
                       修掉的恆真式），它只是給 daily_report.py／explore.py 顯示用。
      reported_total ：上游自報總數。預設沿用 total 的值（＝正常情況：上游總數與抓到的
                       筆數相符）；要測守門就明確指定一個與 len(items) 不同的值。
      truncated      ：預設 False（正常抓完）。
      legacy=True    ：產生 2026-09-07 之前的**舊快照**（data 完全沒有 reported_total／
                       truncated 兩個鍵），供 completeness() 的 legacy_range_check
                       相容分支使用。
    """
    data = {"x402Version": 1, "total": total if total is not None else len(items)}
    if not legacy:
        data["reported_total"] = data["total"] if reported_total is _AUTO else reported_total
        data["truncated"] = truncated
    data["items"] = items
    return {"_meta": {"parser_version": 1, "fetched_at": "2030-01-01T00:00:00+00:00"}, "data": data}


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


def mut_dc_rolling_window_self_reference(text):
    """Y3 修法（SPEC-y3-rolling.md）的破壞驗證專用 mutation：把 v3 補丁的 tail_start 公式
    還原回修法前『用 removed_set 自我指涉估計捲動視窗大小』的版本，證明如果這個修法哪天被
    誤還原（例如合併衝突、手滑 revert），下面兩條 rolling_window_no_self_reference 檢查
    真的抓得到——而不是抓不到就沉默。"""
    return apply_mutation(
        text,
        '        tail_start = len(list_old) - len(added) - 2  '
        '# v3 修法：不再用 removed_set 自我指涉估計捲動量（見 SPEC-y3-rolling.md）',
        '        tail_start = len(list_old) - (len(added) + len(removed_set)) - 2  '
        '# [selftest mutant] v3 self-reference fix reverted',
        "dc_rolling_window_self_reference")



def mut_dc_window_guard_disabled(text):
    """Window Guard（SPEC-window-guard.md）破壞驗證：關掉「視窗顯著變化 -> 跳過下架」這個
    分支本身，讓 compare_guarded() 在視窗顯著變化時仍然直接沿用 compare() 的原始（未受
    保護）判定結果，證明如果這個分支哪天被誤刪，下面的 window_guard_shrink 系列檢查
    真的抓得到——而不是抓不到就沉默。"""
    return apply_mutation(
        text,
        "    if window_changed_significantly(n_old, n_new):",
        "    if False:  # [selftest mutant] window-guard branch disabled",
        "dc_window_guard_disabled")


def mut_dc_window_guard_stuck(text):
    """Window Guard 破壞驗證：讓 window_changed_significantly() 恆真，模擬「視窗保護一旦
    觸發就再也不會自動恢復」的迴歸（例如誤把門檻判斷寫死成恆真），證明
    window_guard_recovers_next_day 檢查真的有在驗證『視窗穩定後下一日自動恢復』這件事，
    不是恆真檢查。"""
    return apply_mutation(
        text,
        "    return rel >= WINDOW_CHANGE_REL_THRESHOLD and abs_diff >= WINDOW_CHANGE_ABS_FLOOR",
        "    return True  # [selftest mutant] window guard stuck permanently on",
        "dc_window_guard_stuck")


def mut_dc_window_guard_and_to_or(text):
    """Window Guard 破壞驗證：把雙門檻（相對 20% 且絕對 5 筆）的 and 改成 or，模擬「絕對
    筆數下限保護被誤刪／誤改」的迴歸——小視窗來源會被 1~2 筆自然雜訊（相對變化可能輕易
    ≥20%）誤觸發跳過。證明 window_guard_threshold 檢查真的有在驗證雙門檻缺一不可，
    不是只驗證相對門檻。"""
    return apply_mutation(
        text,
        "    return rel >= WINDOW_CHANGE_REL_THRESHOLD and abs_diff >= WINDOW_CHANGE_ABS_FLOOR",
        "    return rel >= WINDOW_CHANGE_REL_THRESHOLD or abs_diff >= WINDOW_CHANGE_ABS_FLOOR"
        "  # [selftest mutant] AND weakened to OR",
        "dc_window_guard_and_to_or")


def mut_dc_window_guard_missing_data_skips(text):
    """Window Guard 破壞驗證：manifest 讀不到 n 時改成觸發跳過（而非既有設計的保守
    「不跳過」），模擬「找不到輔助欄位時反而擴大保護範圍」的迴歸——這會讓任何 manifest
    讀取失敗（不是本保護原本要處理的情境）都意外吞掉下架判定。證明
    window_guard_missing_manifest_no_skip 檢查真的有在驗證這條保守預設。"""
    return apply_mutation(
        text,
        "    if n_old is None or n_new is None or n_old <= 0:\n        return False",
        "    if n_old is None or n_new is None or n_old <= 0:\n"
        "        return True  # [selftest mutant] missing data now wrongly triggers skip",
        "dc_window_guard_missing_data_skips")


def mut_snap_gov_volatile(text):
    return apply_mutation(
        text, 'def strip_volatile(text):\n    out, skip_next_number = [], False',
        'def strip_volatile(text):\n    return text  # [selftest mutant] volatile stripping disabled\n'
        '    out, skip_next_number = [], False',
        "snap_gov_volatile")


def mut_dd_integrity_gate(text):
    """錨點更新（2026-09-07，恆真式守門修正）：completeness() 已改寫，原錨點
    `if total != n:` 不再存在。改指向新版容忍度比較式——關掉它，守門就不會再因為
    「上游自報總數與 len(items) 差太多」而擋下判定。"""
    return apply_mutation(
        text,
        '    if gap > limit:',
        '    if False:  # [selftest mutant] integrity gate disabled',
        "dd_integrity_gate")


def mut_dd_x402_tautological_gate(text):
    """重現本輪修掉的那個 bug：讓完整性守門去比對「adapter 自己算出來的數字」而不是
    上游自報總數 —— 也就是把守門變回**恆真式**（被檢查的數字＝自報的數字）。
    對應檢查 detect_delistings.x402_gate_not_tautological。"""
    return apply_mutation(
        text,
        '    reported_total = data.get(cfg["reported_total_field"])',
        '    reported_total = n  # [selftest mutant] 恆真式守門重現：自報值改成 len(items) 本身',
        "dd_x402_tautological_gate")


def mut_dd_x402_truncated_gate(text):
    """關掉 completeness() 對 data.truncated 的 fail-closed 檢查。
    對應檢查 detect_delistings.x402_gate_truncated_flag。"""
    return apply_mutation(
        text,
        '    if tr is not False:',
        '    if False:  # [selftest mutant] x402 truncated-flag gate disabled',
        "dd_x402_truncated_gate")


def mut_dd_x402_legacy_range(text):
    """關掉舊快照相容分支的區間檢查（legacy_range_check），讓任何筆數都算通過。
    對應檢查 detect_delistings.x402_gate_legacy_range。"""
    return apply_mutation(
        text,
        '        if n < lo or n > hi:',
        '        if False:  # [selftest mutant] legacy range check disabled',
        "dd_x402_legacy_range")


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


# --------------------------------------------------------------------------
# 熔斷語意統一（2026-09-07，任務 C，見本機 docs/0907-C-breaker-semantics-report.md）
# 新增的 4 支 mutation 函式，鎖住「熔斷＝標記但不否決」這條新語意的三個關鍵分支
# 與 cex_events 的統一標記欄位。
# --------------------------------------------------------------------------

def mut_dd_breaker_not_veto(text):
    """目標：process_pair() 的落地去向判定式。還原成 2026-09-07 之前的「熔斷否決整組」
    行為（只有 NORMAL 才寫事件），模擬「統一後的語意被改回去／被重構掉」的迴歸。
    這正是造成 x402_bazaar 09-06→09-07 那 1,399+387+31 筆事件永久遺失的那一行。
    錨點必須往前延伸到上一行的 breaker_release_check(source, r["d_old"], r["d_new"], r)
    ——process_group_source_pair() 內有一行**逐字相同、只是縮排多 4 個空白**的
    to_events 指派，只用縮排區分是不夠的（8 空白版本包含 4 空白版本，屬子字串命中，
    apply_mutation() 會丟 "anchor not unique"）。process_pair() 的呼叫用
    r["d_old"]／r["d_new"]，group 版用區域變數 d_old／d_new，兩者字面不會互相匹配。
    這是 docs/selftest-fix-report.md 教訓 3「錨點延伸優先於全部替換」的直接套用。"""
    return apply_mutation(
        text,
        'breaker_release_check(source, r["d_old"], r["d_new"], r)\n'
        '    to_events = (judged == "NORMAL") or (judged == "BREAKER" and release_ok)',
        'breaker_release_check(source, r["d_old"], r["d_new"], r)\n'
        '    to_events = (judged == "NORMAL")  # [selftest mutant] breaker reverted to veto',
        "dd_breaker_not_veto")


def mut_dd_breaker_fingerprint(text):
    """目標：breaker_release_check() 的分頁截斷指紋門檻判斷。關掉之後，
    「移除項目剛好是前一日清單連續尾端」這種截斷特徵也會被放行寫進 events.jsonl，
    正是 SPEC 要求評估的反面風險（真截斷時寫入大量假 DELISTED）。"""
    return apply_mutation(
        text,
        '    if cov >= BREAKER_TAIL_COVER_MAX:',
        '    if False:  # [selftest mutant] truncation fingerprint disabled',
        "dd_breaker_fingerprint")


def mut_dd_breaker_manifest_failclosed(text):
    """目標：breaker_release_check() 讀 manifest 側證時的 fail-closed 預設。
    改成「讀不到就當作全部通過」，模擬「輔助資料讀取失敗時反而放寬保護」這種
    典型迴歸（與 mut_dc_window_guard_missing_data_skips 是同一類錯誤，方向相反）。"""
    return apply_mutation(
        text,
        '    e_old = _manifest_entry(d_old, source)\n'
        '    e_new = _manifest_entry(d_new, source)',
        '    _fake = {"ok": True, "truncated": False, "parser_version": 1}\n'
        '    e_old = _manifest_entry(d_old, source) or _fake\n'
        '    e_new = _manifest_entry(d_new, source) or _fake'
        '  # [selftest mutant] manifest fail-closed defeated',
        "dd_breaker_manifest_failclosed")


def mut_ce_breaker_marks(text):
    """目標：cex_events.py 熔斷時「把統一標記套用到整組轉換每一筆事件」的那一段。
    關掉之後只剩既有的 DELISTED 兩欄位（note／removed_pct），LISTED／STATUS_CHANGED
    不再帶標記、也不再有 breaker_tripped 布林旗標——就是 2026-09-07 統一前的狀態。"""
    return apply_mutation(
        text,
        '                marks = breaker_marks(removed_pct, threshold)',
        '                marks = {}  # [selftest mutant] unified breaker marks disabled',
        "ce_breaker_marks")


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


def mut_hc_parser_version(text):
    return apply_mutation(
        text, "if any(v != v_today for v in v_prev):",
        "if False:  # [selftest mutant] parser-version window guard disabled",
        "hc_parser_version")


# --------------------------------------------------------------------------
# track-crypto/scripts/snap_crypto.py — manifest 完整性欄位（SPEC-manifest-fields.md，
# 2026-09-03 新增）的破壞驗證。兩條都只動 compute_manifest_fields() 內部，
# 不影響 collect()／write_gz()／payload 組裝等既有行為。
# --------------------------------------------------------------------------
def mut_sc_fields_complete(text):
    return apply_mutation(
        text, '"dup_keys": dup_total,\n    }',
        '"dup_keys_MUTANT_REMOVED": dup_total,  # [selftest mutant] key renamed, dup_keys now absent\n    }',
        "sc_fields_complete")


def mut_sc_truncated_default(text):
    return apply_mutation(
        text,
        'truncated, _trunc_src = _find_truncated_flag(data)\n'
        '    if truncated is None:\n        truncated = False',
        'truncated, _trunc_src = _find_truncated_flag(data)\n'
        '    if False:  # [selftest mutant] None->False fallback disabled\n        truncated = False',
        "sc_truncated_default")


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
        text, 'except Exception:\n        return None, None, None\n    return issues, pending, notices',
        'except Exception:\n        return None, None, None\n'
        '    return (issues[:-1] if issues else issues), pending, notices  '
        '# [selftest mutant] silently drop last issue',
        "dr_alert_consistency")


def mut_dr_notice_block(text):
    """SPEC-notice-and-dr.md：模擬『REPORT.md 資訊區塊接線被誤刪』的迴歸——
    render_notice_section() 收到的參數被換成永遠是空清單，資訊區塊因此永遠顯示
    「目前沒有來源處於此狀態」，即使 healthcheck.check_source() 明明印出了
    NOTICE。用來證明 daily_report.notice_surfaced_not_anomaly 真的有在檢查
    『NOTICE 有沒有被接到 REPORT.md』，不是恆真檢查。"""
    return apply_mutation(
        text, 'sections.append(render_notice_section(health_notices))',
        'sections.append(render_notice_section([]))  '
        '# [selftest mutant] notice info block silently emptied',
        "dr_notice_block")


def mut_dr_window_guard_block(text):
    """SPEC-window-guard.md：模擬『## 變動偵測區塊的視窗變動彙總提示被誤刪』的迴歸——
    window_changed_keys 永遠是空清單，即使 detect.log 裡明明有「視窗變動，不判定」的
    來源。用來證明 daily_report.window_guard_surfaced_in_change_detection_section
    真的有在檢查『視窗變動跳過有沒有被接到 REPORT.md』，不是恆真檢查。"""
    return apply_mutation(
        text,
        'window_changed_keys = [r["來源"] for r in rows if r.get("視窗變動")]',
        'window_changed_keys = []  '
        '# [selftest mutant] window-change summary line silently emptied',
        "dr_window_guard_block")


# --------------------------------------------------------------------------
# SPEC-gate-dedup.md（2026-09-04 新增）：gate_skips 冪等 + detect_delistings 的
# GATE_FAIL 告警，3 支目標程式（cex_events／detect_delistings／healthcheck）
# 各一支對應的 mutation 函式，供下方各自章節的新檢查使用。
# --------------------------------------------------------------------------

def mut_ce_gate_dedup(text):
    """目標：cex_events.py main() 寫入 gate_skips.jsonl 前的去重過濾。還原成
    「不去重，直接把這次算出的完整清單全部附加」的修復前行為，模擬去重邏輯被
    意外刪除／重構掉的情境（見 docs/gate-dedup-report.md）。"""
    return apply_mutation(
        text,
        '    fresh_gate_skips = [g for g in gate_skips\n'
        '                        if (g["date"], g["exchange"], g["reason"]) not in gate_seen]',
        '    fresh_gate_skips = list(gate_skips)  '
        '# [selftest mutant] gate_skips dedup disabled',
        "ce_gate_dedup")


def mut_dd_gate_fail_log_dedup(text):
    """目標：detect_delistings.py record_gate_fail() 的去重判斷。還原成「永遠寫入，
    不管有沒有寫過」，模擬去重邏輯被意外刪除的情境（gate_skips.jsonl 曾經發生過的
    同一種錯誤，這份新紀錄檔本應從第一天就避免重蹈覆轍）。"""
    return apply_mutation(
        text,
        '    key = (date, source, group, reason)\n'
        '    if key in seen:\n'
        '        return False',
        '    key = (date, source, group, reason)\n'
        '    if False:  # [selftest mutant] gate_fail dedup disabled\n'
        '        return False',
        "dd_gate_fail_log_dedup")


def mut_hc_delist_gate_fail_today_filter(text):
    """目標：healthcheck.py check_delist_gate_fail() 的 date==TODAY 過濾。拿掉過濾，
    模擬「忘記只看最新一次轉換」的情境——main() 對完整歷史重新配對計算，若不過濾，
    所有歷史 GATE_FAIL 紀錄都會被當成『現在』的問題，永遠不會自動消失（與
    check_cex_gate_skips() 已解決過的同一類錯誤，見該函式模組層級註解第 2 點）。"""
    return apply_mutation(
        text,
        '                if g.get("date") == TODAY:\n'
        '                    today_fails.append(g)',
        '                today_fails.append(g)  '
        '# [selftest mutant] TODAY filter removed, all history always alerts',
        "hc_delist_gate_fail_today_filter")


# --------------------------------------------------------------------------
# 第三階段新增（track-crypto/scripts/detect_delistings.py 的兩個新分支，
# 見對應 chk_* 檢查與 GROUP_SOURCES 第三階段新增段落，specs/SPEC-detect-phase3.md）
# --------------------------------------------------------------------------
def mut_dd_group_tolerant_total_match(text):
    """目標：completeness_group() 的 tolerant_total_match 分支（第三階段新增，
agent_virtuals 專用）。同時停用兩個子條件（truncated 旗標檢查、
相對誤差容忍度檢查）——agent_virtuals 真實壞資料（時間預算截斷日）
剛好兩個子條件同時失敗（truncated=True 且落差遠超容忍度），只停用
其中一個子條件的話，另一個仍會正確擋下，real-replay 檢查測不出來，
見 docs/detect-phase3-report.md §3 的破壞驗證設計說明。"""
    return apply_mutation(
        text,
        '        if tf_val is not False:\n            return False, n_raw, "%s(%r) 非布林 False（缺失/True 一律 fail-closed 視為不完整）" % (tf_name, tf_val)\n        total_field = gcfg["total_field"]\n        total = data_root.get(total_field)\n        if not isinstance(total, (int, float)) or isinstance(total, bool) or total <= 0:\n            return False, n_raw, "缺 %s 欄位或非正數（%r）" % (total_field, total)\n        gap_pct = abs(total - n_raw) / total * 100.0\n        tol = gcfg["tolerance_pct"]\n        if gap_pct > tol:',
        '        if False:  # [selftest mutant] tolerant_total_match truncated-flag gate disabled\n            return False, n_raw, "%s(%r) 非布林 False（缺失/True 一律 fail-closed 視為不完整）" % (tf_name, tf_val)\n        total_field = gcfg["total_field"]\n        total = data_root.get(total_field)\n        if not isinstance(total, (int, float)) or isinstance(total, bool) or total <= 0:\n            return False, n_raw, "缺 %s 欄位或非正數（%r）" % (total_field, total)\n        gap_pct = abs(total - n_raw) / total * 100.0\n        tol = gcfg["tolerance_pct"]\n        if False:  # [selftest mutant] tolerant_total_match tolerance gate disabled',
        'dd_group_tolerant_total_match')


def mut_dd_group_composite_key_casefold(text):
    """目標：dedup() 複合鍵 tuple 分支的大小寫正規化（第三階段新增，
crypto_project_liveness 專用）。拿掉 .lower()，模擬「複合鍵大小寫
正規化被誤刪」的迴歸——真實資料 2026-08-29 的 Saturn→SATURN 大小寫
修正會因此被誤判為一筆消失＋一筆新增，見 docs/detect-phase3-report.md
§2.2 的實測案例。"""
    return apply_mutation(
        text,
        '                parts.append(v.lower() if isinstance(v, str) else v)',
        '                parts.append(v)  # [selftest mutant] composite key case-fold disabled',
        'dd_group_composite_key_casefold')


def mut_dd_rename_reconcile(text):
    """目標：compare_group() 的上游改名抵銷層（第四階段新增，2026-09-07 任務 B）。
整段停用 reconcile_renames() 呼叫，模擬「抵銷層被誤刪／被 revert」的迴歸——
真實資料 2026-09-05→09-06 的 Stake DAO→Stake DAO Yield 改名
（defillamaId 兩天都是 "249"）會因此重新被誤判為 2 筆消失＋2 筆新增，
見 docs/0907-B-rename-key-report.md §2。

錨點唯一性：`reconcile_renames(` 這個函式在 detect_delistings.py 裡只有
compare_group() 一個呼叫端（定義處的 `def reconcile_renames(` 字面不同，
不會被這個含前導縮排與換行的多行錨點匹配到），實測 count==1。
比照 docs/selftest-fix-report.md §2.1 選項 A 的教訓：錨點必須精確命中
「這條檢查實際會執行到的那一處」，不能只寫一個到處都可能出現的短句。"""
    return apply_mutation(
        text,
        '    added_keys, removed_keys, renamed_pairs = reconcile_renames(\n'
        '        gcfg, keyed_old, keyed_new, added_keys, removed_keys)',
        '    renamed_pairs = []  # [selftest mutant] rename reconciliation disabled',
        'dd_rename_reconcile')


def mut_dd_rename_reconcile_added_guard(text):
    """目標：reconcile_renames() 的第 3 個抵銷條件（`k_new not in added_set`，
第四階段新增）。拿掉這個條件之後，抵銷層會把「消失的那筆」跟一筆**前日就已經
存在、本次並非新增**的紀錄配對起來，於是一筆真實的消失被無聲吃掉——這是抵銷層
最危險的失效模式（減少事實紀錄），必須有專屬破壞驗證鎖住。

`matched_new` 這個條件保留不動，避免突變後改成一對多配對而丟出例外，
讓破壞驗證停在「判定變寬鬆」這個要測的行為上，不是停在例外。"""
    return apply_mutation(
        text,
        '        if k_new is None or k_new not in added_set or k_new in matched_new:\n'
        '            continue',
        '        if k_new is None or k_new in matched_new:  # [selftest mutant] added-set guard disabled\n'
        '            continue',
        'dd_rename_reconcile_added_guard')


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
# detect_changes.py — Y3 修法新增 3 條（SPEC-y3-rolling.md：滾動視窗 tail_start 公式
# 對 removed_set 的自我指涉造成的下架漏報路徑；見 docs/y3-rolling-report.md）
# 注意：這 3 條測試的是「Y3 補丁版」detect_changes.py（tail_start 公式已修正，見
# patches/y3-rolling/detect_changes.py.diff），不是目前的正式版本——本輪只產出補丁、
# 未部署，需搭配 SELFTEST_SOURCE_REPO 指向含補丁版 scripts/detect_changes.py 的目錄樹
# 才有意義；若指向未套用補丁的正式目錄，前兩條會直接 FAIL（因為正式版本身就有這個漏報）。
# ==========================================================================

@check("detect_changes.rolling_window_no_self_reference",
       mutate_target="detect_changes", mutate=mut_dc_rolling_window_self_reference)
def chk_dc_rolling_window_no_self_reference(is_mutant):
    """Y3 核心不變量：tail_start 公式不得用『當日全部消失筆數』（含尚待判定的真下架本身）
    估計捲動視窗大小，否則新增+移除量一多，安全區會自我膨脹，把明顯非清單尾端的真下架
    也吞成 rolled（漏報，見 docs/y3-rolling-report.md 第 2 節根因分析）。
    合成情境：視窗 50 筆，當日新增 20 篇（自然滾動 20 篇，原清單最舊的 I30..I49），
    另外 I10（position=10，清單前 20%、明顯非尾端）當天被真的下架。"""
    sandbox = new_sandbox("dc_rollself_mut" if is_mutant else "dc_rollself")
    text = read_source("detect_changes")
    if is_mutant:
        text = mut_dc_rolling_window_self_reference(text)
    script_path = install_text(sandbox, "scripts/detect_changes.py", text)
    old_items = [gov_item("I%d" % i, "T%d" % i, "body %d unchanged" % i) for i in range(50)]
    new_items = ([gov_item("I%d" % i, "T%d" % i, "body %d unchanged" % i) for i in range(50, 70)]
                 + [gov_item("I%d" % i, "T%d" % i, "body %d unchanged" % i)
                    for i in range(0, 30) if i != 10])
    old = gov_snapshot(old_items)
    new = gov_snapshot(new_items)
    f_old = write_gz_json(os.path.join(sandbox, "old.json.gz"), old)
    f_new = write_gz_json(os.path.join(sandbox, "new.json.gz"), new)
    mod = load_module(script_path)
    a, b, added, removed, changed, rolled, skip_removed = mod.compare("synthsrc", DC_CFG, f_old, f_new)
    guard_active = ("I10" in removed) and ("I10" not in rolled) and len(added) == 20
    return Result(guard_active,
                  "added=%d removed=%r I10_in_rolled=%s (期望 I10 進 removed、不在 rolled："
                  "position=10 明顯非清單尾端，同日高流量不該讓它被判定為滾動移出)"
                  % (len(added), removed, "I10" in rolled))


@check("detect_changes.rolling_window_no_self_reference_max_items_shrink",
       mutate_target="detect_changes", mutate=mut_dc_rolling_window_self_reference)
def chk_dc_rolling_window_no_self_reference_max_items(is_mutant):
    """Y3 邊界：MAX_ITEMS 調降造成的『乾淨縮窗』（不逾時、不觸發 truncated=true，比照本專案
    2026-08-31 實際把 fda_clarify／moj_press／tpe_clarify 由 100 降為 50 的調整，但假設當天
    站台回應正常、沒有觸發截斷保護——見 docs/y3-rolling-report.md 第 4.3 節，真實那次剛好
    被截斷保護意外接住，不能證明這條路徑本身安全）。合成情境：視窗 100→50，當日僅新增 3 篇，
    縮窗後清單只保留『新 3 篇 + 舊清單最新 47 筆（position 0..46）』，另外 J44
    （縮窗後理論上仍應存活的 position=44）當天被真的下架。"""
    sandbox = new_sandbox("dc_rollself_maxitems_mut" if is_mutant else "dc_rollself_maxitems")
    text = read_source("detect_changes")
    if is_mutant:
        text = mut_dc_rolling_window_self_reference(text)
    script_path = install_text(sandbox, "scripts/detect_changes.py", text)
    old_items = [gov_item("J%d" % i, "T%d" % i, "body %d unchanged" % i) for i in range(100)]
    new_items = ([gov_item("K%d" % i, "T%d" % i, "body %d unchanged" % i) for i in range(3)]
                 + [gov_item("J%d" % i, "T%d" % i, "body %d unchanged" % i)
                    for i in range(0, 47) if i != 44])
    old = gov_snapshot(old_items)
    new = gov_snapshot(new_items)
    f_old = write_gz_json(os.path.join(sandbox, "old.json.gz"), old)
    f_new = write_gz_json(os.path.join(sandbox, "new.json.gz"), new)
    mod = load_module(script_path)
    a, b, added, removed, changed, rolled, skip_removed = mod.compare("synthsrc", DC_CFG, f_old, f_new)
    guard_active = ("J44" in removed) and ("J44" not in rolled) and len(added) == 3
    return Result(guard_active,
                  "added=%d removed=%r J44_in_rolled=%s (期望 J44 進 removed：MAX_ITEMS 縮窗當天，"
                  "縮窗後仍應存活區間內的真下架不該被判定為滾動移出)"
                  % (len(added), removed, "J44" in rolled))


@check("detect_changes.rolling_window_no_self_reference.real_replay")
def chk_dc_rolling_window_no_self_reference_real(is_mutant):
    """real-replay：track-gov/mohw_press 真實歷史快照 2026-09-02->2026-09-03，VPS 正式
    changes/mohw_press/2026-09-03.md 記錄「新增3、下架1（id 87667）、滾動移出視窗2」，
    這是本專案歷史上唯一一筆真實下架事件。本檢查確認 Y3 補丁版 compare() 重放同一組真實
    快照，仍重算出完全相同的數字（回歸驗證：修法沒有改變任何一筆既有正確判定）。
    本項不做破壞驗證（沒有 mutate，比照本檔既有先例
    cex_events.daily_last_snapshot_only.real_replay 的作法）：docs/y3-rolling-report.md
    第 4.2 節已證明，這組真實資料上修法前後兩個公式算出的 tail_start 剛好都正確分類
    這一筆（92 vs 95，id 87667 的 position=13 兩者皆小於門檻），無法在純真實資料上
    有意義地讓破壞驗證翻盤——真正保證「自我指涉的漏報會被抓到」的是上面兩條合成資料版本。"""
    if is_mutant:
        return Result(True, "本項無破壞驗證，見 docstring 說明（避免依賴不保證存在的真實資料巧合）")
    sandbox = new_sandbox("dc_rollself_real")
    text = read_source("detect_changes")
    script_path = install_text(sandbox, "scripts/detect_changes.py", text)
    f_old = install_binary_copy(os.path.join(SOURCE_REPO, "track-gov/data/mohw_press/2026-09-02.json.gz"),
                                 sandbox, "old.json.gz")
    f_new = install_binary_copy(os.path.join(SOURCE_REPO, "track-gov/data/mohw_press/2026-09-03.json.gz"),
                                 sandbox, "new.json.gz")
    mod = load_module(script_path)
    a, b, added, removed, changed, rolled, skip_removed = mod.compare("mohw_press", DC_CFG, f_old, f_new)
    guard_active = (len(added) == 3 and removed == ["87667"] and sorted(rolled) == ["87201", "87207"])
    return Result(guard_active,
                  "real-replay mohw_press 2026-09-02->2026-09-03; added=%d removed=%r rolled=%r "
                  "(VPS changes/mohw_press/2026-09-03.md 原始記錄：新增3/下架1(id 87667)/滾動移出2；"
                  "Y3 補丁版須重算出完全相同數字)"
                  % (len(added), removed, sorted(rolled)))


# ==========================================================================
# ==========================================================================
# detect_changes.py — Window Guard 新增 7 條（SPEC-window-guard.md：補完 Y3 修法
# docs/y3-rolling-report.md 第 8.3 節誠實揭露的已知缺口——視窗大小刻意變更
# （例如 MAX_ITEMS 調整）且未同時觸發截斷保護時，v3 公式會把因視窗變小而自然消失的
# 項目誤判為下架。見 scripts/detect_changes.py 的 compare_guarded()／
# window_changed_significantly()／window_size_of()。
# ==========================================================================

def _copy_real_manifest_entry(sandbox, date, source):
    """把 SOURCE_REPO 當日 track-gov manifest 裡指定來源的紀錄，原樣複製進 sandbox
    （只複製這一個來源的 dict，不動其餘來源，供 window_size_of() 在 sandbox 內讀到
    真實歷史的 n）。同一 sandbox、同一天若已有其他來源寫入過，合併而不覆蓋。"""
    real_path = os.path.join(SOURCE_REPO, "track-gov/data/_manifest", "%s.json" % date)
    with open(real_path, encoding="utf-8") as f:
        real_manifest = json.load(f)
    entry = real_manifest["channels"][source]
    dest = os.path.join(sandbox, "track-gov/data/_manifest", "%s.json" % date)
    obj = {"date": date, "channels": {}}
    if os.path.exists(dest):
        obj = json.load(open(dest, encoding="utf-8"))
    obj["channels"][source] = entry
    install_text(sandbox, "track-gov/data/_manifest/%s.json" % date, json.dumps(obj))
    return entry


@check("detect_changes.window_guard_threshold", mutate_target="detect_changes",
       mutate=mut_dc_window_guard_and_to_or)
def chk_dc_window_guard_threshold(is_mutant):
    """Window Guard 核心不變量：window_changed_significantly() 必須同時滿足「相對變化
    ≥20%」與「絕對筆數差 ≥5」兩個門檻（見 SPEC-window-guard.md、
    docs/window-guard-report.md「門檻依據」節：2026-08-27~09-04 全歷史 124 組視窗
    穩定真實資料，相對變化最大僅 1.01%、絕對差最大 1 筆；已知 MAX_ITEMS 事件相對變化
    28.2%~67.0%、絕對差 11~67 筆）。逐一驗證邊界案例，包含 AND 邏輯缺一不可的兩組
    對照（僅相對門檻過／僅絕對門檻過皆不應觸發）與缺值防禦性處理。"""
    sandbox = new_sandbox("dc_wg_threshold_mut" if is_mutant else "dc_wg_threshold")
    text = read_source("detect_changes")
    if is_mutant:
        text = mut_dc_window_guard_and_to_or(text)
    script_path = install_text(sandbox, "scripts/detect_changes.py", text)
    mod = load_module(script_path)
    cases = [
        (100, 100, False, "無變化"),
        (100, 79, True, "-21%/-21筆，雙門檻皆過"),
        (100, 81, False, "-19%/-19筆，雙門檻皆不過"),
        (100, 94, False, "-6%/-6筆，僅絕對門檻過（AND 邏輯應擋下）"),
        (10, 7, False, "-30%/-3筆，僅相對門檻過（AND 邏輯應擋下，小視窗雜訊防線）"),
        (15, 9, True, "-40%/-6筆，雙門檻皆過"),
        (None, 100, False, "n_old 缺值"),
        (100, None, False, "n_new 缺值"),
        (0, 100, False, "n_old<=0（防禦除以零）"),
    ]
    failures = []
    for n_old, n_new, expected, desc in cases:
        got = mod.window_changed_significantly(n_old, n_new)
        if got != expected:
            failures.append("%s: n_old=%r n_new=%r 預期=%r 實際=%r" % (desc, n_old, n_new, expected, got))
    return Result(not failures, "; ".join(failures) if failures else
                  "全部 %d 組邊界案例符合預期（雙門檻 AND 邏輯、缺值保守不觸發）" % len(cases))


@check("detect_changes.window_guard_shrink_skips_removed", mutate_target="detect_changes",
       mutate=mut_dc_window_guard_disabled)
def chk_dc_window_guard_shrink(is_mutant):
    """Window Guard 核心不變量：MAX_ITEMS 100->50 乾淨縮窗（無 truncated，比照本專案
    2026-08-31 實際調整、但假設站台回應正常、未觸發截斷保護，見
    docs/window-guard-report.md「重現 08-31 情境」節）時，即使 v3（Y3）修法的
    rolling-window heuristic 本身會把縮窗後仍應存活區間內的真下架（position=44）
    誤判為 rolled（docs/y3-rolling-report.md 第 8.3 節已證明的已知缺口），
    Window Guard 必須整批跳過下架判定（removed=[]、rolled=[]、skip_removed=True、
    reason="window_change"）。另外驗證「改寫（changed）不受影響」：K0 這一筆兩天皆
    存在但內容不同，縮窗跳過下架判定的同一天，K0 仍必須正確出現在 changed。"""
    sandbox = new_sandbox("dc_wg_shrink_mut" if is_mutant else "dc_wg_shrink")
    text = read_source("detect_changes")
    if is_mutant:
        text = mut_dc_window_guard_disabled(text)
    script_path = install_text(sandbox, "scripts/detect_changes.py", text)

    old_items = [gov_item("J%d" % i, "T%d" % i, "body %d unchanged" % i) for i in range(100)]
    old_items.append(gov_item("K0", "T-K0", "body K0 舊內容"))
    new_items = ([gov_item("M%d" % i, "T%d" % i, "body %d unchanged" % i) for i in range(3)]
                 + [gov_item("J%d" % i, "T%d" % i, "body %d unchanged" % i)
                    for i in range(0, 47) if i != 44]
                 + [gov_item("K0", "T-K0", "body K0 新內容（改寫）")])
    old = gov_snapshot(old_items, truncated=False)
    new = gov_snapshot(new_items, truncated=False)
    f_old = write_gz_json(os.path.join(sandbox, "track-gov/data/wgsrc/2030-07-01.json.gz"), old)
    f_new = write_gz_json(os.path.join(sandbox, "track-gov/data/wgsrc/2030-07-02.json.gz"), new)
    install_text(sandbox, "track-gov/data/_manifest/2030-07-01.json", json.dumps(
        {"date": "2030-07-01", "channels": {"wgsrc": {"ok": True, "n": len(old_items), "bytes": 1,
                                                        "secs": 1.0, "attempts": 1, "truncated": False}}}))
    install_text(sandbox, "track-gov/data/_manifest/2030-07-02.json", json.dumps(
        {"date": "2030-07-02", "channels": {"wgsrc": {"ok": True, "n": len(new_items), "bytes": 1,
                                                        "secs": 1.0, "attempts": 1, "truncated": False}}}))
    mod = load_module(script_path)
    a, b, added, removed, changed, rolled, skip_removed, reason, n_old, n_new = \
        mod.compare_guarded("wgsrc", DC_CFG, f_old, f_new)
    guard_active = (skip_removed is True and reason == "window_change"
                     and removed == [] and rolled == [] and "K0" in changed
                     and n_old == 101 and n_new == 50)
    return Result(guard_active,
                  "removed=%r rolled=%r skip_removed=%s reason=%s changed=%r n_old=%s n_new=%s "
                  "(期望縮窗當日 removed/rolled 皆空、skip_removed=True、reason=window_change，"
                  "且 K0 仍正確出現在 changed)"
                  % (removed, rolled, skip_removed, reason, changed, n_old, n_new))


@check("detect_changes.window_guard_recovers_next_day", mutate_target="detect_changes",
       mutate=mut_dc_window_guard_stuck)
def chk_dc_window_guard_recovers(is_mutant):
    """Window Guard 核心不變量：視窗大小穩定後，下一次比對即自動恢復正常下架判定
    （SPEC-window-guard.md 驗收 2：「縮窗當日不報下架、次日恢復正常判定；真下架在
    視窗穩定時仍被偵測到」）。三天合成情境：Day A（視窗 100）-> Day B（MAX_ITEMS
    縮到 ~50，無 truncated，注入真下架 G44）-> Day C（視窗穩定在 B 的大小，僅 2%
    變化，遠低於門檻，注入另一筆真下架 位置 5，明顯非清單尾端）。斷言 A->B 當天
    跳過（reason=window_change，removed/rolled 皆空），B->C 當天恢復正常判定且
    該筆真下架正確進入 removed（不是 rolled）。"""
    sandbox = new_sandbox("dc_wg_recover_mut" if is_mutant else "dc_wg_recover")
    text = read_source("detect_changes")
    if is_mutant:
        text = mut_dc_window_guard_stuck(text)
    script_path = install_text(sandbox, "scripts/detect_changes.py", text)

    ids_A = list(range(1099, 999, -1))  # 100 items，newest-first：1099..1000
    items_A = [gov_item("G%d" % i, "T%d" % i, "body %d" % i) for i in ids_A]
    added_B = [2001, 2002, 2003]
    genuine_pos_B = 44
    genuine_id_B = ids_A[genuine_pos_B]
    survivors_B = [i for i in ids_A[:47] if i != genuine_id_B]
    items_B = ([gov_item("G%d" % i, "T%d" % i, "body %d" % i) for i in added_B]
               + [it for it in items_A if int(it["id"][1:]) in survivors_B])
    ids_B = [int(it["id"][1:]) for it in items_B]
    added_C = [3001, 3002]
    genuine_pos_C = 5
    genuine_id_C = ids_B[genuine_pos_C]
    natural_rolled_C = ids_B[-2:]
    survivors_C = [i for i in ids_B if i not in natural_rolled_C and i != genuine_id_C]
    items_C = ([gov_item("G%d" % i, "T%d" % i, "bodyC %d" % i) for i in added_C]
               + [it for it in items_B if int(it["id"][1:]) in survivors_C])

    def dump(day, items):
        snap = gov_snapshot(items, truncated=False)
        f = write_gz_json(os.path.join(sandbox, "track-gov/data/wgrec/%s.json.gz" % day), snap)
        install_text(sandbox, "track-gov/data/_manifest/%s.json" % day, json.dumps(
            {"date": day, "channels": {"wgrec": {"ok": True, "n": len(items), "bytes": 1,
                                                   "secs": 1.0, "attempts": 1, "truncated": False}}}))
        return f

    f_A = dump("2030-08-01", items_A)
    f_B = dump("2030-08-02", items_B)
    f_C = dump("2030-08-03", items_C)

    mod = load_module(script_path)
    rAB = mod.compare_guarded("wgrec", DC_CFG, f_A, f_B)
    rBC = mod.compare_guarded("wgrec", DC_CFG, f_B, f_C)
    ab_ok = (rAB[6] is True and rAB[7] == "window_change" and rAB[3] == [] and rAB[5] == [])
    bc_ok = (rBC[6] is False and rBC[7] is None
             and ("G%d" % genuine_id_C) in rBC[3] and ("G%d" % genuine_id_C) not in rBC[5])
    return Result(ab_ok and bc_ok,
                  "A->B: skip_removed=%s reason=%s removed=%r rolled=%r (期望縮窗當日整批跳過) | "
                  "B->C: skip_removed=%s reason=%s removed=%r rolled=%r (期望視窗穩定後自動恢復，"
                  "真下架 G%d 正確進入 removed)"
                  % (rAB[6], rAB[7], rAB[3], rAB[5], rBC[6], rBC[7], rBC[3], rBC[5], genuine_id_C))


@check("detect_changes.window_guard_real_replay_2026_08_31_without_truncation")
def chk_dc_window_guard_real_replay_no_trunc(is_mutant):
    """real-replay（SPEC-window-guard.md 驗收 1）：重現 2026-08-31 MAX_ITEMS 100->50
    真實事件（fda_clarify／moj_press／tpe_clarify 三個來源皆驗證），把當日快照複本
    的 `_meta.truncated` 人為改成 False（模擬「這次調整沒有同時逾時」，即當時只是
    巧合被截斷保護接住，見 docs/y3-rolling-report.md 第 4.3 節；正式檔案唯讀，
    本檢查只改 sandbox 內的複本），證明即使沒有截斷保護，Window Guard 本身也會
    獨立擋下——manifest 的 n（100->33/35/39，不受這個人為修改影響，因為 n 來自
    獨立的 manifest 檔案，不是快照內嵌 _meta）足以觸發視窗變更保護。
    本項無破壞驗證（比照既有 real_replay 先例，如
    detect_changes.rolling_window_no_self_reference.real_replay）：破壞驗證已由
    上面的合成資料版本（window_guard_shrink_skips_removed #mutant）涵蓋，此處只用
    真實資料驗證同一保護在正式歷史事件上確實生效，不重複做破壞驗證。"""
    if is_mutant:
        return Result(True, "本項無破壞驗證，見 docstring 說明（比照既有 real_replay 先例）")
    text = read_source("detect_changes")
    all_ok = True
    details = []
    for source in ("fda_clarify", "moj_press", "tpe_clarify"):
        sandbox = new_sandbox("dc_wg_0831_notrunc_%s" % source)
        script_path = install_text(sandbox, "scripts/detect_changes.py", text)
        # 檔名刻意維持「日期在前 10 碼」（比照正式快照命名），因為
        # window_size_of() 靠 os.path.basename(f)[:10] 推算比對日期去查 manifest。
        f_old = install_binary_copy(
            os.path.join(SOURCE_REPO, "track-gov/data/%s/2026-08-30.json.gz" % source),
            sandbox, "track-gov/data/%s/2026-08-30.json.gz" % source)
        real_new_path = os.path.join(SOURCE_REPO, "track-gov/data/%s/2026-08-31.json.gz" % source)
        with gzip.open(real_new_path, "rt", encoding="utf-8") as fh:
            j_new = json.load(fh)
        j_new["_meta"]["truncated"] = False
        j_new["_meta"].pop("items_fetched", None)
        f_new = write_gz_json(
            os.path.join(sandbox, "track-gov/data/%s/2026-08-31.json.gz" % source), j_new)
        _copy_real_manifest_entry(sandbox, "2026-08-30", source)
        _copy_real_manifest_entry(sandbox, "2026-08-31", source)
        mod = load_module(script_path)
        cfg = DC_CFG  # 三個真實來源欄位形狀與 DC_CFG 相同（id/title/body_text/body_sha256/url），
                      # 不透過 TEXT_SOURCES／_discover() 查表——sandbox 內沒有 track-gov/adapters/，
                      # 比照既有 real_replay 檢查（如 rolling_window_no_self_reference.real_replay）
                      # 的既有做法，直接用固定 cfg。
        a, b, added, removed, changed, rolled, skip_removed, reason, n_old, n_new = \
            mod.compare_guarded(source, cfg, f_old, f_new)
        ok = (skip_removed is True and reason == "window_change" and removed == [] and rolled == [])
        all_ok = all_ok and ok
        details.append("%s: manifest n=%s->%s removed=%d rolled=%d skip_removed=%s reason=%s%s"
                        % (source, n_old, n_new, len(removed), len(rolled), skip_removed, reason,
                           "" if ok else " <-- 未如預期跳過"))
    return Result(all_ok, "; ".join(details))


@check("detect_changes.window_guard_real_replay_2026_08_31_truncation_priority")
def chk_dc_window_guard_real_replay_priority(is_mutant):
    """real-replay（零回歸驗證）：2026-08-31 真實事件（完全未修改，`_meta.truncated`
    維持真實值 True），確認 Window Guard 疊加後 reason 仍是 "truncated"（不是
    "window_change"）——截斷保護優先序高於視窗變更保護（見 compare_guarded()
    設計原則第 4 點），且與未加保護的 compare() 逐欄位相同，確保這 3 個來源既有的
    （截斷）行為與訊息逐位元組不變（SPEC-window-guard.md 硬性要求「不得放寬任何
    既有保護」）。本項無破壞驗證：這裡驗證的是「優先序沒有被打亂、零回歸」，
    不是「保護本身有沒有生效」，真正的破壞驗證由 window_guard_shrink_skips_removed
    （#mutant）涵蓋。"""
    if is_mutant:
        return Result(True, "本項無破壞驗證，見 docstring 說明")
    text = read_source("detect_changes")
    all_ok = True
    details = []
    for source in ("fda_clarify", "moj_press", "tpe_clarify"):
        sandbox = new_sandbox("dc_wg_0831_priority_%s" % source)
        script_path = install_text(sandbox, "scripts/detect_changes.py", text)
        f_old = install_binary_copy(
            os.path.join(SOURCE_REPO, "track-gov/data/%s/2026-08-30.json.gz" % source),
            sandbox, "track-gov/data/%s/2026-08-30.json.gz" % source)
        f_new = install_binary_copy(
            os.path.join(SOURCE_REPO, "track-gov/data/%s/2026-08-31.json.gz" % source),
            sandbox, "track-gov/data/%s/2026-08-31.json.gz" % source)
        _copy_real_manifest_entry(sandbox, "2026-08-30", source)
        _copy_real_manifest_entry(sandbox, "2026-08-31", source)
        mod = load_module(script_path)
        cfg = DC_CFG  # 三個真實來源欄位形狀與 DC_CFG 相同（id/title/body_text/body_sha256/url），
                      # 不透過 TEXT_SOURCES／_discover() 查表——sandbox 內沒有 track-gov/adapters/，
                      # 比照既有 real_replay 檢查（如 rolling_window_no_self_reference.real_replay）
                      # 的既有做法，直接用固定 cfg。
        base = mod.compare(source, cfg, f_old, f_new)
        guarded = mod.compare_guarded(source, cfg, f_old, f_new)
        ok = (guarded[6] is True and guarded[7] == "truncated" and guarded[:7] == base)
        all_ok = all_ok and ok
        details.append("%s: skip_removed=%s reason=%s 與未加保護版逐欄位相同=%s%s"
                        % (source, guarded[6], guarded[7], guarded[:7] == base,
                           "" if ok else " <-- 不符預期"))
    return Result(all_ok, "; ".join(details))


@check("detect_changes.window_guard_stable_window_no_false_positive")
def chk_dc_window_guard_no_false_positive_real(is_mutant):
    """real-replay（門檻依據的直接驗證）：本專案 2026-08-27~09-04 全歷史 124 組「視窗
    穩定」真實資料中，相對變化最大的兩組（mof_press 09-03->09-04 與 ey_press
    09-02->09-03，相對變化皆 1.00%~1.01%，見 docs/window-guard-report.md「門檻依據」
    節）用真實快照驗證 Window Guard 在這個「最貼近門檻」的真實案例上不會誤觸發
    （reason 必須是 None，不是 window_change），且與未加保護的 compare() 逐欄位相同。
    本項無破壞驗證：這裡驗證的是「正常情況不誤殺」，門檻本身的破壞驗證由
    window_guard_threshold（#mutant）涵蓋。"""
    if is_mutant:
        return Result(True, "本項無破壞驗證，見 docstring 說明")
    text = read_source("detect_changes")
    all_ok = True
    details = []
    for source, d_old, d_new in (("mof_press", "2026-09-03", "2026-09-04"),
                                  ("ey_press", "2026-09-02", "2026-09-03")):
        sandbox = new_sandbox("dc_wg_nofp_%s" % source)
        script_path = install_text(sandbox, "scripts/detect_changes.py", text)
        f_old = install_binary_copy(
            os.path.join(SOURCE_REPO, "track-gov/data/%s/%s.json.gz" % (source, d_old)),
            sandbox, "track-gov/data/%s/%s.json.gz" % (source, d_old))
        f_new = install_binary_copy(
            os.path.join(SOURCE_REPO, "track-gov/data/%s/%s.json.gz" % (source, d_new)),
            sandbox, "track-gov/data/%s/%s.json.gz" % (source, d_new))
        _copy_real_manifest_entry(sandbox, d_old, source)
        _copy_real_manifest_entry(sandbox, d_new, source)
        mod = load_module(script_path)
        cfg = DC_CFG  # 三個真實來源欄位形狀與 DC_CFG 相同（id/title/body_text/body_sha256/url），
                      # 不透過 TEXT_SOURCES／_discover() 查表——sandbox 內沒有 track-gov/adapters/，
                      # 比照既有 real_replay 檢查（如 rolling_window_no_self_reference.real_replay）
                      # 的既有做法，直接用固定 cfg。
        base = mod.compare(source, cfg, f_old, f_new)
        guarded = mod.compare_guarded(source, cfg, f_old, f_new)
        ok = (guarded[7] is None and guarded[:7] == base)
        all_ok = all_ok and ok
        details.append("%s %s->%s: manifest n=%s->%s reason=%s%s"
                        % (source, d_old, d_new, guarded[8], guarded[9], guarded[7],
                           "" if ok else " <-- 不符預期（誤觸發或與 compare() 不一致）"))
    return Result(all_ok, "; ".join(details))


@check("detect_changes.window_guard_missing_manifest_no_skip", mutate_target="detect_changes",
       mutate=mut_dc_window_guard_missing_data_skips)
def chk_dc_window_guard_missing_manifest(is_mutant):
    """Window Guard 邊界不變量：manifest 讀不到 n（例如 manifest 檔案不存在、或當日
    該來源沒有紀錄）時，一律保守判定為「不觸發跳過」，沿用既有（v3）判定，不會因為
    讀不到一個輔助欄位就意外擴大既有保護的跳過範圍（見 window_size_of() 說明）。
    合成情境：刻意不建立任何 track-gov/data/_manifest 檔案（模擬 manifest 缺席），
    同時放入一筆位置明顯非尾端（position=5）的真下架 Z5，驗證在「manifest 缺席」的
    防禦性路徑下，Window Guard 不介入（n_old／n_new 皆 None、reason 為 None、
    skip_removed 為 False），既有（v3）下架判定依然正常運作、真下架依然被抓到。"""
    sandbox = new_sandbox("dc_wg_nomanifest_mut" if is_mutant else "dc_wg_nomanifest")
    text = read_source("detect_changes")
    if is_mutant:
        text = mut_dc_window_guard_missing_data_skips(text)
    script_path = install_text(sandbox, "scripts/detect_changes.py", text)
    old_items = [gov_item("Z%d" % i, "T%d" % i, "body %d" % i) for i in range(30)]
    new_items = ([gov_item("Z%d" % i, "T%d" % i, "body %d" % i) for i in range(30, 32)]
                 + [it for it in old_items if it["id"] not in ("Z5", "Z28", "Z29")])
    old = gov_snapshot(old_items, truncated=False)
    new = gov_snapshot(new_items, truncated=False)
    # 刻意不建立 track-gov/data/_manifest/ 底下任何檔案，模擬 manifest 缺席。
    f_old = write_gz_json(os.path.join(sandbox, "track-gov/data/wgnm/2030-09-01.json.gz"), old)
    f_new = write_gz_json(os.path.join(sandbox, "track-gov/data/wgnm/2030-09-02.json.gz"), new)
    mod = load_module(script_path)
    a, b, added, removed, changed, rolled, skip_removed, reason, n_old, n_new = \
        mod.compare_guarded("wgnm", DC_CFG, f_old, f_new)
    guard_inactive = (n_old is None and n_new is None and reason is None and skip_removed is False
                       and "Z5" in removed and "Z5" not in rolled)
    return Result(guard_inactive,
                  "n_old=%r n_new=%r reason=%s skip_removed=%s removed=%r (期望 manifest 缺席時"
                  "保守不觸發跳過，既有 v3 判定正常運作、Z5 正確進入 removed)"
                  % (n_old, n_new, reason, skip_removed, removed))


# track-crypto/scripts/detect_delistings.py — 20 條不變量（第一階段 4 條 + 第二階段新行為 5 條 + 覆蓋缺口補齊 2 條，SPEC-selftest-gap.md + gate-dedup 新增 1 條，SPEC-gate-dedup.md + 第三階段新增 5 條，SPEC-detect-phase3.md + 第四階段新增 3 條，2026-09-07 任務 B 上游改名抵銷，見 docs/0907-B-rename-key-report.md）
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
    # 2026-09-07 更新（恆真式守門修正）：造假的對象從 data.total 改成
    # data.reported_total（上游自報總數）——因為守門的比對基準已經換成後者。
    # 這一組刻意讓 data.total 與 len(items) **完全自我一致**（都是 98），
    # 證明守門攔下來靠的不是那個自我一致的數字。
    old = x402_snapshot([x402_item("R%d" % i, "d%d" % i) for i in range(100)])
    new_items = [x402_item("R%d" % i, "d%d" % i) for i in range(98)]  # 只剩 98 筆（R98,R99 消失）
    new = x402_snapshot(new_items, reported_total=110)  # 上游說 110 筆，實際只抓到 98 筆 → 差 12 筆
    f_old = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-02-01.json.gz"), old)
    f_new = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-02-02.json.gz"), new)
    r = mod.compare_pair("x402_bazaar", cfg, f_old, f_new)
    judged = mod.judge(r, cfg)
    seen, last_delisted = set(), {}
    judged2, r2, fresh, entries, alert_written = mod.process_pair("x402_bazaar", cfg, f_old, f_new, seen, last_delisted)
    guard_active = (judged == "GATE_FAIL") and (fresh == [])
    return Result(guard_active,
                  "reported_total=110 vs len(items)=98（差 12 筆，容忍度 max(5, 0.1%%×110)=5）；"
                  "judged=%s fresh_events=%d "
                  "(期望 judged=GATE_FAIL，不寫任何事件；removed_rate 若未被此守門攔截將只有 2%%，"
                  "刻意設計在熔斷門檻 5%% 之下，確保這條檢查只測完整性守門本身)"
                  % (judged, len(fresh)))


def _dd_manifest(sandbox, dates, source="x402_bazaar", ok=True, truncated=False, parser_version=1):
    """熔斷語意統一（2026-09-07）新增的輔助函式：在沙盒裡寫出 breaker_release_check()
    要讀的 track-crypto/data/_manifest/<date>.json 側證檔（欄位名與正式
    track-crypto/scripts/snap_crypto.py 產生的 manifest 逐一核對相同）。"""
    for d in dates:
        install_text(sandbox, "track-crypto/data/_manifest/%s.json" % d,
                      json.dumps({"date": d, "sources": {source: {
                          "ok": ok, "bytes": 1234, "secs": 1.0,
                          "parser_version": parser_version, "n": 100,
                          "complete": True, "completeness_check": "total_match",
                          "reported_total": 100, "truncated": truncated, "dup_keys": 0}}},
                                 ensure_ascii=False))


def _dd_quarantine_rows(sandbox, source="x402_bazaar"):
    """讀沙盒裡的隔離檔（events_quarantine.jsonl），不存在時回空清單。"""
    return read_jsonl(os.path.join(sandbox, "track-crypto/data", source, "events_quarantine.jsonl"))


@check("detect_delistings.breaker_threshold", mutate_target="detect_delistings", mutate=mut_dd_breaker)
def chk_dd_breaker(is_mutant):
    """熔斷門檻本身是否會觸發（2026-09-07 更新斷言：本檢查的合成資料是「消失的 30 筆
    剛好是前一日清單的連續尾端」，在新語意下會同時命中分頁截斷指紋，因此走的是
    『熔斷成立→指紋成立→隔離』這條路徑：events.jsonl 不寫、隔離檔完整保留、
    ALERT-DELIST.md 照寫。事件事實沒有遺失是新語意的重點，所以斷言一併檢查隔離檔）。
    熔斷關掉後（mutant）判定會變回 NORMAL、事件直接寫進 events.jsonl，本檢查翻盤成 FAIL。"""
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
    _dd_manifest(sandbox, ["2030-02-11", "2030-02-12"])
    seen, last_delisted = {}, {}
    seen = set()
    judged, r, fresh, entries, alert_written = mod.process_pair("x402_bazaar", cfg, f_old, f_new, seen, last_delisted)
    q = _dd_quarantine_rows(sandbox)
    q_del = [e for e in q if e["event"] == "DELISTED"]
    guard_active = (judged == "BREAKER") and (fresh == []) and alert_written and len(q_del) == 30
    return Result(guard_active,
                  "removed_rate=%.1f%% (門檻 %.1f%%)；judged=%s fresh_events=%d alert_written=%s "
                  "隔離檔DELISTED=%d tail_cover=%.4f "
                  "(期望 judged=BREAKER、events.jsonl 不寫、ALERT-DELIST.md 有寫、"
                  "隔離檔保留 30 筆：合成資料的移除項目剛好是連續尾端，命中截斷指紋)"
                  % (r["removed_rate"], cfg["breaker_pct"], judged, len(fresh), alert_written,
                     len(q_del), r.get("tail_cover", -1)))


def _dd_breaker_scatter_fixtures(sandbox, tag):
    """熔斷語意統一（2026-09-07）新增：造一組「移除規模超過熔斷門檻，但移除項目**分散**
    在整份清單裡（不是連續尾端）」的三日合成快照，用來測『熔斷→放行→標記寫入』這條路徑。

    day1: R0..R99（100 筆）
    day2: 只少 R5（1 筆＝1%，低於 5% 門檻）→ NORMAL，R5 被記為消失
    day3: R5 回來，另外散布移除 30 筆（含 R0，但**不含 R99**，確保 tail_run=0）
          → removed_rate 約 30%，遠超 5%，但 tail_cover=0.0 不會命中截斷指紋
    回傳 (f1, f2, f3)。
    """
    day1 = [x402_item("R%d" % i, "d%d" % i) for i in range(100)]
    day2 = [it for it in day1 if it["resource"] != "R5"]
    # 散布移除：從 R0 開始每 3 筆挑 1 筆，挑滿 30 筆，且刻意跳過 R99（最後一筆必須留著）
    victims = [i for i in range(0, 99, 3)][:30]
    gone = {"R%d" % i for i in victims}
    day3 = [it for it in day1 if it["resource"] not in gone]  # R5 已回到清單（day1 含 R5）
    f1 = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-02-20.json.gz"),
                        x402_snapshot(day1))
    f2 = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-02-21.json.gz"),
                        x402_snapshot(day2))
    f3 = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-02-22.json.gz"),
                        x402_snapshot(day3))
    return f1, f2, f3


@check("detect_delistings.breaker_marks_not_veto", mutate_target="detect_delistings",
       mutate=mut_dd_breaker_not_veto)
def chk_dd_breaker_marks_not_veto(is_mutant):
    """熔斷語意統一（2026-09-07，任務 C）核心不變量：熔斷成立、且放行檢查通過時，
    事件必須**照常寫入 events.jsonl**，而且該組轉換的**每一筆**事件
    （DELISTED／LISTED／REAPPEARED）都要帶齊 4 個統一標記欄位。

    這條檢查鎖的就是 x402_bazaar 2026-09-06→09-07 那次熔斷造成 1,399 DELISTED＋
    387 LISTED＋31 REAPPEARED 永久遺失的根因（見 docs/0907-events-audit-0904-0907.md
    §6.1）：舊行為是「否決整組」，REAPPEARED 尤其補不回來。
    mutant 把落地去向改回「只有 NORMAL 才寫」，事件數立刻歸零，本檢查翻盤成 FAIL。"""
    sandbox = new_sandbox("dd_bmark_mut" if is_mutant else "dd_bmark")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_breaker_not_veto(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    cfg = mod.SOURCES["x402_bazaar"]
    f1, f2, f3 = _dd_breaker_scatter_fixtures(sandbox, "bmark")
    _dd_manifest(sandbox, ["2030-02-20", "2030-02-21", "2030-02-22"])
    seen, last_delisted = set(), {}
    j12, r12, fresh12, e12, a12 = mod.process_pair("x402_bazaar", cfg, f1, f2, seen, last_delisted)
    j23, r23, fresh23, e23, a23 = mod.process_pair("x402_bazaar", cfg, f2, f3, seen, last_delisted)
    delisted = [e for e in fresh23 if e["event"] == "DELISTED"]
    listed = [e for e in fresh23 if e["event"] == "LISTED"]
    reappeared = [e for e in fresh23 if e["event"] == "REAPPEARED"]
    need = ("note", "breaker_tripped", "removed_pct", "breaker_threshold")
    fully_marked = [e for e in fresh23
                    if all(k in e for k in need) and e["breaker_tripped"] is True
                    and e["note"] == "anomalous_scale"]
    guard_active = (j12 == "NORMAL" and j23 == "BREAKER"
                    and len(delisted) == 30 and len(reappeared) == 1
                    and len(fully_marked) == len(fresh23) and len(fresh23) > 0
                    and a23 and r23.get("to_events") is True
                    and _dd_quarantine_rows(sandbox) == [])
    return Result(guard_active,
                  "day2->day3 judged=%s（期望 BREAKER，removed_rate=%.1f%%>5%%，tail_cover=%.4f<0.50）"
                  "；寫入 events.jsonl 的事件 DELISTED=%d(期望30) LISTED=%d REAPPEARED=%d(期望1) "
                  "全部帶齊 4 個標記欄位=%d/%d；ALERT-DELIST.md 已寫=%s；隔離檔筆數=%d(期望0)"
                  % (j23, r23["removed_rate"], r23.get("tail_cover", -1),
                     len(delisted), len(listed), len(reappeared),
                     len(fully_marked), len(fresh23), a23, len(_dd_quarantine_rows(sandbox))))


@check("detect_delistings.breaker_truncation_fingerprint", mutate_target="detect_delistings",
       mutate=mut_dd_breaker_fingerprint)
def chk_dd_breaker_fingerprint(is_mutant):
    """熔斷語意統一（2026-09-07）的反面風險防線：熔斷成立、但移除項目是「前一日清單的
    連續尾端」（分頁提前中止的結構特徵）時，事件**不可以**寫進 events.jsonl，必須改進
    隔離檔。這是 SPEC 明文要求評估的「若熔斷其實來自抓取截斷，標記不否決就會寫入大量
    假 DELISTED」那個風險的實際擋板。

    正控制（尾端連續移除 30 筆，tail_cover=1.0）：期望 events.jsonl 0 筆、隔離檔 30 筆。
    負控制（同樣移除 30 筆但散布，tail_cover=0.0）：期望 events.jsonl 有寫。
    mutant 關掉指紋判斷後正控制會被放行寫入，本檢查翻盤成 FAIL。"""
    sandbox = new_sandbox("dd_bfp_mut" if is_mutant else "dd_bfp")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_breaker_fingerprint(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    cfg = mod.SOURCES["x402_bazaar"]
    # 正控制：尾端連續移除
    tail_old = x402_snapshot([x402_item("T%03d" % i, "d%d" % i) for i in range(100)])
    tail_new = x402_snapshot([x402_item("T%03d" % i, "d%d" % i) for i in range(70)], total=70)
    ft_o = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-03-11.json.gz"), tail_old)
    ft_n = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-03-12.json.gz"), tail_new)
    _dd_manifest(sandbox, ["2030-03-11", "2030-03-12", "2030-02-20", "2030-02-21", "2030-02-22"])
    seen, last_delisted = set(), {}
    j_tail, r_tail, fresh_tail, _e, a_tail = mod.process_pair("x402_bazaar", cfg, ft_o, ft_n, seen, last_delisted)
    q_tail = _dd_quarantine_rows(sandbox)
    # 負控制：同樣規模但散布（沿用 marks_not_veto 那組 fixture 的第 1、3 天）
    f1, f2, f3 = _dd_breaker_scatter_fixtures(sandbox, "bfp")
    seen2, last2 = set(), {}
    j_sc, r_sc, fresh_sc, _e2, a_sc = mod.process_pair("x402_bazaar", cfg, f1, f3, seen2, last2)
    guard_active = (j_tail == "BREAKER" and fresh_tail == [] and len(q_tail) == 30
                    and all(e["quarantine_reason"] == "BREAKER_TRUNCATION_SUSPECT" for e in q_tail)
                    and j_sc == "BREAKER" and len(fresh_sc) > 0)
    return Result(guard_active,
                  "正控制(尾端連續移除)：judged=%s tail_cover=%.4f events.jsonl=%d(期望0) "
                  "隔離檔=%d(期望30，reason 全為 BREAKER_TRUNCATION_SUSPECT)；"
                  "負控制(散布移除)：judged=%s tail_cover=%.4f events.jsonl=%d(期望>0)"
                  % (j_tail, r_tail.get("tail_cover", -1), len(fresh_tail), len(q_tail),
                     j_sc, r_sc.get("tail_cover", -1), len(fresh_sc)))


@check("detect_delistings.breaker_release_manifest_fail_closed", mutate_target="detect_delistings",
       mutate=mut_dd_breaker_manifest_failclosed)
def chk_dd_breaker_manifest_fail_closed(is_mutant):
    """熔斷放行檢查的第二道側證：manifest 讀不到／ok 不為 True／truncated 不為 False／
    parser_version 兩日不同時，一律 fail-closed（不放行，改走隔離檔）。

    三組情境同時驗：(a) 完全沒有 manifest、(b) manifest ok=False、
    (c) manifest truncated=True。三組的移除型態都是「散布」（tail_cover=0），
    所以擋下它們的一定是 manifest 側證，不是截斷指紋。
    mutant 把「讀不到就當通過」放回去，(a) 會被放行，本檢查翻盤成 FAIL。"""
    sandbox = new_sandbox("dd_bmf_mut" if is_mutant else "dd_bmf")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_breaker_manifest_failclosed(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    cfg = mod.SOURCES["x402_bazaar"]
    f1, f2, f3 = _dd_breaker_scatter_fixtures(sandbox, "bmf")
    # (a) 完全不寫 manifest
    seen_a, last_a = set(), {}
    j_a, r_a, fresh_a, _ea, _aa = mod.process_pair("x402_bazaar", cfg, f1, f3, seen_a, last_a)
    ok_a = (j_a == "BREAKER" and fresh_a == [])
    # (b) manifest ok=False
    _dd_manifest(sandbox, ["2030-02-20", "2030-02-22"], ok=False)
    seen_b, last_b = set(), {}
    j_b, r_b, fresh_b, _eb, _ab = mod.process_pair("x402_bazaar", cfg, f1, f3, seen_b, last_b)
    ok_b = (j_b == "BREAKER" and fresh_b == [])
    # (c) manifest truncated=True
    _dd_manifest(sandbox, ["2030-02-20", "2030-02-22"], ok=True, truncated=True)
    seen_c, last_c = set(), {}
    j_c, r_c, fresh_c, _ec, _ac = mod.process_pair("x402_bazaar", cfg, f1, f3, seen_c, last_c)
    ok_c = (j_c == "BREAKER" and fresh_c == [])
    guard_active = ok_a and ok_b and ok_c
    return Result(guard_active,
                  "(a)無 manifest：judged=%s events=%d 放行=%s；(b)ok=False：events=%d 放行=%s；"
                  "(c)truncated=True：events=%d 放行=%s（三者都期望 judged=BREAKER、events=0，"
                  "即 fail-closed 不放行；三組的 tail_cover 皆為 %.4f，確保擋下它們的是 manifest 側證）"
                  % (j_a, len(fresh_a), r_a.get("breaker_release_ok"),
                     len(fresh_b), r_b.get("breaker_release_ok"),
                     len(fresh_c), r_c.get("breaker_release_ok"), r_a.get("tail_cover", -1)))


@check("detect_delistings.breaker_semantics.real_replay", mutate_target="detect_delistings",
       mutate=mut_dd_breaker_not_veto)
def chk_dd_breaker_real_replay(is_mutant):
    """用**真實**的 x402_bazaar 2026-09-06／09-07 快照與真實 manifest 重放那一次熔斷，
    鎖住本輪修復的實際結果：judged=BREAKER、放行、events.jsonl 寫入 1,399 DELISTED＋
    387 LISTED（本檢查用空的 last_delisted 起跑，所以不驗 REAPPEARED；31 筆 REAPPEARED
    需要完整歷史狀態，已在 docs/0907-C-breaker-semantics-report.md §5 用全量重放驗證）。
    快照不存在時（例如未來歷史被輪替）本檢查自動略過並回報 PASS 附註，不製造假失敗。"""
    src_dir = os.path.join(SOURCE_REPO, "track-crypto/data/x402_bazaar")
    man_dir = os.path.join(SOURCE_REPO, "track-crypto/data/_manifest")
    need = [os.path.join(src_dir, "2026-09-06.json.gz"), os.path.join(src_dir, "2026-09-07.json.gz"),
            os.path.join(man_dir, "2026-09-06.json"), os.path.join(man_dir, "2026-09-07.json")]
    if not all(os.path.exists(p) for p in need):
        return Result(not is_mutant, "略過：找不到 2026-09-06／09-07 的真實快照或 manifest（%r）"
                                      % [p for p in need if not os.path.exists(p)])
    sandbox = new_sandbox("dd_brr_mut" if is_mutant else "dd_brr")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_breaker_not_veto(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    cfg = mod.SOURCES["x402_bazaar"]
    dst = os.path.join(sandbox, "track-crypto/data/x402_bazaar")
    os.makedirs(dst, exist_ok=True)
    os.makedirs(os.path.join(sandbox, "track-crypto/data/_manifest"), exist_ok=True)
    for p in need:
        shutil.copy(p, os.path.join(sandbox, os.path.relpath(p, SOURCE_REPO)))
    f_old = os.path.join(dst, "2026-09-06.json.gz")
    f_new = os.path.join(dst, "2026-09-07.json.gz")
    seen, last_delisted = set(), {}
    judged, r, fresh, _e, alert_written = mod.process_pair("x402_bazaar", cfg, f_old, f_new, seen, last_delisted)
    n_del = sum(1 for e in fresh if e["event"] == "DELISTED")
    n_lis = sum(1 for e in fresh if e["event"] == "LISTED")
    marked = sum(1 for e in fresh if e.get("breaker_tripped") is True)
    guard_active = (judged == "BREAKER" and r.get("to_events") is True
                    and n_del == 1399 and n_lis == 387 and marked == len(fresh)
                    and abs(r["removed_rate"] - 8.4328) < 0.001 and r["tail_cover"] == 0.0)
    return Result(guard_active,
                  "真實 2026-09-06->09-07：judged=%s removed_rate=%.4f%%(期望8.4328) "
                  "tail_cover=%.4f(期望0.0) 放行=%s DELISTED=%d(期望1399) LISTED=%d(期望387) "
                  "帶標記=%d/%d ALERT=%s"
                  % (judged, r["removed_rate"], r.get("tail_cover", -1), r.get("to_events"),
                     n_del, n_lis, marked, len(fresh), alert_written))


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



@check("detect_delistings.gate_fail_recorded", mutate_target="detect_delistings",
       mutate=mut_dd_gate_fail_log_dedup)
def chk_dd_gate_fail_recorded(is_mutant):
    """SPEC-gate-dedup.md：GATE_FAIL（完整性守門不通過）除了既有的 changes/<source>/
    YYYY-MM-DD.md 與 CHANGES.md 索引列之外，本輪新增要求額外寫一筆結構化事實到
    track-crypto/data/_gate_fail/gate_skips.jsonl（供 healthcheck.py 告警用，見
    detect_delistings.gate_fail_recorded 姊妹檢查 healthcheck.delist_gate_fail_alert）。
    main() 對完整歷史重新配對計算，若這份新紀錄檔不去重，會重蹈 cex_events.py 的
    gate_skips.jsonl 覆轍——本檢查用 process_pair() 對同一組快照呼叫兩次（模擬同一組
    快照被重新處理兩次，例如隔天重跑時完整歷史裡這一對還在），斷言事實紀錄檔只有
    1 筆；另外用一個 group source 的 GATE_FAIL 驗證 process_group_source_pair()
    也會正確寫入同一份共用檔案（兩條路徑都要接上，不能只接一半）。"""
    sandbox = new_sandbox("dd_gfail_mut" if is_mutant else "dd_gfail")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_gate_fail_log_dedup(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)

    # --- x402_bazaar（process_pair() 路徑）---
    cfg = mod.SOURCES["x402_bazaar"]
    old = x402_snapshot([x402_item("R%d" % i, "d%d" % i) for i in range(100)])
    new_items = [x402_item("R%d" % i, "d%d" % i) for i in range(98)]
    # 2026-09-07 更新：改造假 reported_total（上游自報總數），與 integrity_gate_skips 同一手法
    new = x402_snapshot(new_items, reported_total=110)  # 觸發 GATE_FAIL
    f_old = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-09-01.json.gz"), old)
    f_new = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-09-02.json.gz"), new)
    seen, last_delisted = set(), {}
    gate_fail_seen = mod.load_gate_fail_seen()
    j1, r1, fresh1, e1, a1 = mod.process_pair("x402_bazaar", cfg, f_old, f_new, seen, last_delisted,
                                               gate_fail_seen=gate_fail_seen)
    j2, r2, fresh2, e2, a2 = mod.process_pair("x402_bazaar", cfg, f_old, f_new, seen, last_delisted,
                                               gate_fail_seen=gate_fail_seen)  # 同區間重跑
    log_after_x402 = read_jsonl(mod.GATE_FAIL_LOG)
    x402_rows = [g for g in log_after_x402 if g["source"] == "x402_bazaar"]

    # --- group source（process_group_source_pair() 路徑，證明共用同一份檔案）---
    scfg = {"label": "selftest gate-fail group", "groups": {
        "grp": {"path": ("items",), "shape": "list", "key_field": "id", "desc_field": "name",
                "completeness": "range_check", "range": (90, 110),
                "status_fields": (), "breaker_pct": 50.0, "abs_floor": 5},
    }}
    g_old = [gs_item("id", "R%d" % i, "name", "r%d" % i) for i in range(100)]
    g_new = [gs_item("id", "R%d" % i, "name", "r%d" % i) for i in range(50)]  # 跌破區間下界 [90,110]
    gf_old = write_gz_json(
        os.path.join(sandbox, "track-crypto/data/selftest_gfail_grp/2030-09-01.json.gz"), gs_snapshot({"items": g_old}))
    gf_new = write_gz_json(
        os.path.join(sandbox, "track-crypto/data/selftest_gfail_grp/2030-09-02.json.gz"), gs_snapshot({"items": g_new}))
    g_seen, g_last = set(), {}
    mod.process_group_source_pair("selftest_gfail_grp", scfg, gf_old, gf_new, g_seen, g_last,
                                   gate_fail_seen=gate_fail_seen)
    log_after_group = read_jsonl(mod.GATE_FAIL_LOG)
    group_rows = [g for g in log_after_group if g["source"] == "selftest_gfail_grp"]

    guard_active = (j1 == "GATE_FAIL" and j2 == "GATE_FAIL"
                     and len(x402_rows) == 1 and len(group_rows) == 1)
    return Result(guard_active,
                  "judged 第一次=%s 第二次=%s；x402_bazaar GATE_FAIL 事實紀錄=%d 筆"
                  "（process_pair 呼叫 2 次，期望 1：冪等）；group source GATE_FAIL 事實紀錄=%d 筆"
                  "（期望 1：process_group_source_pair 也會寫入同一份檔案）"
                  % (j1, j2, len(x402_rows), len(group_rows)))


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



@check("cex_events.breaker_marks_unified", mutate_target="cex_events", mutate=mut_ce_breaker_marks)
def chk_ce_breaker_marks(is_mutant):
    """熔斷語意統一（2026-09-07，任務 C）：cex_events.py 的熔斷標記由 2 個欄位擴充為
    4 個，而且要套用到**該組轉換的每一筆事件**（LISTED／DELISTED／STATUS_CHANGED），
    不再只標記 DELISTED——熔斷是「這一組轉換整體異常」的性質，下游要排除一次異常轉換
    時必須能一致地排除全部事件。欄位名與
    track-crypto/scripts/detect_delistings.py 的 breaker_marks() 完全相同。

    正控制 mexc：200→150（25% 移除，超過門檻 max(10, 2)），同時有 1 筆新增與 1 筆狀態
    變化 → 三種事件型別全部要帶齊 4 欄位。
    負控制 bybit：50→49（2% 移除，低於門檻 10）→ 一個欄位都不能帶。
    mutant 把整組標記關掉後，LISTED／STATUS_CHANGED 不再帶標記、DELISTED 也失去
    breaker_tripped 布林旗標，本檢查翻盤成 FAIL。"""
    sandbox = new_sandbox("ce_bmark_mut" if is_mutant else "ce_bmark")
    text = read_source("cex_events")
    if is_mutant:
        text = mut_ce_breaker_marks(text)
    script_path = _install_ce(sandbox, text)
    stable = {ex: [("STABLE1", "ok")] for ex in ALL_EXCHANGES if ex not in ("mexc", "bybit")}
    mexc_old = [("M%d" % i, "1") for i in range(200)]
    mexc_new = ([("M%d" % i, "1") for i in range(149)] + [("M149", "2")]  # M149 狀態變化
                 + [("MNEW", "1")])                                        # 1 筆新增
    bybit_old = [("B%d" % i, "Trading") for i in range(50)]
    bybit_new = [("B%d" % i, "Trading") for i in range(49)]
    old = cex_snapshot(dict(stable, mexc=mexc_old, bybit=bybit_old))
    new = cex_snapshot(dict(stable, mexc=mexc_new, bybit=bybit_new))
    write_gz_json(os.path.join(sandbox, "track-crypto/data/cex_symbols/2030-09-01.json.gz"), old)
    write_gz_json(os.path.join(sandbox, "track-crypto/data/cex_symbols/2030-09-02.json.gz"), new)
    rc, out, err, events, gate_skips = _run_ce(sandbox, script_path)
    need = ("note", "breaker_tripped", "removed_pct", "breaker_threshold")
    mexc_ev = [e for e in events if e["exchange"] == "mexc"]
    mexc_marked = [e for e in mexc_ev
                   if all(k in e for k in need) and e["breaker_tripped"] is True
                   and e["note"] == "anomalous_scale"]
    by_type = {}
    for e in mexc_marked:  # 本檔案沒有 import collections，用字典手動累計（比照既有慣例）
        by_type[e["event"]] = by_type.get(e["event"], 0) + 1
    bybit_ev = [e for e in events if e["exchange"] == "bybit"]
    bybit_marked = [e for e in bybit_ev if any(k in e for k in need)]
    guard_active = (rc == 0 and len(mexc_ev) > 0 and len(mexc_marked) == len(mexc_ev)
                    and by_type.get("DELISTED", 0) == 50 and by_type.get("LISTED", 0) == 1
                    and by_type.get("STATUS_CHANGED", 0) == 1
                    and len(bybit_ev) == 1 and len(bybit_marked) == 0)
    return Result(guard_active,
                  "rc=%d；mexc 事件=%d 全部帶齊4欄位=%d（型別分布=%r，期望 DELISTED=50/"
                  "LISTED=1/STATUS_CHANGED=1）；bybit 事件=%d 帶任一標記=%d（期望 1／0）"
                  % (rc, len(mexc_ev), len(mexc_marked), by_type,
                     len(bybit_ev), len(bybit_marked)))


@check("cex_events.gate_skips_idempotent", mutate_target="cex_events", mutate=mut_ce_gate_dedup)
def chk_ce_gate_dedup(is_mutant):
    """SPEC-gate-dedup.md：main() 對完整歷史重新配對計算（見上面 daily_last_snapshot_only
    等檢查已驗證的既有行為），若 gate_skips.jsonl 寫入不去重，同一天手動重跑
    push.sh（或任何原因重跑 cex_events.py，例如隔天執行時完整歷史裡這一對快照依然
    存在）會把同一筆完整性守門紀錄重複附加，長期線性膨脹（docs/gate-alert-and-reaudit.md
    §5 額外發現 1）。用同一組快照（okx 第二天完全缺席，觸發交易所級守門）連續執行
    cex_events.py 兩次，斷言 gate_skips.jsonl 裡 okx 那一筆不會因為第二次執行而變成
    兩筆。"""
    sandbox = new_sandbox("ce_gdedup_mut" if is_mutant else "ce_gdedup")
    text = read_source("cex_events")
    if is_mutant:
        text = mut_ce_gate_dedup(text)
    script_path = _install_ce(sandbox, text)
    stable = {ex: [("STABLE1", "ok")] for ex in ALL_EXCHANGES if ex != "okx"}
    day1 = cex_snapshot(dict(stable, okx=[("OKXA-USDT", "live"), ("OKXB-USDT", "live")]))
    day2 = cex_snapshot(stable)  # okx 完全缺席（連 key 都沒有）-> 交易所級守門觸發
    write_gz_json(os.path.join(sandbox, "track-crypto/data/cex_symbols/2030-08-01.json.gz"), day1)
    write_gz_json(os.path.join(sandbox, "track-crypto/data/cex_symbols/2030-08-02.json.gz"), day2)
    rc1, out1, err1, events1, gate_skips1 = _run_ce(sandbox, script_path)
    rc2, out2, err2, events2, gate_skips2 = _run_ce(sandbox, script_path)  # 同一個 sandbox 原地重跑
    okx_after_first = [g for g in gate_skips1 if g["exchange"] == "okx"]
    okx_after_second = [g for g in gate_skips2 if g["exchange"] == "okx"]
    guard_active = (rc1 == 0 and rc2 == 0 and len(okx_after_first) == 1 and len(okx_after_second) == 1)
    return Result(guard_active,
                  "rc1=%d rc2=%d；第一次執行後 gate_skips 裡 okx=%d 筆，同區間重跑後 okx=%d 筆 "
                  "(期望皆為 1：不因重跑而重複附加，且完全不刪減既有紀錄)"
                  % (rc1, rc2, len(okx_after_first), len(okx_after_second)))


# ==========================================================================
# scripts/healthcheck.py — 5 條不變量
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


@check("healthcheck.parser_version_skip", mutate_target="healthcheck", mutate=mut_hc_parser_version)
def chk_hc_parser_version(is_mutant):
    """核心不變量（SPEC-healthcheck-parserver.md）：體積比對「今日體積 ÷ 前 7 日中位數」
    （LOW/HIGH＝0.5–3.0×，本次改動完全不動這兩個數字）在 parser_version 於比較視窗內
    改變過時應跳過判定（比照 detect_changes.py 既有原則：parser_version 不同時跳過比對）。
    兩個對照組同時驗證，證明這不是「放寬門檻」：
    (a) 版本全程一致（v1）、今日體積驟降（20 筆→1 筆）→ 應該仍然告警。
    (b) 前 7 日 v1、今日改版為 v2 且體積暴增（20 筆→200 筆）→ 應該跳過（不告警）。
    mutate 關掉「版本不一致就跳過」這個判斷後，(b) 應該從『不告警』翻盤成『告警』，
    (a) 不受影響（本來就沒有經過版本判斷這條路徑，兩邊版本相同）。"""
    sandbox = new_sandbox("hc_pv_mut" if is_mutant else "hc_pv")
    text = read_source("healthcheck")
    if is_mutant:
        text = mut_hc_parser_version(text)
    script_path = install_text(sandbox, "scripts/healthcheck.py", text)

    base_days = ["2030-08-%02d" % d for d in range(1, 8)]   # 7 天基準歷史
    today = "2030-08-08"

    key_a = "synth_pv_a"   # (a) 版本一致，體積驟降 → 應仍告警
    for d in base_days:
        write_gz_json(os.path.join(sandbox, "track-gov/data/%s/%s.json.gz" % (key_a, d)),
                      gov_snapshot(_pv_items(20, "a"), parser_version=1))
    write_gz_json(os.path.join(sandbox, "track-gov/data/%s/%s.json.gz" % (key_a, today)),
                  gov_snapshot(_pv_items(1, "a"), parser_version=1))

    key_b = "synth_pv_b"   # (b) 版本改變＋體積暴增 → 應跳過
    for d in base_days:
        write_gz_json(os.path.join(sandbox, "track-gov/data/%s/%s.json.gz" % (key_b, d)),
                      gov_snapshot(_pv_items(20, "b"), parser_version=1))
    write_gz_json(os.path.join(sandbox, "track-gov/data/%s/%s.json.gz" % (key_b, today)),
                  gov_snapshot(_pv_items(200, "b"), parser_version=2))

    with temp_env(HEALTHCHECK_TODAY=today, HEALTHCHECK_NOW=today + "T12:00:00+00:00"):
        mod = load_module(script_path)
        issues_a, pending_a = [], []
        mod.check_source("track-gov", key_a, issues_a, pending_a)
        issues_b, pending_b = [], []
        mod.check_source("track-gov", key_b, issues_b, pending_b)

    guard_active = (len(issues_a) == 1) and (len(issues_b) == 0)
    return Result(guard_active,
                  "(a)版本一致體積驟降：issues=%d(期望1，仍告警) / "
                  "(b)版本改變+體積暴增：issues=%d(期望0，應跳過)" % (len(issues_a), len(issues_b)))


@check("healthcheck.parser_version_skip.window_refill")
def chk_hc_parser_version_refill(is_mutant):
    """驗證「不是永久豁免」（SPEC-healthcheck-parserver.md 硬性要求：不得新增白名單或
    手動豁免，機制必須完全由資料驅動、自動失效）：parser_version 改變後，一旦比較視窗
    （最近 7 天）內全部重新變成新版本，判定能力必須自動恢復，不需要人工介入。
    時間軸（合成資料，2030-09）：
      day1（改版日，2030-09-01）：v1，20 筆——僅作為「將被擠出視窗」的舊快照，
        本身不參與斷言，純粹用來讓 09-02～09-08 是連續 7 天而非唯一歷史。
      day2~day8（2030-09-02～08，共 7 天）：全部 v2，60 筆，體積回到新基準（穩定值）。
      day9＝today（2030-09-09）：v2，1 筆，體積相對新基準再度驟降。
        此時比較視窗＝day2~day8（最近 7 天，day1 已被擠出視窗），與 today 版本一致（皆
        v2）→ 不應該再跳過，應該恢復告警。
    本檢查沒有獨立 #mutant：驗證的是與 healthcheck.parser_version_skip 完全同一段 guard
    （if any(v != v_today for v in v_prev)）在「視窗版本一致」這個分支的行為——mutate
    版本（if False:）在版本一致的情境下與正常版行為完全相同（兩者都會照跑比值判定），
    掛上 #mutant 不會有任何行為差異可觀察，只會產生誤判的 FAIL；核心 guard 本身的破壞
    驗證已由 healthcheck.parser_version_skip 涵蓋（比照既有慣例：
    cex_events.daily_last_snapshot_only.real_replay 同樣不重複註冊 #mutant）。"""
    sandbox = new_sandbox("hc_pv_refill")
    script_path = install_text(sandbox, "scripts/healthcheck.py", read_source("healthcheck"))
    key = "synth_pv_refill"

    day1 = "2030-09-01"
    refill_days = ["2030-09-%02d" % d for d in range(2, 9)]   # day2..day8，共 7 天
    today = "2030-09-09"

    write_gz_json(os.path.join(sandbox, "track-gov/data/%s/%s.json.gz" % (key, day1)),
                  gov_snapshot(_pv_items(20, "r0"), parser_version=1))
    for i, d in enumerate(refill_days):
        write_gz_json(os.path.join(sandbox, "track-gov/data/%s/%s.json.gz" % (key, d)),
                      gov_snapshot(_pv_items(60, "r%d" % i), parser_version=2))
    write_gz_json(os.path.join(sandbox, "track-gov/data/%s/%s.json.gz" % (key, today)),
                  gov_snapshot(_pv_items(1, "rtoday"), parser_version=2))

    with temp_env(HEALTHCHECK_TODAY=today, HEALTHCHECK_NOW=today + "T12:00:00+00:00"):
        mod = load_module(script_path)
        issues, pending = [], []
        mod.check_source("track-gov", key, issues, pending)

    guard_active = (len(issues) == 1)
    return Result(guard_active,
                  "視窗（最近7天）全數重新變成 v2 後，今日體積相對新基準再度異常："
                  "issues=%d（期望1，證明恢復判定、非永久豁免）" % len(issues))


@check("healthcheck.parser_version_skip.real_replay",
       mutate_target="healthcheck", mutate=mut_hc_parser_version)
def chk_hc_parser_version_real(is_mutant):
    """real-replay（本次派工的關鍵驗收，SPEC-healthcheck-parserver.md）：
    track-gov 三個真實來源 2026-08-28～2026-09-02 的真實歷史快照——VPS 正式資料裡
    確實發生過的一次解析器改版：pres_news parser_version 1→2（官方分頁反解成功，
    15 筆→100 筆，體積 4.32×），同期 fda_clarify（0.45×）／tpe_clarify（0.48×）
    純粹體積下降、parser_version 未變。斷言：pres_news 不再被列為體積異常，而
    fda_clarify／tpe_clarify 仍然被判定為異常——證明這不是放寬 0.5–3.0 門檻，而是
    精準只對「解析器改版」這個情境跳過判定。"""
    sandbox = new_sandbox("hc_pv_real_mut" if is_mutant else "hc_pv_real")
    text = read_source("healthcheck")
    if is_mutant:
        text = mut_hc_parser_version(text)
    script_path = install_text(sandbox, "scripts/healthcheck.py", text)

    dates = ["2026-08-28", "2026-08-29", "2026-08-30", "2026-08-31", "2026-09-01", "2026-09-02"]
    for key in ("pres_news", "fda_clarify", "tpe_clarify"):
        for d in dates:
            rel = "track-gov/data/%s/%s.json.gz" % (key, d)
            install_binary_copy(os.path.join(SOURCE_REPO, rel), sandbox, rel)

    with temp_env(HEALTHCHECK_TODAY="2026-09-02", HEALTHCHECK_NOW="2026-09-02T12:00:00+00:00"):
        mod = load_module(script_path)
        found = {}
        for key in ("pres_news", "fda_clarify", "tpe_clarify"):
            issues, pending = [], []
            mod.check_source("track-gov", key, issues, pending)
            found[key] = issues

    guard_active = (len(found["pres_news"]) == 0
                    and len(found["fda_clarify"]) == 1
                    and len(found["tpe_clarify"]) == 1)
    return Result(guard_active,
                  "real-replay 2026-09-02：pres_news issues=%d(期望0) "
                  "fda_clarify issues=%d(期望1) tpe_clarify issues=%d(期望1)"
                  % (len(found["pres_news"]), len(found["fda_clarify"]), len(found["tpe_clarify"])))



@check("healthcheck.delist_gate_fail_alert", mutate_target="healthcheck",
       mutate=mut_hc_delist_gate_fail_today_filter)
def chk_hc_delist_gate_fail(is_mutant):
    """SPEC-gate-dedup.md：detect_delistings.py 的 GATE_FAIL 要能被看見（產生
    ALERT-DELISTGATE.md，內容可直接行動：來源／子集合、比對區間、前日與當日筆數、
    原因），且異常排除後要能自動消失——不能因為 detect_delistings.py 的 main() 對
    完整歷史重新配對計算，就把歷史上任何一天的 GATE_FAIL 都當成『現在』的問題
    （這正是 gate_skips.jsonl／ALERT-CEXGATE.md 已經解決過的同一類問題，
    check_delist_gate_fail() 用同一個 date==TODAY 過濾手法，見該函式模組層級註解）。"""
    sandbox = new_sandbox("hc_dgf_mut" if is_mutant else "hc_dgf")
    text = read_source("healthcheck")
    if is_mutant:
        text = mut_hc_delist_gate_fail_today_filter(text)
    script_path = install_text(sandbox, "scripts/healthcheck.py", text)
    today, yesterday = "2030-07-20", "2030-07-19"
    gate_fail_rel = "track-crypto/data/_gate_fail/gate_skips.jsonl"
    gate_fail_path = os.path.join(sandbox, gate_fail_rel)
    stale = {"date": yesterday, "source": "x402_bazaar", "group": "x402_bazaar",
             "from_date": "2030-07-18", "reason": "total(100) != len(items)(97)",
             "n_old": 100, "n_new": 97}
    fresh = {"date": today, "source": "selftest_src", "group": "grp",
             "from_date": yesterday, "reason": "n=45 超出實測合理區間 [90, 110]",
             "n_old": 100, "n_new": 45}
    install_text(sandbox, gate_fail_rel,
                 json.dumps(stale, ensure_ascii=False) + "\n" + json.dumps(fresh, ensure_ascii=False) + "\n")
    out_path = os.path.join(sandbox, "ALERT-DELISTGATE.md")

    # 情境 1（觸發）：今天（2030-07-20）有 1 筆 GATE_FAIL（selftest_src），
    # 昨天（07-19，x402_bazaar）的舊紀錄不應出現在今天的告警內容裡。
    with temp_env(HEALTHCHECK_TODAY=today, HEALTHCHECK_NOW=today + "T12:00:00+00:00"):
        mod = load_module(script_path)
        mod.check_delist_gate_fail()
    triggered = os.path.exists(out_path)
    content = open(out_path, encoding="utf-8").read() if triggered else ""
    contains_today_source = "selftest_src" in content
    contains_stale_source = "x402_bazaar" in content
    contains_counts = ("100" in content) and ("45" in content)  # SPEC 明文要求：當日與前日筆數

    # 情境 2（自動消失）：隔天（07-21）沒有新的 GATE_FAIL，但 07-19／07-20 的舊紀錄
    # 仍原封不動留在事實紀錄檔裡 -> ALERT-DELISTGATE.md 應自動消失，且本函式絕不能
    # 動過事實紀錄檔本身（比照 check_cex_gate_skips() 的既有驗證原則）。
    before_log = open(gate_fail_path, encoding="utf-8").read()
    with temp_env(HEALTHCHECK_TODAY="2030-07-21", HEALTHCHECK_NOW="2030-07-21T12:00:00+00:00"):
        mod2 = load_module(script_path)
        mod2.check_delist_gate_fail()
    resolved = not os.path.exists(out_path)
    after_log = open(gate_fail_path, encoding="utf-8").read()
    log_untouched = (before_log == after_log)

    guard_active = (triggered and contains_today_source and not contains_stale_source
                     and contains_counts and resolved and log_untouched)
    return Result(guard_active,
                  "情境1(今天有事，2030-07-20)：觸發=%s 含今日來源=%s 含舊紀錄來源(不應含)=%s "
                  "含前日/當日筆數=%s；情境2(隔天無新紀錄，2030-07-21)：已自動消失=%s "
                  "事實紀錄檔未被動過=%s"
                  % (triggered, contains_today_source, contains_stale_source, contains_counts,
                     resolved, log_untouched))


# ==========================================================================
# track-crypto/scripts/snap_crypto.py — manifest 完整性欄位，4 條不變量
# （SPEC-manifest-fields.md，2026-09-03 新增）
# ==========================================================================

def _install_sc(sandbox, text):
    """compute_manifest_fields() 是純函式（不依賴 __file__ 推算的 BASE/DATA/ADPT 做任何
    I/O），放在對應正式部署路徑下純粹是比照本檔既有慣例、方便閱讀對照，不是必要條件。"""
    return install_text(sandbox, "track-crypto/scripts/snap_crypto.py", text)


@check("snap_crypto.manifest_fields_complete", mutate_target="snap_crypto", mutate=mut_sc_fields_complete)
def chk_sc_fields_complete(is_mutant):
    """核心不變量（SPEC-manifest-fields.md 任務1：manifest 新欄位齊全)。對一個 total_match
    型合成來源（形狀比照 x402_bazaar：{"items":[...], "total":N}）呼叫
    compute_manifest_fields()，斷言 n/n_by_path/complete/completeness_check/
    reported_total/truncated/dup_keys 七個欄位全部存在，且對這組已知輸入算出正確值。"""
    sandbox = new_sandbox("sc_fields_mut" if is_mutant else "sc_fields")
    text = read_source("snap_crypto")
    if is_mutant:
        text = mut_sc_fields_complete(text)
    script_path = _install_sc(sandbox, text)
    mod = load_module(script_path)
    # 用 "x402_bazaar" 當來源 key（而非任意合成名稱）：_KEY_FIELD_HINTS 對它已登記
    # key_field="resource"，dup_keys 才真的會被算出來（而不是因為查無主鍵線索而留 None），
    # 這樣才能同時驗證「欄位齊全」與「值正確」，也讓下面 mut_sc_fields_complete 的
    # 破壞驗證（改掉 dup_keys 這個鍵名）對本檢查的斷言真的有影響。
    data = {"items": [{"resource": "r%d" % i} for i in range(5)], "total": 5}
    result = mod.compute_manifest_fields("x402_bazaar", data)
    required = ("n", "n_by_path", "complete", "completeness_check",
                "reported_total", "truncated", "dup_keys")
    fields_present = all(k in result for k in required)
    values_ok = (fields_present and result["n"] == 5 and result["complete"] is True
                 and result["completeness_check"] == "total_match"
                 and result["reported_total"] == 5 and result["truncated"] is False
                 and result["dup_keys"] == 0)
    guard_active = fields_present and values_ok
    return Result(guard_active,
                  "七欄位齊全=%s；值=%r（期望 n=5/complete=True/check=total_match/"
                  "reported_total=5/truncated=False/dup_keys=0）" % (fields_present, result))


@check("snap_crypto.manifest_fields_real_replay", mutate_target="snap_crypto", mutate=mut_sc_fields_complete)
def chk_sc_fields_real_replay(is_mutant):
    """real-replay：對 x402_bazaar 一份真實歷史快照（VPS 正式資料，唯讀複製）算
    compute_manifest_fields()，斷言 completeness_check==total_match 且 complete=True——
    這是 docs/crypto-detect-design.md 附錄 A.1 已實測驗證過的既知事實（data.total 與
    len(items) 七天全部相符），用真實資料佐證欄位計算邏輯正確，不只是合成資料自圓其說。"""
    sandbox = new_sandbox("sc_real_mut" if is_mutant else "sc_real")
    text = read_source("snap_crypto")
    if is_mutant:
        text = mut_sc_fields_complete(text)
    script_path = _install_sc(sandbox, text)
    src_dir = os.path.join(SOURCE_REPO, "track-crypto/data/x402_bazaar")
    real_files = (sorted(f for f in os.listdir(src_dir) if f.endswith(".json.gz"))
                  if os.path.isdir(src_dir) else [])
    if not real_files:
        return Result(False, "找不到任何真實 x402_bazaar 歷史快照，無法做 real-replay 驗證")
    rel = "track-crypto/data/x402_bazaar/%s" % real_files[-1]
    local_path = install_binary_copy(os.path.join(SOURCE_REPO, rel), sandbox, rel)
    with gzip.open(local_path, "rt", encoding="utf-8") as f:
        real_payload = json.load(f)
    mod = load_module(script_path)
    result = mod.compute_manifest_fields("x402_bazaar", real_payload["data"])
    expect_n = len(real_payload["data"].get("items") or [])
    # dup_keys 也一併斷言（x402_bazaar 在 _KEY_FIELD_HINTS 有登記 key_field="resource"，
    # 真實資料應該算得出一個整數，不是 None）：這樣 mut_sc_fields_complete（改掉
    # "dup_keys" 這個回傳鍵名）才會讓這條 real-replay 檢查也翻盤，不是只有
    # snap_crypto.manifest_fields_complete 那條合成資料檢查測得到。
    guard_active = (result.get("completeness_check") == "total_match"
                    and result.get("complete") is True
                    and result.get("n") == expect_n
                    and result.get("dup_keys") is not None)
    return Result(guard_active,
                  "real-replay(%s)：n=%r(期望%d) complete=%r(期望True) check=%r(期望total_match) "
                  "dup_keys=%r(期望非None)"
                  % (real_files[-1], result.get("n"), expect_n,
                     result.get("complete"), result.get("completeness_check"), result.get("dup_keys")))


@check("snap_crypto.truncated_semantics_match_track_gov",
       mutate_target="snap_crypto", mutate=mut_sc_truncated_default)
def chk_sc_truncated_semantics(is_mutant):
    """核心不變量（SPEC-manifest-fields.md：truncated 語意必須與軌二一致)。truncated
    一律是布林值（不可為 None／缺席），比照軌二 snap_gov.py 對不支援 deadline 的舊式
    adapter 一律預設 truncated=False 的既有慣例。三種輸入分別對應 agent_virtuals
    （data.truncated 同極性）、mcp_smithery（data.is_full 反極性）、以及完全沒有
    旗標的一般來源（必須預設 False，不是 None——這是本檢查要守住的核心行為）。"""
    sandbox = new_sandbox("sc_trunc_mut" if is_mutant else "sc_trunc")
    text = read_source("snap_crypto")
    if is_mutant:
        text = mut_sc_truncated_default(text)
    script_path = _install_sc(sandbox, text)
    mod = load_module(script_path)
    r_same_polarity = mod.compute_manifest_fields(
        "selftest_synth_av", {"items": [{"id": 1}], "truncated": True})
    r_inverted = mod.compute_manifest_fields(
        "selftest_synth_mcp", {"servers": [{"id": 1}], "is_full": False})
    r_absent = mod.compute_manifest_fields(
        "selftest_synth_plain", {"items": [{"id": 1}]})
    checks = {
        "same_polarity_true": r_same_polarity["truncated"] is True,
        "inverted_true": r_inverted["truncated"] is True,
        "absent_defaults_false_not_none": r_absent["truncated"] is False,
        "all_bool_type": all(isinstance(r["truncated"], bool)
                              for r in (r_same_polarity, r_inverted, r_absent)),
    }
    guard_active = all(checks.values())
    return Result(guard_active,
                  "truncated=%r/%r/%r（期望 True/True/False，且三者皆為 bool 非 None）：%r"
                  % (r_same_polarity["truncated"], r_inverted["truncated"],
                     r_absent["truncated"], checks))


@check("healthcheck.truncation_streak_covers_track_crypto",
       mutate_target="healthcheck", mutate=mut_hc_streak)
def chk_hc_streak_track_crypto(is_mutant):
    """核心不變量（SPEC-manifest-fields.md 任務3：確認 healthcheck.py 現有的
    check_truncation_streak() 不修改就能涵蓋軌一)。完全比照既有
    healthcheck.truncation_streak（chk_hc_streak，只測 track-gov／"channels" 鍵名），
    改寫入 track-crypto/data/_manifest/*.json 並用 "sources" 鍵名（軌一 manifest 自
    snap_crypto.py v1 起既有的頂層鍵名，不是本次新增），呼叫同一支未經任何修改的
    check_truncation_streak("track-crypto", issues)——沿用 healthcheck.py 原始碼完全
    不改，只證明它本來就同時支援兩種鍵名（見該函式原始碼
    `m.get("channels") or m.get("sources") or {}`），不是本次新增的相容邏輯。
    破壞驗證沿用既有 mut_hc_streak（同一個函式 check_truncation_streak 的同一個
    門檻判斷式，此處只是換用不同的 track 參數與資料重新驗證一次，不需要新錨點）。"""
    sandbox = new_sandbox("hc_streak_crypto_mut" if is_mutant else "hc_streak_crypto")
    text = read_source("healthcheck")
    if is_mutant:
        text = mut_hc_streak(text)
    script_path = install_text(sandbox, "scripts/healthcheck.py", text)
    dm2, dm1, d0 = "2030-08-01", "2030-08-02", "2030-08-03"
    m_dm2 = {"date": dm2, "sources": {
        "synth_streak2": {"ok": True, "n": 100, "secs": 8, "truncated": False},
        "synth_streak1": {"ok": True, "n": 100, "secs": 8, "truncated": False}}}
    m_dm1 = {"date": dm1, "sources": {
        "synth_streak2": {"ok": True, "n": 30, "secs": 10, "truncated": True, "items_fetched": 30},
        "synth_streak1": {"ok": True, "n": 98, "secs": 8, "truncated": False}}}
    m_d0 = {"date": d0, "sources": {
        "synth_streak2": {"ok": True, "n": 25, "secs": 12, "truncated": True, "items_fetched": 25},
        "synth_streak1": {"ok": True, "n": 20, "secs": 12, "truncated": True, "items_fetched": 20}}}
    for d, m in [(dm2, m_dm2), (dm1, m_dm1), (d0, m_d0)]:
        install_text(sandbox, "track-crypto/data/_manifest/%s.json" % d, json.dumps(m))
    with temp_env(HEALTHCHECK_TODAY=d0, HEALTHCHECK_NOW=d0 + "T12:00:00+00:00"):
        mod = load_module(script_path)
        issues = []
        mod.check_truncation_streak("track-crypto", issues)
    names = [a for a, b in issues]
    guard_active = ("track-crypto/synth_streak2" in names) and ("track-crypto/synth_streak1" not in names)
    return Result(guard_active,
                  "軌一（sources 鍵名）連續2天截斷來源 issues=%r "
                  "(期望含 synth_streak2，不含僅1天的 synth_streak1；證明 healthcheck.py "
                  "未修改也能涵蓋軌一)" % (names,))


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


def _extract_md_section(text, heading_prefix):
    """從 Markdown 文字裡擷取「以 heading_prefix 開頭的那一段」：從該行開始，
    到下一個以 `## ` 開頭的行（或檔尾）為止。找不到該標題就回傳空字串。
    供 daily_report.notice_surfaced_not_anomaly 精確核對『某個來源字串出現在
    哪一個區塊』，而不只是「整份 REPORT.md 裡有沒有出現」（那樣測不出來源被
    放錯區塊的錯誤）。"""
    lines = text.splitlines()
    start = None
    for i, l in enumerate(lines):
        if l.startswith(heading_prefix):
            start = i
            break
    if start is None:
        return ""
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return "\n".join(lines[start:end])


@check("daily_report.notice_surfaced_not_anomaly", mutate_target="daily_report", mutate=mut_dr_notice_block)
def chk_dr_notice_surfaced(is_mutant):
    """SPEC-notice-and-dr.md 任務一驗收：healthcheck.check_source() 對
    parser_version 於比較視窗內改變過的來源印出的 NOTICE（見
    healthcheck.parser_version_skip 系列檢查），必須經 daily_report.py 的
    build_health_issues() 擷取後，出現在 REPORT.md『暫不判定／基準重建中』
    資訊區塊，且不得算進異常數、不得出現在 healthcheck.py 產生的 ALERT.md。
    兩個對照組同時驗證，證明不是『把所有東西都塞進資訊區塊』或『資訊區塊/
    異常清單分類錯亂』：
      (a) synth_notice：parser_version 7 天比較視窗內 1→2（前 4 天 v1、後 3 天
          已是 v2，藉此同時驗證『第 X/7 天』的 X 不是恆為 0）＋今日體積暴增
          （若未跳過，20→200 筆遠超 0.5–3.0x 門檻）→ 應只出現在 REPORT.md
          資訊區塊（含正確的「1 → 2」與「第 3／7 天」字樣），不得出現在
          ALERT.md 或 REPORT.md〈異常摘要〉。
      (b) synth_real_anomaly：parser_version 全程一致（v1）、今日體積驟降
          （20→1 筆）→ 應正常出現在 ALERT.md 與 REPORT.md〈異常摘要〉，不得
          出現在資訊區塊。
    sandbox 刻意把 timestamps/、track-crypto/adapters/ 建成空目錄、track-crypto
    manifest 建成空 sources，讓 healthcheck.py 的其他檢查（check_timestamps／
    track-crypto 這一側的 check_manifest／check_source fallback 清單）不產生
    任何額外雜訊，藉此把「issues 應恰好只有 1 筆（synth_real_anomaly）」也一併
    斷言，非僅寬鬆判斷 >=n。
    mutate（mut_dr_notice_block）把資訊區塊來源清單改成永遠清空，模擬『REPORT.md
    資訊區塊接線被誤刪』的迴歸：(a) 應該從『出現在資訊區塊』翻盤成『沒有出現』，
    其餘斷言（ALERT.md／異常摘要／issues 筆數）不受影響（那些由 healthcheck.py
    與 build_health_issues() 的既有邏輯決定，不是本次新增的接線）。"""
    sandbox = new_sandbox("dr_notice_mut" if is_mutant else "dr_notice")
    dr_text = read_source("daily_report")
    if is_mutant:
        dr_text = mut_dr_notice_block(dr_text)
    install_text(sandbox, "scripts/healthcheck.py", read_source("healthcheck"))
    dr_path = install_text(sandbox, "scripts/daily_report.py", dr_text)
    hc_path = os.path.join(sandbox, "scripts/healthcheck.py")

    os.makedirs(os.path.join(sandbox, "timestamps"), exist_ok=True)
    os.makedirs(os.path.join(sandbox, "track-crypto", "adapters"), exist_ok=True)
    install_fake_adapter(sandbox, "track-gov", "synth_notice", "Synthetic Notice Source")
    install_fake_adapter(sandbox, "track-gov", "synth_real_anomaly", "Synthetic Real Anomaly Source")

    hist_days = ["2030-08-%02d" % d for d in range(21, 28)]   # 7 天比較視窗
    today = "2030-08-28"

    # synth_notice：前 4 天 v1、後 3 天已是 v2（驗證「第 3/7 天」而非只有 0/7 這種
    # 邊界值），今日 v2 且體積暴增（若未跳過會遠超 0.5–3.0x 門檻，20 -> 200 筆）。
    for i, d in enumerate(hist_days):
        pv = 1 if i < 4 else 2
        write_gz_json(os.path.join(sandbox, "track-gov/data/synth_notice/%s.json.gz" % d),
                      gov_snapshot(_pv_items(20, "n%d" % i), parser_version=pv))
    write_gz_json(os.path.join(sandbox, "track-gov/data/synth_notice/%s.json.gz" % today),
                  gov_snapshot(_pv_items(200, "ntoday"), parser_version=2))

    # synth_real_anomaly：版本全程一致（v1），今日體積驟降（20 -> 1 筆）→ 真異常。
    for i, d in enumerate(hist_days):
        write_gz_json(os.path.join(sandbox, "track-gov/data/synth_real_anomaly/%s.json.gz" % d),
                      gov_snapshot(_pv_items(20, "r%d" % i), parser_version=1))
    write_gz_json(os.path.join(sandbox, "track-gov/data/synth_real_anomaly/%s.json.gz" % today),
                  gov_snapshot(_pv_items(1, "rtoday"), parser_version=1))

    gov_manifest = {"date": today, "channels": {
        "synth_notice": {"ok": True, "n": 200, "bytes": 1, "secs": 1.0, "attempts": 1, "truncated": False},
        "synth_real_anomaly": {"ok": True, "n": 1, "bytes": 1, "secs": 1.0, "attempts": 1, "truncated": False},
    }}
    crypto_manifest = {"date": today, "sources": {}}   # 空 track-crypto，避免無關雜訊
    install_text(sandbox, "track-gov/data/_manifest/%s.json" % today, json.dumps(gov_manifest))
    install_text(sandbox, "track-crypto/data/_manifest/%s.json" % today, json.dumps(crypto_manifest))

    env = {"HEALTHCHECK_TODAY": today, "HEALTHCHECK_NOW": today + "T12:00:00+00:00"}
    rc_hc, out_hc, err_hc = run_py(hc_path, cwd=sandbox, extra_env=env)
    rc_dr, out_dr, err_dr = run_py(dr_path, cwd=sandbox, extra_env=env)

    alert_path = os.path.join(sandbox, "ALERT.md")
    alert_text = open(alert_path, encoding="utf-8").read() if os.path.exists(alert_path) else ""
    report_path = os.path.join(sandbox, "REPORT.md")
    report_text = open(report_path, encoding="utf-8").read() if os.path.exists(report_path) else ""

    notice_section = _extract_md_section(report_text, "## 暫不判定／基準重建中")
    summary_section = _extract_md_section(report_text, "## 異常摘要")

    # 直接重呼叫 build_health_issues()（與 REPORT.md 用的同一支函式）取得 issues 筆數，
    # 不必再解析 REPORT.md 的「一句話結論」文字，避免額外一層文字解析誤差。
    # 注意：load_module()（動態 import daily_report.py）必須放在 temp_env() 區塊「裡面」——
    # daily_report.py import 時會連帶 import healthcheck.py，healthcheck.py 的
    # NOW_UTC/TODAY 是模組載入當下讀一次環境變數的模組層級常數，不是每次呼叫函式時
    # 重讀；load_module() 放在 with 區塊外會讀到當下真實系統時間，而非本檢查指定的
    # 合成日期（比照 chk_hc_parser_version 等既有檢查的正確寫法）。
    with temp_env(HEALTHCHECK_TODAY=today, HEALTHCHECK_NOW=today + "T12:00:00+00:00"):
        mod = load_module(dr_path)
        issues2, pending2, notices2 = mod.build_health_issues()
    issues_ok = (issues2 is not None and len(issues2) == 1
                 and issues2[0][0] == "track-gov/synth_real_anomaly")

    checks = {
        "rc_hc=0": rc_hc == 0,
        "rc_dr=0": rc_dr == 0,
        "issues恰好1筆且為synth_real_anomaly": issues_ok,
        "ALERT.md不含synth_notice": "synth_notice" not in alert_text,
        "ALERT.md含synth_real_anomaly": "track-gov/synth_real_anomaly" in alert_text,
        "資訊區塊含synth_notice": "track-gov/synth_notice" in notice_section,
        "資訊區塊含版本變化1→2": "1 → 2" in notice_section,
        "資訊區塊含進度第3／7天": "第 3／7 天" in notice_section,
        "資訊區塊不含synth_real_anomaly": "synth_real_anomaly" not in notice_section,
        "異常摘要含synth_real_anomaly": "track-gov/synth_real_anomaly" in summary_section,
        "異常摘要不含synth_notice": "synth_notice" not in summary_section,
    }
    guard_active = all(checks.values())
    failed = [k for k, v in checks.items() if not v]
    detail = "rc_hc=%d rc_dr=%d issues=%r; %s" % (
        rc_hc, rc_dr, (issues2 if issues2 is not None else None),
        ("全部通過" if not failed else "未通過：" + "、".join(failed)))
    return Result(guard_active, detail)


@check("daily_report.window_guard_surfaced_in_change_detection_section",
       mutate_target="daily_report", mutate=mut_dr_window_guard_block)
def chk_dr_window_guard_surfaced(is_mutant):
    """SPEC-window-guard.md 任務四驗收：detect_changes.py v4 對「視窗大小顯著變化」
    印出的主控台行（下架欄位「視窗變動，不判定」＋行尾 marker，比照既有截斷格式），
    必須經 daily_report.py 的 CHANGE_LINE_RE／parse_change_detection_rows() 解析後，
    出現在 REPORT.md『## 變動偵測』區塊的一行彙總警語（比照既有 truncated_keys 的
    既有寫法），且與正常改寫列、既有截斷列並存時三者互不干擾（同一批 detect.log
    裡混合一般列、截斷列、視窗變動列，逐一驗證解析結果）。

    評估後刻意不併入 render_notice_section() 的「暫不判定／基準重建中」資訊區塊
    （daily_report.notice_surfaced_not_anomaly 涵蓋的機制）：那個區塊資料來源是
    build_health_issues() 呼叫 healthcheck.check_source() 時擷取的 NOTICE 文字，
    是體積檢查專用的既有機制；detect_changes.py 的視窗變動跳過是完全獨立的判定
    （不同程式、不同資料），本檢查驗證的是延伸既有『## 變動偵測』區塊
    （truncated_keys 那一套）的做法，理由詳見 scripts/daily_report.py 檔頭
    「2026-09-04 改版」說明。

    mutate（mut_dr_window_guard_block）把 window_changed_keys 永遠清空，模擬
    『彙總提示接線被誤刪』的迴歸：應該從『彙總提示出現』翻盤成『沒有出現』，
    其餘斷言（一般列、截斷列的解析與彙總）不受影響。"""
    sandbox = new_sandbox("dr_wg_mut" if is_mutant else "dr_wg")
    dr_text = read_source("daily_report")
    if is_mutant:
        dr_text = mut_dr_window_guard_block(dr_text)
    dr_path = install_text(sandbox, "scripts/daily_report.py", dr_text)

    # 直接用 detect_changes.py 目前（v4）版本的 _skip_reason_desc()，取得「視窗變動」
    # 這個跳過原因對應的下架欄位文字與行尾 marker，避免本檢查自己手key一份文字、
    # 跟正式程式碼各算各的（本檔案已因這類問題吃過虧，見 daily_report.py 檔頭
    # 「2026-09-03 改版」引用的 docs/healthcheck-parserver-report.md 第 10 節）。
    dc_mod = load_module(install_text(sandbox, "scripts/detect_changes.py", read_source("detect_changes")))
    wc_desc, wc_marker = dc_mod._skip_reason_desc("window_change")
    trunc_desc, trunc_marker = dc_mod._skip_reason_desc("truncated")
    assert wc_desc == "視窗變動，不判定" and trunc_desc == "截斷，不判定"  # 前提假設，非本檢查主張

    log_lines = [
        "normal_src: 2030-10-01→2030-10-02 改寫1 下架2 新增3",
        "trunc_src: 2030-10-01→2030-10-02 改寫0 下架%s 新增1%s" % (trunc_desc, trunc_marker),
        "window_src: 2030-10-01→2030-10-02 改寫1 下架%s 新增3%s" % (wc_desc, wc_marker),
        "SUMMARY changed=2 removed=2",
    ]
    install_text(sandbox, "logs/detect.log", "\n".join(log_lines) + "\n")

    mod = load_module(dr_path)
    block, _ = mod.parse_detect_log_last_round(os.path.join(sandbox, "logs/detect.log"))
    rows, skipped, parser_skipped, summary = mod.parse_change_detection_rows(block)
    row_by_key = {r["來源"]: r for r in rows}
    parse_ok = (
        len(rows) == 3
        and row_by_key["normal_src"]["下架"] == 2 and not row_by_key["normal_src"]["視窗變動"]
        and row_by_key["trunc_src"]["截斷"] and not row_by_key["trunc_src"]["視窗變動"]
        and row_by_key["window_src"]["視窗變動"] and not row_by_key["window_src"]["截斷"]
        and row_by_key["window_src"]["下架"] == "N/A（視窗變動）"
    )

    section_text = mod.build_change_detection_section()
    surfaced = ("window_src" in section_text and "視窗大小顯著變化" in section_text)
    # 截斷彙總（既有機制）與一般列不應受影響，同一次呼叫一併確認沒有被本次修改波及。
    trunc_still_ok = ("trunc_src" in section_text and "快照截斷" in section_text)

    guard_active = parse_ok and trunc_still_ok and surfaced
    return Result(guard_active,
                  "parse_ok=%s trunc_still_ok=%s window_surfaced=%s rows=%r (期望三類列都能正確解析、"
                  "彙總提示三者互不干擾)"
                  % (parse_ok, trunc_still_ok, surfaced,
                     {k: (v["下架"], v["截斷"], v["視窗變動"]) for k, v in row_by_key.items()}))


# ==========================================================================
# track-crypto/scripts/detect_delistings.py 第三階段新增 — 5 條新檢查
# （specs/SPEC-detect-phase3.md，本機 docs/detect-phase3-report.md；
#  agent_virtuals／crypto_project_liveness／oracle_feed_directory.pyth
#  三個來源新增/沿用的完整性判定機制，逐項見各檢查 docstring）
# ==========================================================================

@check("detect_delistings.group_tolerant_total_match", mutate_target="detect_delistings",
       mutate=mut_dd_group_tolerant_total_match)
def chk_dd_group_tolerant_total_match(is_mutant):
    """第三階段新增（docs/detect-phase3-report.md §2.1）：completeness_group()
    新增 tolerant_total_match 分支（agent_virtuals 專用）。嚴格相等
    （total_match）在這個來源永遠不通過（自報總數與可分頁筆數恆有約 0.05%
    落差，屬預期現象），改用「truncated 旗標必須明確為 False」+「相對誤差
    ≤ tolerance_pct」兩條件都通過才算完整。用 3 組情境驗證：
      (a) 落差 0.2%（在容忍度 0.3% 內）且 truncated=False → 應通過；
      (b) 落差同樣 0.2%，但 truncated=True → 仍要擋下（旗標優先權最高，
          不是只看誤差百分比）；
      (c) truncated=False，但落差約 0.99%（超過容忍度）→ 應擋下。
    """
    sandbox = new_sandbox("dd_gtol_mut" if is_mutant else "dd_gtol")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_group_tolerant_total_match(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg = {"path": ("items",), "shape": "list", "key_field": "id", "desc_field": "name",
            "completeness": "tolerant_total_match", "total_field": "total_reported",
            "truncated_field": "truncated", "tolerance_pct": 0.3,
            "status_fields": (), "breaker_pct": 50.0, "abs_floor": 1000}
    items_1000 = [gs_item("id", i, "name", "n%d" % i) for i in range(1000)]

    def mkdata(total_reported, truncated):
        return {"items": items_1000, "total_reported": total_reported, "truncated": truncated}

    ok_a, _, reason_a = mod.completeness_group(mkdata(1002, False), gcfg)   # 0.2% 落差, 未截斷
    ok_b, _, reason_b = mod.completeness_group(mkdata(1002, True), gcfg)    # 0.2% 落差, 但截斷
    ok_c, _, reason_c = mod.completeness_group(mkdata(1010, False), gcfg)   # 約 0.99% 落差, 未截斷

    guard_active = (ok_a is True) and (ok_b is False) and (ok_c is False)
    return Result(guard_active,
                  "(a)gap=0.20%%,truncated=False->ok=%r(期望True) "
                  "(b)gap=0.20%%,truncated=True->ok=%r(期望False，旗標優先) "
                  "(c)gap=0.99%%,truncated=False->ok=%r(期望False，超容忍度) reasons=%r/%r/%r"
                  % (ok_a, ok_b, ok_c, reason_a, reason_b, reason_c))


@check("detect_delistings.group_tolerant_total_match.real_replay", mutate_target="detect_delistings",
       mutate=mut_dd_group_tolerant_total_match)
def chk_dd_group_tolerant_total_match_real_replay(is_mutant):
    """real-replay：agent_virtuals 真實歷史快照（VPS 正式資料，唯讀複製）
    2026-08-29→08-30（兩側皆 data.truncated=True，時間預算截斷造成的真實
    假下架風險，落差 48.96%~59.84%，added=8978/removed=0）與
    2026-09-03→09-04（兩側皆 truncated=False，乾淨資料，落差穩定約 0.05%），
    證明 tolerant_total_match 對前者判 GATE_FAIL、對後者判 NORMAL，
    不是只在合成資料上正確。用真實 GROUP_SOURCES["agent_virtuals"] 設定
    （非另建合成 gcfg），一併驗證正式設定值本身正確。"""
    sandbox = new_sandbox("dd_gtol_real_mut" if is_mutant else "dd_gtol_real")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_group_tolerant_total_match(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg = mod.GROUP_SOURCES["agent_virtuals"]["groups"]["_items"]
    src_dir = os.path.join(SOURCE_REPO, "track-crypto/data/agent_virtuals")
    need = ["2026-08-29.json.gz", "2026-08-30.json.gz", "2026-09-03.json.gz", "2026-09-04.json.gz"]
    if not all(os.path.exists(os.path.join(src_dir, n)) for n in need):
        return Result(False, "找不到真實 agent_virtuals 歷史快照，無法做 real-replay 驗證")
    paths = {n: install_binary_copy(os.path.join(src_dir, n), sandbox, n) for n in need}

    def _judge(name_old, name_new):
        j_old, j_new = mod.load(paths[name_old]), mod.load(paths[name_new])
        r = mod.compare_group("agent_virtuals", "_items", gcfg, j_old["data"], j_new["data"])
        return mod.judge(r, gcfg), r

    judged_bad, r_bad = _judge("2026-08-29.json.gz", "2026-08-30.json.gz")
    judged_good, r_good = _judge("2026-09-03.json.gz", "2026-09-04.json.gz")
    guard_active = (judged_bad == "GATE_FAIL" and judged_good == "NORMAL")
    return Result(guard_active,
                  "real-replay 08-29->08-30(兩側truncated=True，落差48.96%%~59.84%%)：judged=%s(期望GATE_FAIL)；"
                  "09-03->09-04(兩側truncated=False，落差~0.05%%)：judged=%s(期望NORMAL，removed=%d)"
                  % (judged_bad, judged_good, len(r_good["removed_keys"])))


@check("detect_delistings.group_composite_key_casefold", mutate_target="detect_delistings",
       mutate=mut_dd_group_composite_key_casefold)
def chk_dd_group_composite_key_casefold(is_mutant):
    """第三階段新增（docs/detect-phase3-report.md §2.2）：dedup() 新增
    key_field 為 tuple 的複合鍵支援，crypto_project_liveness 用 (name, date)
    複合鍵，字串成分正規化小寫。用真實案例的合成版本驗證：同一筆事件只有
    name 大小寫被上游修正（"Saturn"->"SATURN"），date/其餘欄位不變，複合鍵
    若不忽略大小寫會被誤判為「一筆消失＋一筆新增」——這正是零假消失驗收
    要防的情境。同時驗證複合鍵集合差本身仍正確：真正新增的獨立事件（New）
    不受影響，另一筆完全沒變的事件（Other）也不受影響。"""
    sandbox = new_sandbox("dd_gckey_mut" if is_mutant else "dd_gckey")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_group_composite_key_casefold(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg = {"path": ("hacks",), "shape": "list", "key_field": ("name", "date"), "desc_field": "name",
            "completeness": "total_match", "total_fields": ("count",),
            "status_fields": (), "breaker_pct": 50.0, "abs_floor": 1000}
    day1 = [
        {"name": "Saturn", "date": 1715040000},
        {"name": "Other", "date": 1600000000},
    ]
    # 大小寫修正（同 date，同一筆事件）＋ Other 不變 ＋ New 是真正新增
    day2 = [
        {"name": "SATURN", "date": 1715040000},
        {"name": "Other", "date": 1600000000},
        {"name": "New", "date": 1700000000},
    ]
    data1 = {"hacks": day1, "count": len(day1)}
    data2 = {"hacks": day2, "count": len(day2)}
    r = mod.compare_group("selftest_liveness_src", "grp", gcfg, data1, data2)
    judged = mod.judge(r, gcfg)
    guard_active = (judged == "NORMAL" and len(r["removed_keys"]) == 0
                    and len(r["added_keys"]) == 1)
    return Result(guard_active,
                  "Saturn->SATURN(同 date，純大小寫修正)＋Other不變＋New新增；"
                  "removed=%d(期望0) added=%d(期望1，僅New) judged=%s(期望NORMAL；"
                  "若未忽略大小寫，removed/added 應各多出 1 筆 Saturn/SATURN)"
                  % (len(r["removed_keys"]), len(r["added_keys"]), judged))


@check("detect_delistings.group_composite_key_casefold.real_replay", mutate_target="detect_delistings",
       mutate=mut_dd_group_composite_key_casefold)
def chk_dd_group_composite_key_casefold_real_replay(is_mutant):
    """real-replay：crypto_project_liveness 真實歷史快照（VPS 正式資料，
    唯讀複製）2026-08-28→08-29 驗證：真實發生過的 Saturn->SATURN 大小寫修正
    （date=1715040000 不變，見報告 §2.2 完整實測數字）用複合鍵比對後不會
    出現在 removed_keys／added_keys，但同一天真正新增的 CCC（date=1787788800）
    仍正確出現在 added_keys。用真實 GROUP_SOURCES["crypto_project_liveness"]
    設定（非另建合成 gcfg）。"""
    sandbox = new_sandbox("dd_gckey_real_mut" if is_mutant else "dd_gckey_real")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_group_composite_key_casefold(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg = mod.GROUP_SOURCES["crypto_project_liveness"]["groups"]["_hacks"]
    src_dir = os.path.join(SOURCE_REPO, "track-crypto/data/crypto_project_liveness")
    need = ["2026-08-28.json.gz", "2026-08-29.json.gz"]
    if not all(os.path.exists(os.path.join(src_dir, n)) for n in need):
        return Result(False, "找不到真實 crypto_project_liveness 歷史快照，無法做 real-replay 驗證")
    f_old = install_binary_copy(os.path.join(src_dir, need[0]), sandbox, "old.json.gz")
    f_new = install_binary_copy(os.path.join(src_dir, need[1]), sandbox, "new.json.gz")
    j_old, j_new = mod.load(f_old), mod.load(f_new)
    r = mod.compare_group("crypto_project_liveness", "_hacks", gcfg, j_old["data"], j_new["data"])
    judged = mod.judge(r, gcfg)
    saturn_removed = any(isinstance(k, str) and k.split("\x1f")[0].lower() == "saturn"
                          for k in r["removed_keys"])
    saturn_added = any(isinstance(k, str) and k.split("\x1f")[0].lower() == "saturn"
                        for k in r["added_keys"])
    ccc_added = any(isinstance(k, str) and k.split("\x1f")[0].lower() == "ccc"
                     for k in r["added_keys"])
    guard_active = (judged == "NORMAL" and not saturn_removed and not saturn_added and ccc_added)
    return Result(guard_active,
                  "real-replay 08-28->08-29：judged=%s(期望NORMAL) removed含saturn=%r(期望False) "
                  "added含saturn=%r(期望False) added含ccc=%r(期望True) removed=%d added=%d"
                  % (judged, saturn_removed, saturn_added, ccc_added,
                     len(r["removed_keys"]), len(r["added_keys"])))


@check("detect_delistings.rename_reconcile", mutate_target="detect_delistings",
       mutate=mut_dd_rename_reconcile)
def chk_dd_rename_reconcile(is_mutant):
    """第四階段新增（2026-09-07 任務 B，docs/0907-B-rename-key-report.md §2、§5）：
    compare_group() 的上游改名抵銷層。用真實案例的合成版本驗證：同一個專案
    （defillamaId="249"）的兩筆歷史事件（date 不同）被上游同時改名
    "Stake DAO"->"Stake DAO Yield"，複合主鍵 (name,date) 會整組換掉，
    若沒有抵銷層就是 2 筆假消失＋2 筆假新增。

    同時驗證抵銷層沒有把不該抵銷的東西一起吃掉：
      - 完全沒變的 Other（沒有 defillamaId，走 stable_identity()->None 的
        fail-closed 路徑）不受影響；
      - 真正新增的 New（全新 defillamaId）仍然正確出現在 added_keys。"""
    sandbox = new_sandbox("dd_rename_mut" if is_mutant else "dd_rename")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_rename_reconcile(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg = {"path": ("hacks",), "shape": "list", "key_field": ("name", "date"), "desc_field": "name",
            "completeness": "total_match", "total_fields": ("count",),
            "status_fields": (), "breaker_pct": 50.0, "abs_floor": 1000,
            "stable_id_fields": ("defillamaId", "date")}
    day1 = [
        {"name": "Stake DAO", "date": 1773273600, "defillamaId": "249"},
        {"name": "Stake DAO", "date": 1779840000, "defillamaId": "249"},
        {"name": "Other", "date": 1600000000, "defillamaId": None},
    ]
    day2 = [
        {"name": "Stake DAO Yield", "date": 1773273600, "defillamaId": "249"},
        {"name": "Stake DAO Yield", "date": 1779840000, "defillamaId": "249"},
        {"name": "Other", "date": 1600000000, "defillamaId": None},
        {"name": "New", "date": 1700000000, "defillamaId": "999"},
    ]
    data1 = {"hacks": day1, "count": len(day1)}
    data2 = {"hacks": day2, "count": len(day2)}
    r = mod.compare_group("selftest_liveness_src", "grp", gcfg, data1, data2)
    judged = mod.judge(r, gcfg)
    new_only = [k for k in r["added_keys"] if isinstance(k, str) and k.startswith("new\x1f")]
    guard_active = (judged == "NORMAL" and len(r["removed_keys"]) == 0
                     and len(r["added_keys"]) == 1 and len(new_only) == 1
                     and len(r["renamed_pairs"]) == 2)
    return Result(guard_active,
                  "Stake DAO->Stake DAO Yield(同 defillamaId=249，兩筆不同 date)＋Other不變＋New新增；"
                  "removed=%d(期望0) added=%d(期望1，僅New) renamed=%d(期望2) judged=%s(期望NORMAL；"
                  "若抵銷層失效，removed/added 應各多出 2 筆 stake dao)"
                  % (len(r["removed_keys"]), len(r["added_keys"]), len(r["renamed_pairs"]), judged))


@check("detect_delistings.rename_reconcile_added_guard", mutate_target="detect_delistings",
       mutate=mut_dd_rename_reconcile_added_guard)
def chk_dd_rename_reconcile_added_guard(is_mutant):
    """第四階段新增（2026-09-07 任務 B）：鎖住抵銷層最危險的失效模式——
    把一筆**真實的消失**跟一筆「前日就已經在清單裡、本次並非新增」的紀錄
    配對而無聲吃掉。

    情境（合成）：前日有 Alpha 與 Beta 兩筆，兩者共用同一個穩定識別
    （defillamaId="9"、同 date，真實資料裡對應 Gamma／OcelotDex／Merlin 那種
    「同專案同日期兩起不同攻擊」的既有重複型態）；當日 Alpha 真的消失、Beta
    原樣留著。Beta 不在 added_keys 裡，所以**不可以**拿來抵銷 Alpha 的消失，
    Alpha 必須照常寫 DELISTED。"""
    sandbox = new_sandbox("dd_rename_guard_mut" if is_mutant else "dd_rename_guard")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_rename_reconcile_added_guard(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg = {"path": ("hacks",), "shape": "list", "key_field": ("name", "date"), "desc_field": "name",
            "completeness": "total_match", "total_fields": ("count",),
            "status_fields": (), "breaker_pct": 50.0, "abs_floor": 1000,
            "stable_id_fields": ("defillamaId", "date")}
    day1 = [
        {"name": "Alpha", "date": 1600000000, "defillamaId": "9"},
        {"name": "Beta", "date": 1600000000, "defillamaId": "9"},
    ]
    day2 = [
        {"name": "Beta", "date": 1600000000, "defillamaId": "9"},
    ]
    data1 = {"hacks": day1, "count": len(day1)}
    data2 = {"hacks": day2, "count": len(day2)}
    r = mod.compare_group("selftest_liveness_src", "grp", gcfg, data1, data2)
    judged = mod.judge(r, gcfg)
    alpha_removed = any(isinstance(k, str) and k.startswith("alpha\x1f") for k in r["removed_keys"])
    guard_active = (judged == "NORMAL" and alpha_removed and len(r["removed_keys"]) == 1
                     and len(r["added_keys"]) == 0 and len(r["renamed_pairs"]) == 0)
    return Result(guard_active,
                  "Alpha 真消失、Beta(同 defillamaId=9 同 date，前日就存在、本次非新增)留著；"
                  "removed=%d(期望1) removed含alpha=%r(期望True) added=%d(期望0) renamed=%d(期望0) "
                  "judged=%s(期望NORMAL；若 added-set 條件失效，Alpha 的真實消失會被 Beta 抵銷掉)"
                  % (len(r["removed_keys"]), alpha_removed, len(r["added_keys"]),
                     len(r["renamed_pairs"]), judged))


@check("detect_delistings.rename_reconcile.real_replay", mutate_target="detect_delistings",
       mutate=mut_dd_rename_reconcile)
def chk_dd_rename_reconcile_real_replay(is_mutant):
    """real-replay：crypto_project_liveness 真實歷史快照（VPS 正式資料，唯讀複製）
    用真實 GROUP_SOURCES 設定（非另建合成 gcfg）同時驗證兩件事：

    (a) 2026-09-05→09-06：真實發生過的 Stake DAO -> Stake DAO Yield 改名
        （defillamaId 兩天都是 "249"，date 1773273600／1779840000 兩筆）不再出現在
        removed_keys／added_keys，改記在 renamed_pairs；同一天真正新增的
        2 筆（Dream Health Chain／Reddio RedSonic）仍正確留在 added_keys。
        這正是本輪要修的 4 筆假事件（docs/0907-events-audit-0904-0907.md §5.5）。

    (b) 2026-09-01→09-02：真實發生過的**唯一一次真實消失**（MORE Markets，
        defillamaId="5320"，見 docs/detect-phase3-report.md §2.2）**必須原樣保留**
        為 1 筆 removed——抵銷層不可以把真實消失一起吃掉。這一半在突變後仍會通過，
        刻意與 (a) 綁在同一條檢查裡，讓「修好假事件」與「不吃掉真事件」是同一個
        驗收單位，不會日後被人各自放寬。"""
    sandbox = new_sandbox("dd_rename_real_mut" if is_mutant else "dd_rename_real")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_rename_reconcile(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg = mod.GROUP_SOURCES["crypto_project_liveness"]["groups"]["_hacks"]
    src_dir = os.path.join(SOURCE_REPO, "track-crypto/data/crypto_project_liveness")
    need = ["2026-09-05.json.gz", "2026-09-06.json.gz", "2026-09-01.json.gz", "2026-09-02.json.gz"]
    if not all(os.path.exists(os.path.join(src_dir, n)) for n in need):
        return Result(False, "找不到真實 crypto_project_liveness 歷史快照，無法做 real-replay 驗證")
    paths = [install_binary_copy(os.path.join(src_dir, n), sandbox, n) for n in need]
    j05, j06, j01, j02 = [mod.load(p) for p in paths]

    r_rename = mod.compare_group("crypto_project_liveness", "_hacks", gcfg, j05["data"], j06["data"])
    judged_rename = mod.judge(r_rename, gcfg)
    sd_removed = any(isinstance(k, str) and k.split("\x1f")[0].startswith("stake dao")
                      for k in r_rename["removed_keys"])
    sd_added = any(isinstance(k, str) and k.split("\x1f")[0].startswith("stake dao")
                    for k in r_rename["added_keys"])
    renamed_sids = sorted(sid for _o, _n, sid in r_rename["renamed_pairs"])
    sids_ok = renamed_sids == ["249\x1f1773273600", "249\x1f1779840000"]

    r_true = mod.compare_group("crypto_project_liveness", "_hacks", gcfg, j01["data"], j02["data"])
    judged_true = mod.judge(r_true, gcfg)
    mm_removed = any(isinstance(k, str) and k.split("\x1f")[0] == "more markets"
                      for k in r_true["removed_keys"])

    guard_active = (judged_rename == "NORMAL" and not sd_removed and not sd_added
                     and sids_ok and len(r_rename["removed_keys"]) == 0
                     and len(r_rename["added_keys"]) == 2
                     and judged_true == "NORMAL" and mm_removed
                     and len(r_true["removed_keys"]) == 1
                     and len(r_true["renamed_pairs"]) == 0)
    return Result(guard_active,
                  "(a)09-05->09-06：judged=%s(期望NORMAL) removed=%d(期望0) added=%d(期望2) "
                  "removed含stake dao=%r(期望False) added含stake dao=%r(期望False) "
                  "renamed穩定識別=%r(期望249+兩個date)；"
                  "(b)09-01->09-02：judged=%s(期望NORMAL) removed=%d(期望1) "
                  "removed含more markets=%r(期望True) renamed=%d(期望0)"
                  % (judged_rename, len(r_rename["removed_keys"]), len(r_rename["added_keys"]),
                     sd_removed, sd_added, renamed_sids,
                     judged_true, len(r_true["removed_keys"]), mm_removed,
                     len(r_true["renamed_pairs"])))


@check("detect_delistings.oracle_pyth_range_check_real_replay", mutate_target="detect_delistings",
       mutate=mut_dd_group_integrity_gate)
def chk_dd_oracle_pyth_range_check_real_replay(is_mutant):
    """real-replay：oracle_feed_directory.pyth 真實歷史快照（VPS 正式資料，
    唯讀複製，2026-09-04，1864 筆）驗證 completeness=range_check（既有
    第二階段機制，本階段沿用不改）套用本階段校準的區間 [1658,2051] 時：
    (a) 真實完整資料本身（1864 筆）在區間內，兩側相同也應判 NORMAL；
    (b) 保留真實欄位形狀、只把清單截斷到前 1000 筆（低於下界 1658，模擬
        部分擷取失敗）應被 GATE_FAIL 擋下。
    真實 8 天資料本身從未真的跌出校準區間（本輪範圍即以此校準），純粹重放
    無法測到「跌出區間」分支，因此用「真實 schema + 人為截斷筆數」的混合
    方式驗證，而非另建完全合成資料，理由見 docs/detect-phase3-report.md §4.3。
    沿用既有 mut_dd_group_integrity_gate（range_check 分支不是本階段新程式碼，
    不需要另外設計新的破壞驗證）。"""
    sandbox = new_sandbox("dd_oracle_real_mut" if is_mutant else "dd_oracle_real")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_group_integrity_gate(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg = mod.GROUP_SOURCES["oracle_feed_directory"]["groups"]["pyth"]
    src_dir = os.path.join(SOURCE_REPO, "track-crypto/data/oracle_feed_directory")
    real_file = os.path.join(src_dir, "2026-09-04.json.gz")
    if not os.path.exists(real_file):
        return Result(False, "找不到真實 oracle_feed_directory 歷史快照，無法做 real-replay 驗證")
    f_real = install_binary_copy(real_file, sandbox, "real.json.gz")
    j_real = mod.load(f_real)
    data_full = j_real["data"]
    real_pyth = data_full.get("pyth") or []
    lo = gcfg["range"][0]
    data_truncated = {"pyth": real_pyth[:1000]}  # 1000 < 下界 1658，其餘欄位形狀完全真實

    r_full = mod.compare_group("oracle_feed_directory", "pyth", gcfg, data_full, data_full)
    judged_full = mod.judge(r_full, gcfg)
    r_bad = mod.compare_group("oracle_feed_directory", "pyth", gcfg, data_full, data_truncated)
    judged_bad = mod.judge(r_bad, gcfg)

    guard_active = (judged_full == "NORMAL" and judged_bad == "GATE_FAIL")
    return Result(guard_active,
                  "真實 09-04 pyth n=%d（區間%r）自我比對 judged=%s(期望NORMAL)；"
                  "截斷至前 1000 筆（<下界%d）judged=%s(期望GATE_FAIL)"
                  % (len(real_pyth), gcfg["range"], judged_full, lo, judged_bad))




# ==========================================================================
# 第四階段新增（2026-09-07，任務 E：抑制 cex_currency_status/gate 的 withdraw_disabled
# 一日抖動）。派工與證據：docs/0907-events-audit-0904-0907.md §5.8／§9.3 第 4 項，
# 使用者裁示「做法 2（抖動標記）＋做法 4（語意過濾），不做做法 3（不直接抑制寫入）」。
# 設計、實測數字、歷史全量重放驗證見本機 docs/0907-E-gate-flap-report.md。
#
# 本區塊 4 條檢查各自鎖住一條新行為，每條都有 #mutant 破壞驗證：
#   1. status_semantic_filter             做法 4：規則命中就不產生事件；前提欄位自己在變的
#                                          那一天不得被誤濾；被抑制的每筆都要進事實紀錄檔
#   2. status_semantic_filter.real_replay 做法 4：對真實 09-06／09-07 快照重放，
#                                          121／122 筆被抑制、49／49 筆保留
#   3. flap_window                        做法 2：回翻視窗 N=FLAP_WINDOW_DAYS 的邊界
#                                          （gap<=N 標記、gap>N 不標記），兩筆都要標記
#   4. flap_annotate_convergence          做法 2：回寫既有事件行時「該加的加、該拿掉的拿掉」，
#                                          標記狀態有唯一不動點 → 重跑零變化（冪等）
#
# 錨點唯一性：本區塊 3 個 mut_* 的錨點都在本輪新增的程式碼裡（status_filter_hit()、
# flap_marks()、annotate_flaps()），且已逐一用 text.count(anchor)==1 驗證，
# 不與既有 19 條錨點重疊（教訓來源：docs/selftest-fix-report.md 的 mut_dd_reappeared
# 錨點不唯一事件——平行函式可能逐字元寫出同一行）。
# 這 3 個 mut_* 刻意與檢查放在同一段落尾端，而不是插進上方既有的 mutation 區塊，
# 是為了讓本輪對 selftest.py 的改動是「檔尾單一連續新增區塊」，方便與同期其他任務合併。
# ==========================================================================


def mut_dd_status_filter(text):
    # 目標：status_filter_hit() 的規則命中判斷式（做法 4 語意過濾的唯一判定點）。
    # 破壞後所有規則都不會命中 → 被抑制的欄位變化會重新產生 STATUS_CHANGED 事件。
    return apply_mutation(
        text,
        '        if all(old_item.get(cf) == cv and new_item.get(cf) == cv for cf, cv in cond.items()):',
        '        if False:  # [selftest mutant] status semantic filter disabled',
        "dd_status_filter")


def mut_dd_flap_window(text):
    # 目標：flap_marks() 的回翻視窗上界。破壞後視窗形同無限大 → 間隔超過
    # FLAP_WINDOW_DAYS 的「翻回原值」也會被誤標成抖動。
    return apply_mutation(
        text,
        '                if gap > window_days:\n                    break',
        '                if False:  # [selftest mutant] flap window bound disabled\n'
        '                    break',
        "dd_flap_window")


def mut_dd_flap_stale_removal(text):
    # 目標：annotate_flaps() 移除「不該存在的舊標記」那一步。破壞後標記只會被加上、
    # 不會被拿掉，標記狀態失去唯一不動點 → 每次重跑都判定為需要改寫（冪等性破功）。
    return apply_mutation(
        text,
        '        for kk in FLAP_MARK_FIELDS:\n            e.pop(kk, None)',
        '        for kk in ():  # [selftest mutant] stale flap-mark removal disabled\n'
        '            e.pop(kk, None)',
        "dd_flap_stale_removal")


_FLAP_GCFG = {"path": ("gate",), "shape": "list", "key_field": "currency", "desc_field": "name",
              "completeness": "total_match", "total_fields": ("count",),
              "status_fields": ("delisted", "trade_disabled", "withdraw_disabled"),
              "status_filters": ({"field": "withdraw_disabled", "when_both": {"delisted": True},
                                  "reason": "delisted_dominates_withdraw_disabled"},),
              "breaker_pct": 50.0, "abs_floor": 5}


def _gate_day(rows):
    """rows: [(currency, delisted, trade_disabled, withdraw_disabled), ...] -> 合成快照 data 區塊。"""
    items = [gs_item("currency", c, "name", c, delisted=d, trade_disabled=t, withdraw_disabled=w)
             for c, d, t, w in rows]
    return {"gate": items, "count": len(items)}


@check("detect_delistings.status_semantic_filter", mutate_target="detect_delistings",
       mutate=mut_dd_status_filter)
def chk_dd_status_semantic_filter(is_mutant):
    """做法 4【語意過濾】：status_filters 命中的欄位變化不得產生 STATUS_CHANGED，
    但**前提欄位自己正在變化的那一天**必須完整保留（when_both 要求新舊兩側都成立）。
    合成資料四種情境同時驗證：
      KEEP_NOTDEL  delisted 兩側皆 False、withdraw_disabled 翻轉 → 保留（規則不命中）
      DROP_DEL     delisted 兩側皆 True、withdraw_disabled 翻轉  → 抑制（規則命中）
      KEEP_ONDEL   當天才變成 delisted，同時 withdraw_disabled 也翻 → 保留，且
                   from/to 必須同時含 delisted 與 withdraw_disabled 兩個欄位（不得只濾掉一半）
      KEEP_TRADE   delisted 兩側皆 True、但變的是 trade_disabled → 保留（規則只管 withdraw_disabled）
    另外驗證被抑制的那一筆確實寫進 STATUS_FILTER_LOG（抑制 != 資料消失）。"""
    sandbox = new_sandbox("dd_semfilter_mut" if is_mutant else "dd_semfilter")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_status_filter(text)
    mod = load_module(_install_dd(sandbox, text))
    d1 = _gate_day([("KEEP_NOTDEL", False, False, False), ("DROP_DEL", True, True, True),
                    ("KEEP_ONDEL", False, False, False), ("KEEP_TRADE", True, True, True),
                    ("PAD1", False, False, False), ("PAD2", False, False, False)])
    d2 = _gate_day([("KEEP_NOTDEL", False, False, True), ("DROP_DEL", True, True, False),
                    ("KEEP_ONDEL", True, False, True), ("KEEP_TRADE", True, False, True),
                    ("PAD1", False, False, False), ("PAD2", False, False, False)])
    r = mod.compare_group("cex_currency_status", "gate", _FLAP_GCFG, d1, d2)
    judged = mod.judge(r, _FLAP_GCFG)
    events, _ = mod.build_group_events("cex_currency_status", "gate", _FLAP_GCFG, r, judged,
                                        "2030-06-02", {})
    sc = {e["key"]: e for e in events if e["event"] == "STATUS_CHANGED"}
    log = read_jsonl(os.path.join(sandbox, "track-crypto/data/_status_filter/suppressed.jsonl"))
    logged = {(g["key"], g["field"]) for g in log}
    ok = (judged == "NORMAL"
          and set(sc) == {"KEEP_NOTDEL", "KEEP_ONDEL", "KEEP_TRADE"}
          and sc.get("KEEP_ONDEL", {}).get("from") == {"delisted": False, "withdraw_disabled": False}
          and sc.get("KEEP_ONDEL", {}).get("to") == {"delisted": True, "withdraw_disabled": True}
          and sc.get("KEEP_TRADE", {}).get("from") == {"trade_disabled": True}
          and logged == {("DROP_DEL", "withdraw_disabled")})
    return Result(ok, "judged=%s 產生的 STATUS_CHANGED key=%s（期望剛好 KEEP_NOTDEL/KEEP_ONDEL/"
                      "KEEP_TRADE 三筆、DROP_DEL 被抑制）；KEEP_ONDEL.from=%r（期望同時含 delisted 與 "
                      "withdraw_disabled）；抑制紀錄=%s（期望 {('DROP_DEL','withdraw_disabled')}）"
                  % (judged, sorted(sc), sc.get("KEEP_ONDEL", {}).get("from"), sorted(logged)))


@check("detect_delistings.status_semantic_filter.real_replay", mutate_target="detect_delistings",
       mutate=mut_dd_status_filter)
def chk_dd_status_semantic_filter_real_replay(is_mutant):
    """real-replay：對 VPS 正式歷史快照（唯讀複製）2026-09-05→09-06→09-07 三份
    cex_currency_status 快照重放 cex_currency_status/gate。
    實測基準（docs/0907-events-audit-0904-0907.md §5.8 與本輪重算一致）：
      09-05→09-06：170 筆 withdraw_disabled 變化，其中 delisted 兩側皆 True 者 121 筆
      09-06→09-07：171 筆，其中 delisted 兩側皆 True 者 122 筆
    套用語意過濾後 STATUS_CHANGED 應各剩 49／49 筆，且剩下的每一筆都不得是
    「delisted 兩側皆 True 且只變 withdraw_disabled」。"""
    sandbox = new_sandbox("dd_semfilter_real_mut" if is_mutant else "dd_semfilter_real")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_status_filter(text)
    mod = load_module(_install_dd(sandbox, text))
    gcfg = mod.GROUP_SOURCES["cex_currency_status"]["groups"]["gate"]
    src_dir = os.path.join(SOURCE_REPO, "track-crypto/data/cex_currency_status")
    days = {}
    for d in ("2026-09-05", "2026-09-06", "2026-09-07"):
        p = os.path.join(src_dir, "%s.json.gz" % d)
        if not os.path.exists(p):
            return Result(False, "找不到真實歷史快照 %s，無法做 real-replay 驗證" % p)
        days[d] = mod.load(install_binary_copy(p, sandbox, "real_%s.json.gz" % d))["data"]
    got = {}
    for d_old, d_new in (("2026-09-05", "2026-09-06"), ("2026-09-06", "2026-09-07")):
        r = mod.compare_group("cex_currency_status", "gate", gcfg, days[d_old], days[d_new])
        judged = mod.judge(r, gcfg)
        ev, _ = mod.build_group_events("cex_currency_status", "gate", gcfg, r, judged, d_new, {})
        sc = [e for e in ev if e["event"] == "STATUS_CHANGED"]
        leak = [e for e in sc
                if set(e["from"]) == {"withdraw_disabled"}
                and r["keyed_old"][e["key"]].get("delisted") is True
                and r["keyed_new"][e["key"]].get("delisted") is True]
        got[d_new] = (judged, len(sc), len(leak))
    log = read_jsonl(os.path.join(sandbox, "track-crypto/data/_status_filter/suppressed.jsonl"))
    n_log = {d: sum(1 for g in log if g["date"] == d) for d in ("2026-09-06", "2026-09-07")}
    ok = (got.get("2026-09-06") == ("NORMAL", 49, 0) and got.get("2026-09-07") == ("NORMAL", 49, 0)
          and n_log == {"2026-09-06": 121, "2026-09-07": 122})
    return Result(ok, "09-06=(judged,STATUS_CHANGED,漏網)=%r 09-07=%r（各期望 ('NORMAL',49,0)）；"
                      "抑制紀錄筆數=%r（期望 09-06:121、09-07:122）" % (got.get("2026-09-06"),
                                                                     got.get("2026-09-07"), n_log))


@check("detect_delistings.flap_window", mutate_target="detect_delistings", mutate=mut_dd_flap_window)
def chk_dd_flap_window(is_mutant):
    """做法 2【抖動標記】的回翻視窗邊界：間隔 <= FLAP_WINDOW_DAYS 天翻回原值要標記、
    超過就不標記，而且**配對的兩筆都要標記**、彼此互相記下對方的日期。
    合成 3 組（都用同一支 flap_marks() 純函式判定，不必跑整支程式）：
      G1  01-01 F->T、01-02 T->F     間隔 1 天  → 兩筆都標記
      G2  01-01 F->T、01-03 T->F     間隔 2 天  → 兩筆都標記（N=2 的上界，剛好在界內）
      G3  01-01 F->T、01-05 T->F     間隔 4 天  → 都不標記（超過視窗，可能是真的維護窗）
      G4  01-01 F->T、01-02 T->None  間隔 1 天但沒翻回原值 → 都不標記（值不相等）
    視窗取值 N=2 的實測推導見 detect_delistings.py 的 FLAP_WINDOW_DAYS 註解。"""
    sandbox = new_sandbox("dd_flapwin_mut" if is_mutant else "dd_flapwin")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_flap_window(text)
    mod = load_module(_install_dd(sandbox, text))

    def ev(date, key, ov, nv):
        return {"date": date, "source": "s", "group": "gate", "key": key,
                "event": "STATUS_CHANGED", "from": {"withdraw_disabled": ov},
                "to": {"withdraw_disabled": nv}}
    events = [ev("2030-01-01", "G1", False, True), ev("2030-01-02", "G1", True, False),
              ev("2030-01-01", "G2", False, True), ev("2030-01-03", "G2", True, False),
              ev("2030-01-01", "G3", False, True), ev("2030-01-05", "G3", True, False),
              ev("2030-01-01", "G4", False, True), ev("2030-01-02", "G4", True, None)]
    marks = mod.flap_marks(events)
    keys = sorted((d, k) for (d, g, k) in marks)
    ok = (keys == [("2030-01-01", "G1"), ("2030-01-01", "G2"),
                   ("2030-01-02", "G1"), ("2030-01-03", "G2")]
          and marks.get(("2030-01-01", "gate", "G1"), {}).get("with") == ["2030-01-02"]
          and marks.get(("2030-01-02", "gate", "G1"), {}).get("with") == ["2030-01-01"]
          and marks.get(("2030-01-01", "gate", "G1"), {}).get("fields") == ["withdraw_disabled"]
          and mod.FLAP_WINDOW_DAYS == 2)
    return Result(ok, "FLAP_WINDOW_DAYS=%r 被標記的(日期,key)=%r（期望 G1 兩筆＋G2 兩筆，"
                      "G3 間隔 4 天與 G4 未翻回原值都不得被標記）；G1 互指=%r/%r"
                  % (getattr(mod, "FLAP_WINDOW_DAYS", None), keys,
                     marks.get(("2030-01-01", "gate", "G1"), {}).get("with"),
                     marks.get(("2030-01-02", "gate", "G1"), {}).get("with")))


@check("detect_delistings.flap_annotate_convergence", mutate_target="detect_delistings",
       mutate=mut_dd_flap_stale_removal)
def chk_dd_flap_annotate_convergence(is_mutant):
    """做法 2【抖動標記】回寫既有事件行的三項不變量（合起來就是 verify_prod.py 第 6 項
    「detect_delistings 冪等（重跑零變化）」在本輪新機制上的對應保護）：
      (a) 該加的加：真正抖動的兩筆事件都被補上 flapped／flap_fields／flap_with；
      (b) 該拿掉的拿掉：檔案裡原本就有、但依現行資料不該存在的舊標記必須被移除
          —— 這是「標記狀態有唯一不動點」的關鍵，否則重跑會一直判定需要改寫；
      (c) 因此第二次呼叫 annotate_flaps() 的改寫行數必須是 0，檔案位元組完全不變。
    另外驗證既有 7 個核心欄位（date/source/group/key/event/from/to）一個都沒被動到，
    以及非 STATUS_CHANGED 的行原樣保留。"""
    sandbox = new_sandbox("dd_flapconv_mut" if is_mutant else "dd_flapconv")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_flap_stale_removal(text)
    mod = load_module(_install_dd(sandbox, text))
    jl = os.path.join(sandbox, "track-crypto/data/selftest_flap/events.jsonl")
    os.makedirs(os.path.dirname(jl), exist_ok=True)
    rows = [
        {"date": "2030-02-01", "source": "s", "group": "gate", "key": "FLAP",
         "event": "STATUS_CHANGED", "from": {"w": False}, "to": {"w": True}},
        {"date": "2030-02-02", "source": "s", "group": "gate", "key": "FLAP",
         "event": "STATUS_CHANGED", "from": {"w": True}, "to": {"w": False}},
        # 不該有標記卻已經帶著標記的一筆（模擬規則調整後的殘留），必須被移除
        {"date": "2030-02-01", "source": "s", "group": "gate", "key": "SOLO",
         "event": "STATUS_CHANGED", "from": {"w": False}, "to": {"w": True},
         "flapped": True, "flap_fields": ["w"], "flap_with": ["2030-02-09"]},
        {"date": "2030-02-01", "source": "s", "group": "gate", "key": "X1", "event": "LISTED",
         "from": None, "to": "x"},
    ]
    with open(jl, "w", encoding="utf-8") as f:
        for e in rows:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    n1, c1 = mod.annotate_flaps(jl)
    b1 = open(jl, "rb").read()
    after1 = read_jsonl(jl)
    n2, c2 = mod.annotate_flaps(jl)
    b2 = open(jl, "rb").read()
    got = {(e["date"], e["key"]): e for e in after1}
    core_ok = all(got[(o["date"], o["key"])].get(c) == o.get(c)
                  for o in rows for c in ("date", "source", "group", "key", "event", "from", "to"))
    ok = (n1 == 2 and c1 == 3 and core_ok
          and got[("2030-02-01", "FLAP")].get("flapped") is True
          and got[("2030-02-01", "FLAP")].get("flap_with") == ["2030-02-02"]
          and got[("2030-02-02", "FLAP")].get("flap_with") == ["2030-02-01"]
          and "flapped" not in got[("2030-02-01", "SOLO")]
          and "flapped" not in got[("2030-02-01", "X1")]
          and c2 == 0 and b1 == b2 and len(after1) == 4)
    return Result(ok, "第1次(標記數,改寫行數)=(%r,%r)（期望 (2,3)）；SOLO 殘留標記已移除=%s"
                      "（期望 True）；第2次改寫行數=%r（期望 0）；兩次位元組相同=%s（期望 True）；"
                      "核心7欄未被動到=%s 行數=%d（期望 4）"
                  % (n1, c1, "flapped" not in got[("2030-02-01", "SOLO")], c2, b1 == b2,
                     core_ok, len(after1)))


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



# ==========================================================================
# x402_bazaar 完整性守門：不可以是恆真式（2026-09-07 新增，
# 見 track-crypto/scripts/detect_delistings.py 第四階段修正區塊、
# 本機 docs/0907-D-x402-gate-report.md）
#
# 背景：舊版守門比對的是 data.total，而 data.total 是 adapter 自己寫的 len(items)
# ——自報的數字與被檢查的數字是同一個，判斷式恆為假、守門恆為真，對分頁截斷
# 零防護力。以下三條檢查把「守門必須拿**上游自報總數**來比」這件事鎖住。
# ==========================================================================

@check("detect_delistings.x402_gate_not_tautological",
       mutate_target="detect_delistings", mutate=mut_dd_x402_tautological_gate)
def chk_dd_x402_gate_not_tautological(is_mutant):
    """核心不變量：x402_bazaar 的完整性守門**不可以**是恆真式。

    用一組互為反例的資料，同時從兩個方向把守門釘在「上游自報總數」上：

      甲、data.total 與 len(items) 完全自我一致（都是 98），但上游說有 598 筆
          -> **必須** GATE_FAIL。恆真式守門（比對自我一致的數字）在這裡會放行。
      乙、data.total 故意說謊（宣稱 598，實際 len(items)=98），但上游自報總數
          與 len(items) 相符（都是 98）-> **必須** NORMAL。恆真式守門
          （比對 data.total 與 len(items)）在這裡會誤擋。

    兩個方向都對，才能證明守門讀的是 reported_total、不是 adapter 自己算的 total。
    #mutant 把 reported_total 換成 len(items) 本身（＝重現本輪修掉的那個 bug），
    甲案會變成放行，本檢查隨即翻盤成 FAIL。

    兩組的 removed_rate 都是 2%（100 -> 98），刻意壓在熔斷門檻 5% 之下，
    確保這條檢查只測完整性守門本身，不會被熔斷搶先攔截（比照既有
    detect_delistings.integrity_gate_skips 的設計）。
    """
    sandbox = new_sandbox("dd_x402_taut_mut" if is_mutant else "dd_x402_taut")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_x402_tautological_gate(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    cfg = mod.SOURCES["x402_bazaar"]

    base100 = [x402_item("R%d" % i, "d%d" % i) for i in range(100)]
    items98 = [x402_item("R%d" % i, "d%d" % i) for i in range(98)]

    # 甲：自我一致但上游說更多（模擬「掉了一整頁」）
    a_old = x402_snapshot(base100)
    a_new = x402_snapshot(items98, reported_total=598)
    fa_old = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-07-01.json.gz"), a_old)
    fa_new = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-07-02.json.gz"), a_new)
    judged_a = mod.judge(mod.compare_pair("x402_bazaar", cfg, fa_old, fa_new), cfg)

    # 乙：adapter 自算欄位說謊，但上游自報總數與實得筆數相符
    b_old = x402_snapshot(base100)
    b_new = x402_snapshot(items98, total=598, reported_total=98)
    fb_old = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-08-01.json.gz"), b_old)
    fb_new = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-08-02.json.gz"), b_new)
    judged_b = mod.judge(mod.compare_pair("x402_bazaar", cfg, fb_old, fb_new), cfg)

    # 設定表本身也一併釘住：不可以再出現舊的 total_field 鍵，
    # 且守門欄位不可以指回 adapter 自己算的 "total"。
    cfg_clean = ("total_field" not in cfg) and (cfg.get("reported_total_field") != "total")

    guard_active = (judged_a == "GATE_FAIL") and (judged_b == "NORMAL") and cfg_clean
    return Result(guard_active,
                  "甲(total=98==len(items)=98 但 reported_total=598)judged=%s(期望 GATE_FAIL)；"
                  "乙(total=598 說謊 但 reported_total=98==len(items))judged=%s(期望 NORMAL)；"
                  "SOURCES 無 total_field 且 reported_total_field=%r 不等於 'total' -> %s"
                  % (judged_a, judged_b, cfg.get("reported_total_field"), cfg_clean))


@check("detect_delistings.x402_gate_truncated_flag",
       mutate_target="detect_delistings", mutate=mut_dd_x402_truncated_gate)
def chk_dd_x402_gate_truncated_flag(is_mutant):
    """x402_bazaar 守門的 fail-closed 第一道防線：adapter 自報 data.truncated
    只要不是布林 False（True／缺失／None／任何其他值），一律視為不完整。

    刻意讓 reported_total 與 len(items) **完全相符**（筆數這條線索通過），
    只有 truncated=True 這一個訊號說「沒抓完」——守門仍必須擋下來。
    #mutant 關掉這個檢查後即放行，本檢查翻盤成 FAIL。
    （比照既有 detect_delistings.group_tolerant_total_match 對 agent_virtuals
      truncated 旗標的同一設計原則。）
    """
    sandbox = new_sandbox("dd_x402_trunc_mut" if is_mutant else "dd_x402_trunc")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_x402_truncated_gate(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    cfg = mod.SOURCES["x402_bazaar"]

    old = x402_snapshot([x402_item("R%d" % i, "d%d" % i) for i in range(100)])
    new_items = [x402_item("R%d" % i, "d%d" % i) for i in range(98)]
    new = x402_snapshot(new_items, truncated=True)  # 筆數對得上，但來源自報「沒抓完」
    f_old = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-07-11.json.gz"), old)
    f_new = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-07-12.json.gz"), new)
    judged_true = mod.judge(mod.compare_pair("x402_bazaar", cfg, f_old, f_new), cfg)

    # 對照組：同一組資料、truncated=False -> 必須 NORMAL（證明擋下來的原因就是這個旗標）
    new_ok = x402_snapshot(new_items, truncated=False)
    f_new_ok = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-07-13.json.gz"), new_ok)
    judged_false = mod.judge(mod.compare_pair("x402_bazaar", cfg, f_old, f_new_ok), cfg)

    guard_active = (judged_true == "GATE_FAIL") and (judged_false == "NORMAL")
    return Result(guard_active,
                  "truncated=True judged=%s(期望 GATE_FAIL)；同資料 truncated=False judged=%s(期望 NORMAL)"
                  % (judged_true, judged_false))


@check("detect_delistings.x402_gate_legacy_range",
       mutate_target="detect_delistings", mutate=mut_dd_x402_legacy_range)
def chk_dd_x402_gate_legacy_range(is_mutant):
    """舊快照相容分支：2026-09-07 之前的快照沒有 reported_total 欄位，
    守門退回 legacy_range_check（筆數是否落在實測歷史區間 SOURCES.legacy_range）。

    兩個方向都驗：
      甲、區間內（13,000 筆，區間 [12829,18252]）-> 必須通過守門（NORMAL）。
          這一條同時保證「歷史重放不會整批變成 GATE_FAIL」這個相容性要求。
      乙、區間外（100 筆）-> 必須 GATE_FAIL。這一條保證相容分支**不是**放行一切
          的空殼（否則就只是把恆真式換個地方留下來）。
    #mutant 關掉區間比較後乙案會放行，本檢查翻盤成 FAIL。
    """
    sandbox = new_sandbox("dd_x402_legacy_mut" if is_mutant else "dd_x402_legacy")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_x402_legacy_range(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    cfg = mod.SOURCES["x402_bazaar"]
    lo, hi = cfg["legacy_range"]

    n_in = 13000  # 落在 [12829, 18252] 內
    big_old = [x402_item("R%d" % i, "d%d" % i) for i in range(n_in)]
    big_new = big_old[:n_in - 20]  # 移除 20 筆＝0.15%，遠低於熔斷門檻 5%
    a_old = x402_snapshot(big_old, legacy=True)
    a_new = x402_snapshot(big_new, legacy=True)
    fa_old = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-06-01.json.gz"), a_old)
    fa_new = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-06-02.json.gz"), a_new)
    judged_in = mod.judge(mod.compare_pair("x402_bazaar", cfg, fa_old, fa_new), cfg)

    small = [x402_item("R%d" % i, "d%d" % i) for i in range(100)]
    b_old = x402_snapshot(small, legacy=True)
    b_new = x402_snapshot(small[:98], legacy=True)
    fb_old = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-06-11.json.gz"), b_old)
    fb_new = write_gz_json(os.path.join(sandbox, "track-crypto/data/x402_bazaar/2030-06-12.json.gz"), b_new)
    judged_out = mod.judge(mod.compare_pair("x402_bazaar", cfg, fb_old, fb_new), cfg)

    guard_active = (judged_in == "NORMAL") and (judged_out == "GATE_FAIL")
    return Result(guard_active,
                  "legacy_range=[%d,%d]；區間內 n=%d judged=%s(期望 NORMAL)；"
                  "區間外 n=100 judged=%s(期望 GATE_FAIL)"
                  % (lo, hi, n_in, judged_in, judged_out))

# ==========================================================================
# 第 5 種事件型別 RENAMED（2026-09-08 新增，任務 0908-1）
#
# 背景：任務 B（2026-09-07）加了「上游改名抵銷層」，讓改名不再被誤判成
# DELISTED＋LISTED，但刻意**不寫任何事件**——代價是 events.jsonl 對改名完全沉默，
# 只讀事件流的下游會看到「一個主鍵無聲消失、另一個主鍵無聲出現」
# （docs/0907-B-rename-key-report.md §9.4 第 1 項自陳）。使用者裁示「要看到改名」，
# 因此本輪把改名升格為第 5 種事件型別 RENAMED。
#
# 以下 4 條檢查鎖住的 4 件事：
#   1. renamed_event                改名必須真的產生 RENAMED 事件（而且不產生假 DELISTED／LISTED）
#   2. renamed_event_key_direction  key／from_key 是**舊**主鍵、to_key 是**新**主鍵（方向不可反）
#   3. renamed_event.real_replay    真實歷史快照（2026-09-06 Stake DAO）產生剛好 2 筆，
#                                   且真實消失（MORE Markets）不會被誤記成 RENAMED
#   4. renamed_event_append_safety  RENAMED 對 write_events() 冪等，且 annotate_flaps()
#                                   一個位元組都不會動到 RENAMED 的行
# ==========================================================================

def mut_dd_renamed_event(text):
    """目標：build_group_events() 裡把 renamed_pairs 轉成 RENAMED 事件的迴圈
（第五階段新增）。把迭代對象換成空 tuple，等於「改名又變回不寫事件」——
精確重現任務 B 的舊行為，也就是本輪要修掉的那個缺口。

刻意只改 for 那一行、保留整個迴圈本體：這樣突變後語法仍然合法、
其餘程式碼逐字元不動，破壞驗證停在「事件沒被產生」這個要測的行為上。

錨點唯一性：`for k_old, k_new, sid in (` 這個字面在 detect_delistings.py 裡
只有 build_group_events() 這一處（reconcile_renames() 內部用的是
`for k_old in removed_keys:`，字面不同），實測 count==1。"""
    return apply_mutation(
        text,
        '    for k_old, k_new, sid in (r.get("renamed_pairs") or ()):',
        '    for k_old, k_new, sid in ():  # [selftest mutant] RENAMED emission disabled',
        "dd_renamed_event")


def mut_dd_renamed_direction(text):
    """目標：RENAMED 事件的**方向欄位**。把 from_key／to_key 對調，模擬
「新舊主鍵寫反」這種讀起來完全合理、但語意整個顛倒的迴歸。

為什麼這件事值得一條專屬破壞驗證：events.jsonl 的 key 欄位語意本來就隨
event 型別而異（DELISTED＝消失的鍵、LISTED＝出現的鍵、STATUS_CHANGED＝續存的鍵），
RENAMED 一次牽涉兩個鍵，方向寫反的話下游會把「改名前」當成「改名後」，
而且因為兩個字串都存在、格式也都合法，**不會有任何例外或型別錯誤**——
只能靠不變量把它釘住。"""
    return apply_mutation(
        text,
        '                            "from_key": k_old, "to_key": k_new, "stable_id": sid,',
        '                            "from_key": k_new, "to_key": k_old, "stable_id": sid,'
        '  # [selftest mutant] rename direction swapped',
        "dd_renamed_direction")


def mut_dd_flap_skips_non_status(text):
    """目標：annotate_flaps() 的「非 STATUS_CHANGED 的行原樣保留」保護
（該函式 docstring 第 2 點自陳的三層保護之一）。拿掉 event 型別判斷之後，
RENAMED（以及未來任何新型別）的行會一起走進「重算標記並重新序列化」的路徑。

錨點唯一性：flap_marks() 裡也有一句 `e.get("event") != "STATUS_CHANGED"`，
但它的下一行是 `continue`，不是 `out_lines.append(ln)`——本錨點含這兩行後續，
只會精確命中 annotate_flaps() 那一處，實測 count==1。
（比照 docs/selftest-fix-report.md §2.1 的教訓：平行函式共用同一句判斷式時，
錨點必須延伸到足以區分兩者的後續行。）"""
    return apply_mutation(
        text,
        '        if not isinstance(e, dict) or e.get("event") != "STATUS_CHANGED":\n'
        '            out_lines.append(ln)\n'
        '            continue',
        '        if not isinstance(e, dict):'
        '  # [selftest mutant] non-STATUS_CHANGED rows no longer protected\n'
        '            out_lines.append(ln)\n'
        '            continue',
        "dd_flap_skips_non_status")


_RENAME_GCFG = {"path": ("items",), "shape": "list", "key_field": ("name", "date"),
                "desc_field": "name", "completeness": "total_match", "total_fields": ("count",),
                "status_fields": (), "breaker_pct": 50.0, "abs_floor": 5,
                "stable_id_fields": ("defillamaId", "date")}


def _rename_pair_data():
    """兩份合成快照：共同的 8 筆不動，第 9 筆被上游改名（穩定識別不變），
    另有 1 筆是當日真正的新增（沒有 defillamaId，不可能被抵銷）。"""
    common = [{"name": "P%d" % i, "date": 100 + i, "defillamaId": str(700 + i)} for i in range(8)]
    old = common + [{"name": "Stake DAO", "date": 900, "defillamaId": "249"}]
    new = common + [{"name": "Stake DAO Yield", "date": 900, "defillamaId": "249"},
                    {"name": "Brand New", "date": 901, "defillamaId": None}]
    return ({"items": old, "count": len(old)}, {"items": new, "count": len(new)})


@check("detect_delistings.renamed_event", mutate_target="detect_delistings",
       mutate=mut_dd_renamed_event)
def chk_dd_renamed_event(is_mutant):
    """核心不變量：被抵銷層判定為「上游改名」的一組主鍵，**必須**在事件流裡
    留下剛好一筆 RENAMED，而且**不可以**同時留下 DELISTED 或 LISTED。

    同一組資料裡刻意混一筆真正的新增（Brand New，沒有 defillamaId 所以
    stable_identity() 回 None、不可能被抵銷），用來確認本輪的新迴圈沒有把
    正常的 LISTED 路徑弄壞——「該寫的照寫、不該寫的不寫」兩個方向同時驗。

    欄位層級一併驗完整：from／to 必須是改名前後的人類可讀描述，
    stable_id 必須等於判定用的穩定識別，stable_id_fields 必須如實記下
    是用哪些欄位判定的（讓每一筆 RENAMED 都能被獨立複核）。"""
    sandbox = new_sandbox("dd_renamed_mut" if is_mutant else "dd_renamed")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_renamed_event(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    d_old, d_new = _rename_pair_data()
    r = mod.compare_group("selftest_rename_src", "grp", _RENAME_GCFG, d_old, d_new)
    judged = mod.judge(r, _RENAME_GCFG)
    events, _ = mod.build_group_events("selftest_rename_src", "grp", _RENAME_GCFG, r, judged,
                                        "2030-08-02", {})
    ren = [e for e in events if e["event"] == "RENAMED"]
    listed = [e for e in events if e["event"] == "LISTED"]
    delisted = [e for e in events if e["event"] == "DELISTED"]
    fields_ok = False
    if len(ren) == 1:
        e = ren[0]
        fields_ok = (e["date"] == "2030-08-02" and e["source"] == "selftest_rename_src"
                     and e["group"] == "grp"
                     and e["from"] == "Stake DAO" and e["to"] == "Stake DAO Yield"
                     and e["stable_id"] == "249\x1f900"
                     and e["stable_id_fields"] == ["defillamaId", "date"])
    guard_active = (judged == "NORMAL" and len(ren) == 1 and fields_ok
                    and len(delisted) == 0 and len(listed) == 1
                    and listed[0]["key"] == "brand new\x1f901")
    return Result(guard_active,
                  "judged=%s(期望NORMAL) RENAMED=%d(期望1) DELISTED=%d(期望0) LISTED=%d(期望1，"
                  "只有真正新增的 Brand New) 欄位齊全=%r(期望True) RENAMED內容=%r"
                  % (judged, len(ren), len(delisted), len(listed), fields_ok, ren))


@check("detect_delistings.renamed_event_key_direction", mutate_target="detect_delistings",
       mutate=mut_dd_renamed_direction)
def chk_dd_renamed_event_key_direction(is_mutant):
    """核心不變量：RENAMED 的 key／from_key 必須是**舊**主鍵、to_key 必須是**新**主鍵。

    不是用字串字面去比對（那只會鎖死測試資料），而是回到兩份快照的**事實**去驗：
      - from_key 必須「在前日快照裡、且不在當日快照裡」（＝真的消失了）
      - to_key   必須「在當日快照裡、且不在前日快照裡」（＝真的是新出現的）
      - key == from_key（本欄位的既有語意：DELISTED 也是放消失的那個鍵）
    這三條同時成立，方向就不可能寫反。

    為什麼 key 取舊主鍵：舊主鍵才是從當日快照消失的那一個，追蹤它的下游
    若查不到任何事件就會誤判為資料靜默遺失——那正是本輪要修掉的失效模式。"""
    sandbox = new_sandbox("dd_rendir_mut" if is_mutant else "dd_rendir")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_renamed_direction(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    d_old, d_new = _rename_pair_data()
    r = mod.compare_group("selftest_rename_src", "grp", _RENAME_GCFG, d_old, d_new)
    judged = mod.judge(r, _RENAME_GCFG)
    events, _ = mod.build_group_events("selftest_rename_src", "grp", _RENAME_GCFG, r, judged,
                                        "2030-08-02", {})
    ren = [e for e in events if e["event"] == "RENAMED"]
    ko, kn = set(r["keyed_old"]), set(r["keyed_new"])
    ok_from = ok_to = ok_key = False
    if len(ren) == 1:
        e = ren[0]
        ok_from = (e["from_key"] in ko) and (e["from_key"] not in kn)
        ok_to = (e["to_key"] in kn) and (e["to_key"] not in ko)
        ok_key = (e["key"] == e["from_key"])
    guard_active = (len(ren) == 1 and ok_from and ok_to and ok_key)
    return Result(guard_active,
                  "RENAMED=%d(期望1) from_key只在前日快照=%r(期望True) "
                  "to_key只在當日快照=%r(期望True) key==from_key=%r(期望True) 實際=%r"
                  % (len(ren), ok_from, ok_to, ok_key,
                     [(e.get("key"), e.get("from_key"), e.get("to_key")) for e in ren]))


@check("detect_delistings.renamed_event.real_replay", mutate_target="detect_delistings",
       mutate=mut_dd_renamed_event)
def chk_dd_renamed_event_real_replay(is_mutant):
    """real-replay：crypto_project_liveness 真實歷史快照（VPS 正式資料，唯讀複製），
    用真實 GROUP_SOURCES 設定，把「事件流看得見改名」這件事釘在真實資料上。

    (a) 2026-09-05→09-06：真實發生過的 Stake DAO → Stake DAO Yield（defillamaId
        兩天都是 "249"，兩筆 date 1773273600／1779840000）必須產生**剛好 2 筆**
        RENAMED，且兩筆的 to_key 都指向 "stake dao yield"、stable_id 都是 249＋date。
        同一天真正新增的 2 筆（Dream Health Chain／Reddio RedSonic）仍是 LISTED。

    (b) 2026-09-01→09-02：真實發生過的**唯一一次真實消失**（MORE Markets）
        必須是 1 筆 DELISTED、**0 筆 RENAMED**——真實消失不可以被誤記成改名。
        這一半在突變後仍會通過，刻意與 (a) 綁在同一條檢查裡，讓「改名看得見」與
        「消失不會被改名吃掉」是同一個驗收單位，不會日後被人各自放寬
        （手法比照既有 detect_delistings.rename_reconcile.real_replay）。"""
    sandbox = new_sandbox("dd_renreal_mut" if is_mutant else "dd_renreal")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_renamed_event(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg = mod.GROUP_SOURCES["crypto_project_liveness"]["groups"]["_hacks"]
    src_dir = os.path.join(SOURCE_REPO, "track-crypto/data/crypto_project_liveness")
    need = ["2026-09-05.json.gz", "2026-09-06.json.gz", "2026-09-01.json.gz", "2026-09-02.json.gz"]
    if not all(os.path.exists(os.path.join(src_dir, n)) for n in need):
        return Result(False, "找不到真實 crypto_project_liveness 歷史快照，無法做 real-replay 驗證")
    paths = [install_binary_copy(os.path.join(src_dir, n), sandbox, n) for n in need]
    j05, j06, j01, j02 = [mod.load(p) for p in paths]

    r_a = mod.compare_group("crypto_project_liveness", "_hacks", gcfg, j05["data"], j06["data"])
    ev_a, _ = mod.build_group_events("crypto_project_liveness", "_hacks", gcfg, r_a,
                                      mod.judge(r_a, gcfg), "2026-09-06", {})
    ren_a = [e for e in ev_a if e["event"] == "RENAMED"]
    listed_a = [e for e in ev_a if e["event"] == "LISTED"]
    delisted_a = [e for e in ev_a if e["event"] == "DELISTED"]
    sids_a = sorted(e["stable_id"] for e in ren_a)
    to_ok = all(isinstance(e.get("to_key"), str)
                and e["to_key"].split("\x1f")[0] == "stake dao yield" for e in ren_a)
    from_ok = all(isinstance(e.get("from_key"), str)
                  and e["from_key"].split("\x1f")[0] == "stake dao" for e in ren_a)

    r_b = mod.compare_group("crypto_project_liveness", "_hacks", gcfg, j01["data"], j02["data"])
    ev_b, _ = mod.build_group_events("crypto_project_liveness", "_hacks", gcfg, r_b,
                                      mod.judge(r_b, gcfg), "2026-09-02", {})
    ren_b = [e for e in ev_b if e["event"] == "RENAMED"]
    del_b = [e for e in ev_b if e["event"] == "DELISTED"]
    mm_ok = (len(del_b) == 1 and del_b[0]["key"].split("\x1f")[0] == "more markets")

    guard_active = (len(ren_a) == 2 and sids_a == ["249\x1f1773273600", "249\x1f1779840000"]
                    and to_ok and from_ok and len(delisted_a) == 0 and len(listed_a) == 2
                    and len(ren_b) == 0 and mm_ok)
    return Result(guard_active,
                  "(a)09-05->09-06：RENAMED=%d(期望2) stable_id=%r(期望249+兩個date) "
                  "to_key全指向stake dao yield=%r(期望True) from_key全是stake dao=%r(期望True) "
                  "DELISTED=%d(期望0) LISTED=%d(期望2)；"
                  "(b)09-01->09-02：RENAMED=%d(期望0) DELISTED=1且為more markets=%r(期望True)"
                  % (len(ren_a), sids_a, to_ok, from_ok, len(delisted_a), len(listed_a),
                     len(ren_b), mm_ok))


@check("detect_delistings.renamed_event_append_safety", mutate_target="detect_delistings",
       mutate=mut_dd_flap_skips_non_status)
def chk_dd_renamed_event_append_safety(is_mutant):
    """RENAMED 加進事件流之後，**不可以**破壞既有的兩條「只追加」保證：

    (1) write_events() 冪等：同一筆 RENAMED 重跑不得重複寫入。去重鍵是
        (date, source, group, key, event)，RENAMED 沿用不改——這裡實測驗一次，
        因為 RENAMED 的 key 是舊主鍵，與同一天可能存在的其他事件共用鍵空間。

    (2) annotate_flaps() 不得動到 RENAMED 的行。抖動標記是本程式**唯一**一處
        非附加寫入（會整份重寫 events.jsonl），它的契約是「非 STATUS_CHANGED 的行
        原樣保留」。這裡刻意在 RENAMED 那一行放一個**不該存在**的 flapped 欄位：
        契約成立時該行連同這個多餘欄位一起被逐位元組保留（抖動邏輯根本不該碰它）；
        契約被破壞時該行會被重新序列化、flapped 被清掉，位元組隨即改變。
        用「多餘欄位」而不是「正常行」當探針，是因為正常行重新序列化後
        位元組可能剛好相同，測不出保護是否還在。

    同時驗 STATUS_CHANGED 那一對**仍然**被正常標記——避免有人為了讓本檢查通過
    而把整個抖動功能關掉。"""
    sandbox = new_sandbox("dd_renappend_mut" if is_mutant else "dd_renappend")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_flap_skips_non_status(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)

    # (1) write_events() 冪等
    jp = os.path.join(sandbox, "track-crypto/data/selftest_rename_src/events.jsonl")
    os.makedirs(os.path.dirname(jp), exist_ok=True)
    d_old, d_new = _rename_pair_data()
    r = mod.compare_group("selftest_rename_src", "grp", _RENAME_GCFG, d_old, d_new)
    judged = mod.judge(r, _RENAME_GCFG)
    evs, _ = mod.build_group_events("selftest_rename_src", "grp", _RENAME_GCFG, r, judged,
                                     "2030-08-02", {})
    seen = mod.load_seen(jp)
    fresh1 = mod.write_events(jp, evs, seen)
    seen.update((e["date"], e["source"], e["group"], e["key"], e["event"]) for e in fresh1)
    fresh2 = mod.write_events(jp, evs, seen)
    seen3 = mod.load_seen(jp)          # 重新從檔案載入，模擬下一次排程執行
    fresh3 = mod.write_events(jp, evs, seen3)
    n_ren1 = sum(1 for e in fresh1 if e["event"] == "RENAMED")
    idem_ok = (n_ren1 == 1 and len(fresh2) == 0 and len(fresh3) == 0)

    # (2) annotate_flaps() 不得動到 RENAMED 的行
    fp = os.path.join(sandbox, "track-crypto/data/selftest_flapren_src/events.jsonl")
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    ren_line = ('{"date": "2030-01-01", "source": "S", "group": "g", "key": "OLD",'
                ' "event": "RENAMED", "from": "Old", "to": "New", "from_key": "OLD",'
                ' "to_key": "NEW", "stable_id": "sid1", "stable_id_fields": ["id"],'
                ' "flapped": true}')
    sc1 = ('{"date": "2030-01-01", "source": "S", "group": "g", "key": "K1",'
           ' "event": "STATUS_CHANGED", "from": {"f": false}, "to": {"f": true}}')
    sc2 = ('{"date": "2030-01-02", "source": "S", "group": "g", "key": "K1",'
           ' "event": "STATUS_CHANGED", "from": {"f": true}, "to": {"f": false}}')
    with open(fp, "w", encoding="utf-8") as f:
        f.write(ren_line + "\n" + sc1 + "\n" + sc2 + "\n")
    n_marks, n_rewritten = mod.annotate_flaps(fp)
    after = open(fp, encoding="utf-8").read().split("\n")
    ren_intact = (after[0] == ren_line)
    sc_marked = sum(1 for ln in after if ln.strip()
                    and json.loads(ln).get("event") == "STATUS_CHANGED"
                    and json.loads(ln).get("flapped") is True)

    guard_active = (idem_ok and ren_intact and n_marks == 2 and sc_marked == 2)
    return Result(guard_active,
                  "(1)冪等：首次RENAMED=%d(期望1) 第2次新事件=%d(期望0) 重載後第3次=%d(期望0)；"
                  "(2)annotate_flaps：RENAMED該行逐位元組不變=%r(期望True) "
                  "抖動標記數=%d(期望2) 被標記的STATUS_CHANGED=%d(期望2) 改寫行數=%d"
                  % (n_ren1, len(fresh2), len(fresh3), ren_intact, n_marks, sc_marked, n_rewritten))



# ==========================================================================
# WORKDIR 自清（2026-09-08 新增，原 G 報告 tmp 清理建議之一：selftest.py 每次
# 執行都會在 /tmp/selftest/ 建一個新 WORKDIR，先前無論成敗都不清理，是 /tmp
# 累積量最大的單一來源（見 docs/0908-2-alert-selftest-report.md、
# docs/0907-G-tmp-cleanup.md）。只在全數 PASS 時自動清除；FAIL 時保留供除錯；
# SELFTEST_KEEP=1 可強制保留（不論成敗）。見 docs/selftest.md「WORKDIR 自清」一節。
# ==========================================================================

_WORKDIR_DANGEROUS_PATHS = {
    "/", "/root", "/home", "/tmp", "/etc", "/usr", "/bin", "/var", "/opt",
    "/srv", "/boot", "/dev", "/lib", "/lib64", "/proc", "/sbin", "/sys",
    "/mnt", "/media", os.path.expanduser("~"),
}


def _workdir_is_safe_to_delete(path):
    """純判斷（唯讀，不刪除任何東西、不做任何檔案系統寫入）：這個路徑能不能被
    WORKDIR 自清機制自動 shutil.rmtree()。四層防呆，任何一層不通過就整體回傳
    (False, 理由字串)：
      1. 路徑無法正規化，或正規化後為空字串／等於系統根目錄 "/"。
      2. 命中系統層級目錄黑名單（常見掛載點、家目錄，含 "/tmp" 本身——WORKDIR
         必須是 /tmp 底下的子目錄，絕不能是 /tmp 這一層本身，否則等於清空
         整個 /tmp）。
      3. 正規化後路徑深度 < 2 層（例如 "/tmp"，雙重防護，即使黑名單漏列也擋得住）。
      4. 不是以 "/tmp/" 開頭——selftest.py 的沙盒契約是「所有輸出一律寫在 /tmp
         底下」（見模組 docstring「設計原則」第 1 點），自動清除只信任這個範圍
         內的路徑；呼叫端若把 SELFTEST_WORKDIR 指到 /tmp 之外，自動清除會直接
         放棄並在輸出說明原因，需要的話自行清理，不會嘗試刪除。

    全部通過才回傳 (True, 正規化後路徑)。本函式完全不觸碰檔案系統（只有
    os.path.abspath 字串運算），可以放心對任意路徑字串呼叫，不必擔心副作用——
    真正的刪除動作只會在 _safe_rmtree_workdir() 裡、且是本函式回傳 True 之後
    才會發生。"""
    try:
        ap = os.path.abspath(path)
    except Exception:
        return False, "路徑無法正規化"
    if not ap or ap == os.sep:
        return False, "路徑為空或等於根目錄"
    if ap in _WORKDIR_DANGEROUS_PATHS:
        return False, "路徑命中系統目錄黑名單: %s" % ap
    parts = [p for p in ap.split(os.sep) if p]
    if len(parts) < 2:
        return False, "路徑深度不足（%d 層）: %s" % (len(parts), ap)
    if not ap.startswith("/tmp" + os.sep):
        return False, "路徑不在 /tmp 底下，基於安全考量不自動清除: %s" % ap
    return True, ap


def _safe_rmtree_workdir(path):
    """實際清除 WORKDIR：先呼叫 _workdir_is_safe_to_delete() 做唯讀判斷，只有
    通過、且該路徑確實是既存目錄，才呼叫 shutil.rmtree()。任何一關不過就整個
    放棄刪除（寧可少清，不可誤刪）。刪除本身失敗（例如權限問題）也不拋出例外，
    只回報失敗——清理是錦上添花，不該讓一次全數 PASS 的執行因為清理失敗而回報
    非 0 結束碼。回傳 (是否已清除, 說明字串)。"""
    ok, info = _workdir_is_safe_to_delete(path)
    if not ok:
        return False, info
    if not os.path.isdir(info):
        return False, "路徑不是既存目錄，無需清除: %s" % info
    try:
        shutil.rmtree(info)
    except Exception as e:
        return False, "shutil.rmtree 失敗（%s），WORKDIR 保留" % e
    return True, info


def _finalize_workdir(any_fail):
    """WORKDIR 收尾決策：全數 PASS 時自動清除，FAIL 時保留（供除錯），
    SELFTEST_KEEP=1 時不論成敗一律保留。回傳 (動作, 說明文字)，
    動作 in {"cleaned", "kept"}；由呼叫端（main()）決定要不要印出，方便自測
    直接呼叫、檢查回傳值即可，不必攔截 stdout。"""
    keep_forced = os.environ.get("SELFTEST_KEEP") == "1"
    if any_fail:
        return "kept", "WORKDIR 保留（有 FAIL，供除錯）：%s" % WORKDIR_ROOT
    if keep_forced:
        return "kept", "WORKDIR 保留（SELFTEST_KEEP=1 強制保留）：%s" % WORKDIR_ROOT
    cleaned, info = _safe_rmtree_workdir(WORKDIR_ROOT)
    if cleaned:
        return "cleaned", "WORKDIR 已清除（全數 PASS）：%s" % info
    return "kept", "WORKDIR 未清除（%s）：%s" % (info, WORKDIR_ROOT)


def _install_st(sandbox, text):
    """selftest.py 用 __file__ 動態推算 HERE/REPO_SELF，放在 <sandbox>/scripts/
    底下，路徑結構與正式部署位置一致（比照全檔案一致的安裝慣例；本檢查實際上
    只呼叫模組內的純函式，不執行 main()/run_all()，不受這個路徑推算影響）。"""
    return install_text(sandbox, "scripts/selftest.py", text)


def mut_st_workdir_guard(text):
    """關掉 WORKDIR 自清防呆的「必須在 /tmp 底下」這一關，模擬這道防線被誤刪／
    改壞的情況。對應檢查 selftest.workdir_cleanup_guard。
    本檢查全程只呼叫唯讀的判斷函式，即使在 #mutant（防呆被拆掉）的情況下，也
    絕對不會真的對危險路徑呼叫 shutil.rmtree()——只驗證「決策」，不驗證「動作」，
    見 chk_st_workdir_cleanup_guard() docstring。

    錨點文字刻意拆成兩段字串相加組出來（執行期串接後與目標行完全相同），避免
    這個 apply_mutation() 呼叫的原始碼本身（也在 scripts/selftest.py 這個檔案裡）
    被 text.count(anchor) 算成第二個相符——這是本檔第一支「測試對象是
    selftest.py 自己」的 mutation，read_source("selftest") 讀到的是整個檔案，
    包含本函式自己的原始碼；若錨點字串在這裡完整連續出現，就會撞見
    apply_mutation() 的「錨點必須唯一」保護（本輪實測就先撞過一次這個問題，
    見 docs/0908-2-alert-selftest-report.md）。其餘既有 mut_* 都是測試外部程式
    （detect_changes.py／detect_delistings.py／cex_events.py／healthcheck.py／
    daily_report.py），錨點文字與被搜尋的檔案是不同檔案，不會有這個問題。"""
    anchor = '    if not ap.startswith("/tmp" ' + '+ os.sep):'
    return apply_mutation(
        text, anchor,
        '    if False:  # [selftest mutant] /tmp-only workdir guard disabled',
        "st_workdir_guard")


@check("selftest.workdir_cleanup_guard", mutate_target="selftest", mutate=mut_st_workdir_guard)
def chk_st_workdir_cleanup_guard(is_mutant):
    """鎖住 WORKDIR 自清機制的安全防呆（2026-09-08 新增：selftest.py 只在全數
    PASS 時自動 shutil.rmtree(WORKDIR_ROOT)，FAIL 時保留供除錯，SELFTEST_KEEP=1
    可強制保留）。任務書要求「路徑要嚴格檢查，不能有 rm -rf 打到 / 的可能」。

    本檢查**只呼叫唯讀的判斷函式** _workdir_is_safe_to_delete()，全程不對危險
    路徑呼叫真正會刪除檔案的 _safe_rmtree_workdir()／shutil.rmtree()——即使在
    #mutant（防呆被刻意拆掉）的情況下，也絕對不能真的對 "/etc"「/」這類系統
    路徑下手，否則自測程式本身就會變成破壞 VPS 的工具。這是刻意的設計取捨：
    只驗證「決策」，不驗證「危險情況下的動作」。

    危險路徑（判斷應該一律 False，不能自動清除）：
      "/"、"/etc"、"/home"、"/tmp"（等於 WORKDIR 的上一層，不是 WORKDIR 本身）、
      家目錄、以及兩個「深度夠、不在黑名單裡，但不在 /tmp 底下」的探針路徑
      （專門測第 4 關「必須以 /tmp/ 開頭」，不會被前面幾關提早攔下，才能真正
      證明是這一關在把關，而不是其他關卡湊巧也擋住）。
    安全路徑（判斷應該一律 True，可以自動清除）：
      預設格式 "/tmp/selftest/run-xxx-xxx" 與呼叫端自訂名稱 "/tmp/<任意名稱>/..."
      （只要在 /tmp 底下就該放行，不限定目錄名稱格式）。

    另外用本次檢查自己的 sandbox（一定在 /tmp 底下）建一個一次性用完即丟的
    目錄，直接呼叫**真正會刪除**的 _safe_rmtree_workdir()，確認判斷通過後
    真的會清乾淨——不是只有防呆邏輯正確、但刪除機制本身沒接上。這一段用的
    路徑保證安全，normal／mutant 兩種模式下都跑，不受這次 mutation 影響
    （mutation 只影響「/tmp 以外」的路徑判斷）。

    #mutant 把「必須以 /tmp/ 開頭」這一行判斷式改成永遠不成立，兩個探針路徑
    就會被誤判為安全，本檢查隨即翻盤成 FAIL，證明這一行判斷式真的是這道防線
    的關鍵。
    """
    sandbox = new_sandbox("st_guard_mut" if is_mutant else "st_guard")
    text = read_source("selftest")
    if is_mutant:
        text = mut_st_workdir_guard(text)
    script_path = _install_st(sandbox, text)
    mod = load_module(script_path)

    dangerous_cases = ["/", "/etc", "/home", "/tmp", os.path.expanduser("~"),
                        "/var/log/selftest-probe-should-not-exist",
                        "/opt/nested/selftest-probe-should-not-exist"]
    safe_cases = ["/tmp/selftest/run-20300101-000000-1",
                  "/tmp/selftest-caller-picked-name/subdir"]
    dangerous_results = {p: mod._workdir_is_safe_to_delete(p)[0] for p in dangerous_cases}
    safe_results = {p: mod._workdir_is_safe_to_delete(p)[0] for p in safe_cases}
    all_dangerous_rejected = all(v is False for v in dangerous_results.values())
    all_safe_accepted = all(v is True for v in safe_results.values())

    disposable = os.path.join(sandbox, "disposable-marker-dir")
    os.makedirs(disposable, exist_ok=True)
    with open(os.path.join(disposable, "marker.txt"), "w", encoding="utf-8") as f:
        f.write("selftest disposable marker\n")
    cleaned_ok, _ = mod._safe_rmtree_workdir(disposable)
    really_gone = not os.path.exists(disposable)

    guard_active = all_dangerous_rejected and all_safe_accepted and cleaned_ok and really_gone
    return Result(guard_active,
                  "危險路徑判斷=%r（期望全部 False）；安全路徑判斷=%r（期望全部 True）；"
                  "真實清除自己 sandbox 內的暫存目錄=%s 且確實消失=%s（期望皆 True）"
                  % (dangerous_results, safe_results, cleaned_ok, really_gone))


# ==========================================================================
# track-crypto/scripts/detect_delistings.py 第五階段新增 — 5 條新檢查
# （2026-09-08，mcp_smithery 納入下架偵測；本機 docs/0908-3-smithery-detect-report.md）
#
# 涵蓋本輪新增的三個機制：
#   (1) completeness_group() 的 full_flag_tolerant_total_match 分支（is_full 旗標
#       + total_count_reported 相對誤差），且證明它**不是恆真式**；
#   (2) parser_version_floor_check()（min_parser_version 版本下限守門），
#       合成端到端 + 真實歷史快照 real-replay 兩條；
#   (3) mcp_smithery 正式設定值本身（熔斷門檻在正式規模下的行為）。
# ==========================================================================

MCPS_SRC = "mcp_smithery"
MCPS_GRP = "_servers"


def mut_dd_smithery_tautological_gate(text):
    """把 mcp_smithery 的完整性守門比對對象從上游自報總數 total_count_reported
    換成 adapter 自己算的 total_returned（= len(servers)），也就是把守門變回
    **恆真式**（被檢查的數字＝自報的數字）——重現 0907-D 在 x402_bazaar 抓到的
    同一類缺陷。對應檢查 detect_delistings.smithery_gate_not_tautological。"""
    return apply_mutation(
        text,
        '                "total_field": "total_count_reported",',
        '                "total_field": "total_returned",  # [selftest mutant] 恆真式守門重現',
        "dd_smithery_tautological_gate")


def mut_dd_smithery_full_flag(text):
    """關掉 full_flag_tolerant_total_match 分支對 is_full 旗標的 fail-closed 檢查。
    對應檢查 detect_delistings.smithery_gate_full_flag。"""
    return apply_mutation(
        text,
        '        if ff_val is not True:',
        '        if False:  # [selftest mutant] mcp_smithery is_full 旗標守門停用',
        "dd_smithery_full_flag")


def mut_dd_smithery_pv_floor(text):
    """把 parser_version_floor_check() 的下限讀取改成永遠 None，等於整道
    版本下限守門停用（未設定 min_parser_version 的既有子集合本來就是這個行為）。
    對應檢查 detect_delistings.smithery_parser_version_floor。"""
    return apply_mutation(
        text,
        '    floor = gcfg.get("min_parser_version")',
        '    floor = None  # [selftest mutant] parser_version 版本下限守門停用',
        "dd_smithery_pv_floor")


def mut_dd_smithery_tolerance(text):
    """關掉 full_flag_tolerant_total_match 分支的第二個子條件（自報總數與實得筆數的
    相對誤差容忍度）。錨點刻意帶到分支結尾那行 return，因為
    `if gap_pct > tol:` 這一行在 tolerant_total_match（第三階段）分支裡逐字相同，
    只有加上分支專屬的 return 文字才唯一（本檔案已因錨點不唯一吃過虧，
    見 docs/selftest-fix-report.md 教訓 3）。"""
    return apply_mutation(
        text,
        '        if gap_pct > tol:\n'
        '            return False, n_raw, ("%s(%r) 與原始筆數(%d) 相對誤差 %.4f%% 超過容忍度 %.2f%%"\n'
        '                                   % (total_field, total, n_raw, gap_pct, tol))\n'
        '        return True, n_raw, ("full_flag_tolerant_total_match(gap=%.4f%%,tol=%.2f%%)"',
        '        if False:  # [selftest mutant] mcp_smithery 相對誤差容忍度守門停用\n'
        '            return False, n_raw, ("%s(%r) 與原始筆數(%d) 相對誤差 %.4f%% 超過容忍度 %.2f%%"\n'
        '                                   % (total_field, total, n_raw, gap_pct, tol))\n'
        '        return True, n_raw, ("full_flag_tolerant_total_match(gap=%.4f%%,tol=%.2f%%)"',
        "dd_smithery_tolerance")


def mut_dd_smithery_both_layers(text):
    """同時停用**兩層**防線：版本下限守門，以及完整性守門的**兩個**子條件
    （is_full 旗標 + 相對誤差容忍度）。

    為什麼必須三個一起關：real-replay 檢查要主張的是「兩層各自獨立都擋得住」，
    只關其中一項時另一項仍會正確擋下（那正是本檢查要證明的事），破壞驗證就翻不了盤。
    實測（2026-09-08）：只關版本下限＋is_full 旗標時，2026-09-07 快照的
    total_count_reported=11,771 vs 實得 272 相對誤差 97.69% 仍然超過容忍度 0.3%，
    judged 還是 GATE_FAIL，#mutant 條目會 FAIL。設計理由與第三階段
    mut_dd_group_tolerant_total_match 的「兩個子條件一起關」完全相同。
    對應檢查 detect_delistings.smithery_parser_version_floor.real_replay。"""
    return mut_dd_smithery_tolerance(
        mut_dd_smithery_full_flag(mut_dd_smithery_pv_floor(text)))


def mut_dd_smithery_breaker_pct(text):
    """把 mcp_smithery 的熔斷門檻從 1.0% 放寬到 50%，讓正式規模下的
    120 筆移除（1.007%）不再觸發熔斷。對應檢查 detect_delistings.smithery_breaker_pct。"""
    return apply_mutation(
        text,
        '                "breaker_pct": 1.0, "abs_floor": 20,',
        '                "breaker_pct": 50.0, "abs_floor": 20,  # [selftest mutant] 熔斷門檻放寬',
        "dd_smithery_breaker_pct")


def _mcps_data(n_items, total_count_reported, is_full=True, start=0, unlisted=False, inactive=False):
    """比照 track-crypto/data/mcp_smithery 快照 data 節點的實測 schema
    （欄位名逐一核對自 VPS 2026-09-08 正式快照）：
      {"servers":[...], "total_returned": len(servers), "total_count_reported": <上游自報>,
       "pages_fetched":.., "dup_skipped":.., "stop_reason":.., "is_full": bool, "coverage_note":..}
    total_returned 一律寫成 len(servers)——這正是正式 adapter 的行為，也是本組檢查
    要證明「守門沒有拿它來比對」的關鍵。"""
    servers = [
        {"id": "00000000-0000-4000-8000-%012d" % (start + i),
         "qualifiedName": "ns%d/srv%d" % ((start + i) % 7, start + i),
         "namespace": "ns%d" % ((start + i) % 7), "slug": "srv%d" % (start + i),
         "displayName": "Server %d" % (start + i), "description": "selftest synthetic %d" % (start + i),
         "useCount": 100 + (start + i), "verified": False, "remote": True, "isDeployed": True,
         "unlisted": unlisted, "inactive": inactive, "bySmithery": False,
         "createdAt": "2030-01-01T00:00:00.000Z",
         "homepage": "https://example.invalid/selftest/%d" % (start + i),
         "iconUrl": None, "owner": "org_selftest", "score": None}
        for i in range(n_items)
    ]
    return {"servers": servers, "total_returned": len(servers),
            "total_count_reported": total_count_reported,
            "pages_fetched": max(1, (n_items // 100) + 1), "dup_skipped": 0,
            "stop_reason": "exhausted" if is_full else "deadline",
            "is_full": is_full, "coverage_note": "selftest synthetic"}


@check("detect_delistings.smithery_gate_not_tautological", mutate_target="detect_delistings",
       mutate=mut_dd_smithery_tautological_gate)
def chk_dd_smithery_gate_not_tautological(is_mutant):
    """第五階段新增：mcp_smithery 的完整性守門必須比對**上游自報總數**
    （data.total_count_reported，來自回應的 pagination.totalCount），
    不是 adapter 自己算出來的 data.total_returned（＝len(servers)，恆真式）。
    這是 0907-D 在 x402_bazaar 抓到的同一類缺陷，本輪不能再犯一次。

    兩組情境，兩個欄位刻意給出相反的結論：
      甲：total_returned 與 len(servers) 完全自我一致（都是 98），但上游自報
          total_count_reported=598 → 只抓到 16.4%，必須 GATE_FAIL。
      乙：total_returned 故意寫成 598（說謊），但 total_count_reported=98
          與 len(servers) 相符 → 必須 NORMAL（證明守門讀的不是 total_returned）。
    另外直接斷言正式設定的 total_field 不等於 "total_returned"。
    mutant 把 total_field 換成 total_returned，甲會翻成 NORMAL，本檢查 FAIL。"""
    sandbox = new_sandbox("dd_mcps_taut_mut" if is_mutant else "dd_mcps_taut")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_smithery_tautological_gate(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg = mod.GROUP_SOURCES[MCPS_SRC]["groups"][MCPS_GRP]

    d_old = _mcps_data(100, 100)                     # 前一日：乾淨
    d_a = _mcps_data(98, 598)                        # 甲：自報 598、實得 98
    d_b = _mcps_data(98, 98)                         # 乙：自報 98、實得 98
    d_b["total_returned"] = 598                      # 但 total_returned 說謊
    r_a = mod.compare_group(MCPS_SRC, MCPS_GRP, gcfg, d_old, d_a)
    r_b = mod.compare_group(MCPS_SRC, MCPS_GRP, gcfg, d_old, d_b)
    j_a, j_b = mod.judge(r_a, gcfg), mod.judge(r_b, gcfg)
    field_ok = gcfg["total_field"] == "total_count_reported" != "total_returned"
    guard_active = (j_a == "GATE_FAIL") and (j_b == "NORMAL") and field_ok
    return Result(guard_active,
                  "甲(total_returned=98==len(servers)=98 但 total_count_reported=598)judged=%s(期望 GATE_FAIL)；"
                  "乙(total_returned=598 說謊 但 total_count_reported=98==len(servers))judged=%s(期望 NORMAL)；"
                  "正式設定 total_field=%r（期望 'total_count_reported'）-> %s；理由=%r/%r"
                  % (j_a, j_b, gcfg["total_field"], field_ok, r_a["reason_new"], r_b["reason_new"]))


@check("detect_delistings.smithery_gate_full_flag", mutate_target="detect_delistings",
       mutate=mut_dd_smithery_full_flag)
def chk_dd_smithery_gate_full_flag(is_mutant):
    """第五階段新增：full_flag_tolerant_total_match 的第一個子條件——
    adapter 一手旗標 data.is_full 必須明確是布林 True，缺失／None／False
    一律 fail-closed（極性與 agent_virtuals 的 truncated 相反，見該分支註解）。

    三組情境（三組的 total_count_reported 都與 len(servers) 完全相符，
    所以擋下它們的一定是旗標，不是誤差容忍度）：
      (a) is_full=True  → 應通過；
      (b) is_full=False → 應擋下；
      (c) 整個 is_full 欄位缺失（模擬 2026-09-07 之前的舊快照 schema）→ 應擋下。
    另加一組 (d)：is_full=True 但相對誤差 1.0%（> 容忍度 0.3%）→ 應擋下，
    確認第二個子條件也還在。"""
    sandbox = new_sandbox("dd_mcps_full_mut" if is_mutant else "dd_mcps_full")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_smithery_full_flag(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg = mod.GROUP_SOURCES[MCPS_SRC]["groups"][MCPS_GRP]

    ok_a, _, rs_a = mod.completeness_group(_mcps_data(1000, 1000, is_full=True), gcfg)
    ok_b, _, rs_b = mod.completeness_group(_mcps_data(1000, 1000, is_full=False), gcfg)
    d_c = _mcps_data(1000, 1000, is_full=True)
    del d_c["is_full"]
    ok_c, _, rs_c = mod.completeness_group(d_c, gcfg)
    ok_d, _, rs_d = mod.completeness_group(_mcps_data(1000, 1010, is_full=True), gcfg)  # gap≈0.99%
    guard_active = (ok_a is True) and (ok_b is False) and (ok_c is False) and (ok_d is False)
    return Result(guard_active,
                  "(a)is_full=True,gap=0%%->ok=%r(期望True) (b)is_full=False->ok=%r(期望False) "
                  "(c)is_full 欄位缺失->ok=%r(期望False，fail-closed) "
                  "(d)is_full=True 但 gap=0.99%%>容忍度0.30%%->ok=%r(期望False) reasons=%r/%r/%r/%r"
                  % (ok_a, ok_b, ok_c, ok_d, rs_a, rs_b, rs_c, rs_d))


@check("detect_delistings.smithery_parser_version_floor", mutate_target="detect_delistings",
       mutate=mut_dd_smithery_pv_floor)
def chk_dd_smithery_parser_version_floor(is_mutant):
    """第五階段新增：parser_version 版本下限守門（min_parser_version）。

    三組情境的**快照資料完全相同**（兩側都是乾淨的、完整性守門一定通過），
    唯一變因是 manifest 裡的 parser_version，證明擋下來的是版本守門本身：
      (a) 兩側都是 v3（>= 下限 3、且相同）→ NORMAL，LISTED 事件照常寫入；
      (b) 兩側都是 v2（低於下限）→ GATE_FAIL 且 events.jsonl 零新增；
      (c) v2 → v3（改版當天）→ GATE_FAIL 且 events.jsonl 零新增。
    另外驗證 (d)：完全沒有 manifest → fail-closed，同樣 GATE_FAIL。
    也一併確認其餘子集合不受影響：未設定 min_parser_version 的 gcfg
    呼叫 parser_version_floor_check() 必須原樣回 (True, "")。"""
    sandbox = new_sandbox("dd_mcps_pv_mut" if is_mutant else "dd_mcps_pv")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_smithery_pv_floor(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    scfg = mod.GROUP_SOURCES[MCPS_SRC]

    old = gs_snapshot(_mcps_data(100, 100, start=0))
    new = gs_snapshot(_mcps_data(105, 105, start=0))   # 新增 5 筆、移除 0 筆
    f_old = write_gz_json(os.path.join(sandbox, "track-crypto/data/%s/2030-05-01.json.gz" % MCPS_SRC), old)
    f_new = write_gz_json(os.path.join(sandbox, "track-crypto/data/%s/2030-05-02.json.gz" % MCPS_SRC), new)

    def _run(tag):
        seen, last = set(), {}
        gr, fresh, _e, _a = mod.process_group_source_pair(MCPS_SRC, scfg, f_old, f_new, seen, last)
        # 每組情境用自己的 events.jsonl，避免前一組寫進去的事件影響下一組的去重判斷
        jp = os.path.join(sandbox, "track-crypto/data/%s/events.jsonl" % MCPS_SRC)
        if os.path.exists(jp):
            os.rename(jp, jp + "." + tag)
        return gr[MCPS_GRP]["judged"], len(fresh)

    # (d) 先跑「沒有 manifest」的情境（此時 _manifest 目錄還不存在）
    j_d, n_d = _run("d")
    _dd_manifest(sandbox, ["2030-05-01", "2030-05-02"], source=MCPS_SRC, parser_version=3)
    j_a, n_a = _run("a")
    _dd_manifest(sandbox, ["2030-05-01", "2030-05-02"], source=MCPS_SRC, parser_version=2)
    j_b, n_b = _run("b")
    _dd_manifest(sandbox, ["2030-05-01"], source=MCPS_SRC, parser_version=2)
    _dd_manifest(sandbox, ["2030-05-02"], source=MCPS_SRC, parser_version=3)
    j_c, n_c = _run("c")

    other = mod.GROUP_SOURCES["oracle_feed_directory"]["groups"]["pyth"]
    noop_ok, noop_reason = mod.parser_version_floor_check("oracle_feed_directory", other,
                                                          "2030-05-01", "2030-05-02")
    guard_active = (j_a == "NORMAL" and n_a == 5
                    and j_b == "GATE_FAIL" and n_b == 0
                    and j_c == "GATE_FAIL" and n_c == 0
                    and j_d == "GATE_FAIL" and n_d == 0
                    and noop_ok is True and noop_reason == "")
    return Result(guard_active,
                  "(a)v3->v3 judged=%s 事件=%d(期望 NORMAL/5) (b)v2->v2 judged=%s 事件=%d(期望 GATE_FAIL/0) "
                  "(c)v2->v3 judged=%s 事件=%d(期望 GATE_FAIL/0) (d)無 manifest judged=%s 事件=%d"
                  "(期望 GATE_FAIL/0，fail-closed)；未設定 min_parser_version 的 pyth 子集合 "
                  "no-op=(%r,%r)（期望 (True,'')）"
                  % (j_a, n_a, j_b, n_b, j_c, n_c, j_d, n_d, noop_ok, noop_reason))


@check("detect_delistings.smithery_parser_version_floor.real_replay", mutate_target="detect_delistings",
       mutate=mut_dd_smithery_both_layers)
def chk_dd_smithery_pv_floor_real_replay(is_mutant):
    """real-replay：mcp_smithery 真實歷史快照（VPS 正式資料，唯讀複製）
    2026-09-07（舊 adapter，272 筆、is_full=False、parser_version=2）→
    2026-09-08（新 adapter，11,917 筆、is_full=True、parser_version=3）。

    這一組配對如果被放行，會一次寫進 **11,645 筆假 LISTED 事件**
    （實測 added=11,645、removed=0），而 events.jsonl 不在 .gitignore 排除範圍內，
    會永久污染 git 歷史。本檢查同時驗證兩件事：
      1. 正式程式碼對這組配對判 GATE_FAIL，且 events.jsonl 零新增；
      2. **兩層防線各自獨立**都擋得住——把版本下限守門單獨關掉（完整性守門仍在），
         以及把完整性守門的 is_full 旗標單獨關掉（版本下限守門仍在），
         兩種情況都仍然是 GATE_FAIL。
    兩層的獨立變體一律用**未經 mutation 的原始碼**衍生，所以 mutant 只影響第 1 點：
    mutant 把版本下限守門與完整性守門的兩個子條件一起關掉，第 1 點翻成 NORMAL，
    本檢查 FAIL（只關其中一項翻不了盤，見 mut_dd_smithery_both_layers docstring）。"""
    sandbox = new_sandbox("dd_mcps_real_mut" if is_mutant else "dd_mcps_real")
    base_text = read_source("detect_delistings")
    text = mut_dd_smithery_both_layers(base_text) if is_mutant else base_text

    src_dir = os.path.join(SOURCE_REPO, "track-crypto/data/%s" % MCPS_SRC)
    man_dir = os.path.join(SOURCE_REPO, "track-crypto/data/_manifest")
    need = ["2026-09-07.json.gz", "2026-09-08.json.gz"]
    man_need = ["2026-09-07.json", "2026-09-08.json"]
    if not all(os.path.exists(os.path.join(src_dir, n)) for n in need) or \
       not all(os.path.exists(os.path.join(man_dir, n)) for n in man_need):
        return Result(False, "找不到真實 mcp_smithery 歷史快照或 _manifest，無法做 real-replay 驗證")
    paths = {n: install_binary_copy(os.path.join(src_dir, n), sandbox,
                                     "track-crypto/data/%s/%s" % (MCPS_SRC, n)) for n in need}
    for n in man_need:
        install_binary_copy(os.path.join(man_dir, n), sandbox, "track-crypto/data/_manifest/%s" % n)

    def _judge_with(t, tag):
        p = _install_dd(new_sandbox(tag), t)
        # 版本下限守門讀的是 <TRACK_CRYPTO>/data/_manifest/，所以每個變體都要自己一份資料
        m = load_module(p)
        vs = os.path.dirname(os.path.dirname(os.path.dirname(p)))
        for n in need:
            install_binary_copy(paths[n], vs, "track-crypto/data/%s/%s" % (MCPS_SRC, n))
        for n in man_need:
            install_binary_copy(os.path.join(man_dir, n), vs, "track-crypto/data/_manifest/%s" % n)
        f1 = os.path.join(vs, "track-crypto/data/%s/%s" % (MCPS_SRC, need[0]))
        f2 = os.path.join(vs, "track-crypto/data/%s/%s" % (MCPS_SRC, need[1]))
        seen, last = set(), {}
        gr, fresh, _e, _a = m.process_group_source_pair(MCPS_SRC, m.GROUP_SOURCES[MCPS_SRC],
                                                        f1, f2, seen, last)
        return gr[MCPS_GRP]["judged"], len(fresh), len(gr[MCPS_GRP]["r"]["added_keys"]), \
            len(gr[MCPS_GRP]["r"]["removed_keys"])

    j_main, n_main, added, removed = _judge_with(text, "dd_mcps_real_main")
    j_nopv, n_nopv, _, _ = _judge_with(mut_dd_smithery_pv_floor(base_text), "dd_mcps_real_nopv")
    j_nofull, n_nofull, _, _ = _judge_with(mut_dd_smithery_full_flag(base_text), "dd_mcps_real_nofull")

    guard_active = (j_main == "GATE_FAIL" and n_main == 0
                    and j_nopv == "GATE_FAIL" and n_nopv == 0
                    and j_nofull == "GATE_FAIL" and n_nofull == 0
                    and added == 11645 and removed == 0)
    return Result(guard_active,
                  "真實 2026-09-07(272筆,v2,is_full=False)->2026-09-08(11917筆,v3,is_full=True)："
                  "正式程式碼 judged=%s 事件=%d(期望 GATE_FAIL/0)；"
                  "單獨關掉版本下限守門 judged=%s 事件=%d(期望 GATE_FAIL/0，完整性守門獨立擋下)；"
                  "單獨關掉 is_full 旗標 judged=%s 事件=%d(期望 GATE_FAIL/0，版本下限守門獨立擋下)；"
                  "被擋下的集合差 added=%d removed=%d(期望 11645/0，這就是避免掉的假 LISTED 數量)"
                  % (j_main, n_main, j_nopv, n_nopv, j_nofull, n_nofull, added, removed))


@check("detect_delistings.smithery_breaker_pct", mutate_target="detect_delistings",
       mutate=mut_dd_smithery_breaker_pct)
def chk_dd_smithery_breaker_pct(is_mutant):
    """第五階段新增：把 mcp_smithery 的熔斷門檻**在正式規模下**釘住。
    設定 breaker_pct=1.0%、abs_floor=20，前一日 11,917 筆時
    門檻 = max(20, 1.0% × 11917) = 119.17 筆：
      (a) 移除 119 筆（1.0000%）→ 不觸發，NORMAL；
      (b) 移除 120 筆（1.0070%）→ 觸發，BREAKER。
    兩組資料的完整性守門都通過（is_full=True、自報總數與實得筆數相符），
    所以判定差異來自熔斷門檻本身。順帶斷言 abs_floor 在現行規模下是惰性的
    （119.17 > 20），與設定表註解的主張一致。
    mutant 把門檻放寬到 50%，(b) 翻成 NORMAL，本檢查 FAIL。"""
    sandbox = new_sandbox("dd_mcps_brk_mut" if is_mutant else "dd_mcps_brk")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_smithery_breaker_pct(text)
    script_path = _install_dd(sandbox, text)
    mod = load_module(script_path)
    gcfg = mod.GROUP_SOURCES[MCPS_SRC]["groups"][MCPS_GRP]

    N = 11917
    d_old = _mcps_data(N, N)
    d_119 = _mcps_data(N - 119, N - 119)
    d_120 = _mcps_data(N - 120, N - 120)
    r_a = mod.compare_group(MCPS_SRC, MCPS_GRP, gcfg, d_old, d_119)
    r_b = mod.compare_group(MCPS_SRC, MCPS_GRP, gcfg, d_old, d_120)
    j_a, j_b = mod.judge(r_a, gcfg), mod.judge(r_b, gcfg)
    floor_inert = r_a["threshold_count"] > gcfg["abs_floor"]
    guard_active = (j_a == "NORMAL" and j_b == "BREAKER" and floor_inert
                    and len(r_a["removed_keys"]) == 119 and len(r_b["removed_keys"]) == 120)
    return Result(guard_active,
                  "前日 n=%d 門檻=%.2f 筆（breaker_pct=%.2f%%, abs_floor=%d）；"
                  "(a)移除119筆(%.4f%%) judged=%s(期望 NORMAL) (b)移除120筆(%.4f%%) judged=%s(期望 BREAKER)；"
                  "abs_floor 在現行規模下惰性(門檻>abs_floor)=%s"
                  % (N, r_a["threshold_count"], gcfg["breaker_pct"], gcfg["abs_floor"],
                     r_a["removed_rate"], j_a, r_b["removed_rate"], j_b, floor_inert))


# ==========================================================================
# GROUP_SOURCES 剩下的 3 個「恆真式」完整性守門（2026-09-08 第五階段新增，
# 見 track-crypto/scripts/detect_delistings.py 第五階段說明區塊、
# 本機 docs/0908-4-tautological-gates-report.md）
#
# 背景：任務 D 修掉 SOURCES["x402_bazaar"] 之後，GROUP_SOURCES 裡還有 3 個子集合
# 用同一個壞掉的寫法——比對的 count 就是 adapter 自己算的 len(...)，判斷式恆為假、
# 守門恆為真。本輪逐一親打上游後：ofac_sanctions_crypto 改比對上游 SDN.XML 檔頭的
# Record_Count（reported_total_match）；openrouter_providers 與
# crypto_project_liveness 上游確認沒有任何總數可比，改用 range_check。
# 以下 5 條檢查把「這 3 個守門都不可以再是恆真式」鎖住，破壞驗證一律是
# **把設定改回恆真式**（＝重現本輪修掉的那個 bug），與任務 D 的手法一致。
# ==========================================================================

_TAUT_MUT_TAIL = "  # [selftest mutant] 恆真式守門重現"


def mut_dd_ofac_tautological_gate(text):
    """把 ofac_sanctions_crypto 的守門設定改回恆真式（比對 adapter 自算的 count）。
    對應檢查 detect_delistings.ofac_gate_not_tautological。"""
    return apply_mutation(
        text,
        '                "completeness": "reported_total_match",\n'
        '                "reported_total_field": "reported_total",',
        '                "completeness": "total_match", "total_fields": ("count",),' + _TAUT_MUT_TAIL + '\n'
        '                "reported_total_field": "reported_total",',
        "dd_ofac_tautological_gate")


def mut_dd_ofac_legacy_range(text):
    """關掉 completeness_group() 的 reported_total_match 舊快照相容分支的區間比較，
    讓任何筆數都算通過。對應檢查 detect_delistings.ofac_gate_legacy_range。"""
    return apply_mutation(
        text,
        '            if n_raw < lo_g or n_raw > hi_g:',
        '            if False:  # [selftest mutant] reported_total_match legacy range disabled',
        "dd_ofac_legacy_range")


def mut_dd_openrouter_providers_tautological_gate(text):
    """把 openrouter_providers 的守門設定改回恆真式。
    對應檢查 detect_delistings.openrouter_providers_gate_not_tautological。"""
    return apply_mutation(
        text,
        '                "completeness": "range_check", "range": (92, 117),',
        '                "completeness": "total_match", "total_fields": ("count",),' + _TAUT_MUT_TAIL,
        "dd_openrouter_providers_tautological_gate")


def mut_dd_crypto_project_liveness_tautological_gate(text):
    """把 crypto_project_liveness 的守門設定改回恆真式。
    對應檢查 detect_delistings.crypto_project_liveness_gate_not_tautological。"""
    return apply_mutation(
        text,
        '                "completeness": "range_check", "range": (1115, 1383),',
        '                "completeness": "total_match", "total_fields": ("count",),' + _TAUT_MUT_TAIL,
        "dd_crypto_project_liveness_tautological_gate")


def _taut_pair(mod, source, group, data_old, data_new):
    """跑一組相鄰快照（直接餵 data 物件，不落地檔案——GROUP_SOURCES 路徑的
    compare_group() 本來就吃 data 物件，比照既有 chk_dd_group_integrity_gate 的用法）。"""
    gcfg = mod.GROUP_SOURCES[source]["groups"][group]
    r = mod.compare_group(source, group, gcfg, data_old, data_new)
    return mod.judge(r, gcfg), r


@check("detect_delistings.ofac_gate_not_tautological",
       mutate_target="detect_delistings", mutate=mut_dd_ofac_tautological_gate)
def chk_dd_ofac_gate_not_tautological(is_mutant):
    """核心不變量：ofac_sanctions_crypto 的完整性守門**不可以**是恆真式。

    用互為反例的兩組資料，把守門釘在「上游 SDN.XML 檔頭自報的 Record_Count」上：

      甲、data.count 與 len(items) 完全自我一致（都是 98），但上游說有 598 筆
          -> **必須** GATE_FAIL。恆真式守門在這裡會放行。
      乙、data.count 故意說謊（宣稱 598，實際 98），但上游自報總數與 len(items)
          相符（都是 98）-> **必須** NORMAL。恆真式守門在這裡會誤擋。

    兩組的移除量都是 2 筆／100 筆，熔斷門檻 max(abs_floor=5, 1.0%×100=1)=5，
    刻意壓在門檻之下，確保這條檢查只測完整性守門本身（比照既有
    detect_delistings.x402_gate_not_tautological 的設計）。
    #mutant 把設定改回 total_match+count（＝重現本輪修掉的 bug），甲案會放行，本檢查翻盤。
    """
    sandbox = new_sandbox("dd_ofac_taut_mut" if is_mutant else "dd_ofac_taut")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_ofac_tautological_gate(text)
    mod = load_module(_install_dd(sandbox, text))
    gcfg = mod.GROUP_SOURCES["ofac_sanctions_crypto"]["groups"]["_items"]

    items100 = [gs_item("uid", "U%d" % i, "sdn_name", "n%d" % i) for i in range(100)]
    items98 = items100[:98]
    base = {"count": 100, "reported_total": 100, "items": items100}

    # 甲：自我一致但上游說更多（模擬 CSV 只下載到一半）
    judged_a, _ = _taut_pair(mod, "ofac_sanctions_crypto", "_items",
                             base, {"count": 98, "reported_total": 598, "items": items98})
    # 乙：adapter 自算欄位說謊，但上游自報總數與實得筆數相符
    judged_b, _ = _taut_pair(mod, "ofac_sanctions_crypto", "_items",
                             base, {"count": 598, "reported_total": 98, "items": items98})
    # 丙：只差 1 筆也必須擋下來——本來源的容忍度是 0（嚴格相等），
    #     這一條把「不可以偷偷放寬成容忍幾筆」也釘住（實測依據見 GROUP_SOURCES 設定註解：
    #     OFAC 單次發布變動量可達 +65 列，任何非零容忍度都是兩頭不討好）。
    judged_c, _ = _taut_pair(mod, "ofac_sanctions_crypto", "_items",
                             base, {"count": 98, "reported_total": 99, "items": items98})

    # 設定表本身也一併釘住：不可以再有 total_fields，且自報欄位不可以指回 adapter 自算的 count。
    cfg_clean = ("total_fields" not in gcfg) and (gcfg.get("reported_total_field") not in ("count", "total"))

    guard_active = ((judged_a == "GATE_FAIL") and (judged_b == "NORMAL")
                    and (judged_c == "GATE_FAIL") and cfg_clean)
    return Result(guard_active,
                  "甲(count=98==len=98 但 reported_total=598)judged=%s(期望 GATE_FAIL)；"
                  "乙(count=598 說謊 但 reported_total=98==len)judged=%s(期望 NORMAL)；"
                  "丙(reported_total=99 vs len=98，只差 1 筆)judged=%s(期望 GATE_FAIL，容忍度=0)；"
                  "GROUP_SOURCES 無 total_fields 且 reported_total_field=%r -> %s"
                  % (judged_a, judged_b, judged_c, gcfg.get("reported_total_field"), cfg_clean))


@check("detect_delistings.ofac_gate_legacy_range",
       mutate_target="detect_delistings", mutate=mut_dd_ofac_legacy_range)
def chk_dd_ofac_gate_legacy_range(is_mutant):
    """舊快照相容分支：adapter PARSER_VERSION 1（2026-09-08 之前）的快照沒有
    reported_total 欄位，守門退回 legacy_range_check（筆數是否落在實測歷史區間）。

    兩個方向都驗：
      甲、區間內（19,000 筆，區間 [17387,21262]）-> 必須 NORMAL。這一條同時保證
          「12 份既有快照重放不會整批變成 GATE_FAIL」這個相容性要求。
      乙、區間外（100 筆）-> 必須 GATE_FAIL。這一條保證相容分支**不是**放行一切的
          空殼（否則只是把恆真式換個地方留著）。
    #mutant 關掉區間比較後乙案會放行，本檢查翻盤成 FAIL。
    """
    sandbox = new_sandbox("dd_ofac_legacy_mut" if is_mutant else "dd_ofac_legacy")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_ofac_legacy_range(text)
    mod = load_module(_install_dd(sandbox, text))
    gcfg = mod.GROUP_SOURCES["ofac_sanctions_crypto"]["groups"]["_items"]
    lo, hi = gcfg["legacy_range"]

    n_in = 19000  # 落在 [17387, 21262] 內
    big = [gs_item("uid", "U%d" % i, "sdn_name", "n%d" % i) for i in range(n_in)]
    # 舊格式：data 完全沒有 reported_total 這個鍵
    judged_in, _ = _taut_pair(mod, "ofac_sanctions_crypto", "_items",
                              {"count": n_in, "items": big},
                              {"count": n_in - 20, "items": big[:n_in - 20]})
    small = [gs_item("uid", "U%d" % i, "sdn_name", "n%d" % i) for i in range(100)]
    judged_out, _ = _taut_pair(mod, "ofac_sanctions_crypto", "_items",
                               {"count": 100, "items": small},
                               {"count": 98, "items": small[:98]})

    guard_active = (judged_in == "NORMAL") and (judged_out == "GATE_FAIL")
    return Result(guard_active,
                  "legacy_range=[%d,%d]；區間內 n=%d judged=%s(期望 NORMAL)；"
                  "區間外 n=100 judged=%s(期望 GATE_FAIL)"
                  % (lo, hi, n_in - 20, judged_in, judged_out))


@check("detect_delistings.openrouter_providers_gate_not_tautological",
       mutate_target="detect_delistings", mutate=mut_dd_openrouter_providers_tautological_gate)
def chk_dd_openrouter_providers_gate_not_tautological(is_mutant):
    """核心不變量：openrouter_providers 的完整性守門**不可以**是恆真式。

    上游（2026-09-08 親驗）回應頂層只有 data 一個鍵、沒有任何總數，因此改用
    range_check[92,117]。用互為反例的兩組資料證明守門讀的是「筆數落在區間內」
    而不是 adapter 自算的 count：

      甲、count 與 len(providers) 完全自我一致（都是 91），但 91 跌破區間下界 92
          -> **必須** GATE_FAIL。恆真式守門在這裡會放行。
      乙、count 故意說謊（宣稱 598，實際 93 筆、落在區間內）-> **必須** NORMAL。
          恆真式守門在這裡會誤擋。

    兩組移除量分別是 4 筆／2 筆（前日 95 筆），熔斷門檻 max(5, 1.0%×95=0.95)=5，
    都壓在門檻之下，確保只測守門本身。
    #mutant 把設定改回 total_match+count，甲案會放行，本檢查翻盤成 FAIL。
    """
    sandbox = new_sandbox("dd_orp_taut_mut" if is_mutant else "dd_orp_taut")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_openrouter_providers_tautological_gate(text)
    mod = load_module(_install_dd(sandbox, text))
    gcfg = mod.GROUP_SOURCES["openrouter_providers"]["groups"]["_providers"]
    # 注意：#mutant 會把整行設定換成 total_match，"range" 鍵會消失，所以這裡用
    # gcfg.get()，不可以直接索引（否則破壞驗證會變成 EXCEPTION 而不是「翻盤成 FAIL」）。
    rng = gcfg.get("range")

    prov = [gs_item("slug", "p%d" % i, "name", "P%d" % i) for i in range(95)]
    old = {"count": 95, "providers": prov}
    judged_a, _ = _taut_pair(mod, "openrouter_providers", "_providers",
                             old, {"count": 91, "providers": prov[:91]})
    judged_b, _ = _taut_pair(mod, "openrouter_providers", "_providers",
                             old, {"count": 598, "providers": prov[:93]})

    cfg_clean = ("total_fields" not in gcfg) and (gcfg["completeness"] != "total_match")
    guard_active = (judged_a == "GATE_FAIL") and (judged_b == "NORMAL") and cfg_clean
    return Result(guard_active,
                  "range=%r；甲(count=91==len=91，跌破下界)judged=%s(期望 GATE_FAIL)；"
                  "乙(count=598 說謊 但 len=93 在區間內)judged=%s(期望 NORMAL)；"
                  "設定無 total_fields 且 completeness=%r -> %s"
                  % (rng, judged_a, judged_b, gcfg["completeness"], cfg_clean))


@check("detect_delistings.crypto_project_liveness_gate_not_tautological",
       mutate_target="detect_delistings", mutate=mut_dd_crypto_project_liveness_tautological_gate)
def chk_dd_crypto_project_liveness_gate_not_tautological(is_mutant):
    """核心不變量：crypto_project_liveness 的完整性守門**不可以**是恆真式。

    上游（2026-09-08 親驗）回傳裸 JSON 陣列、沒有任何中繼欄位，因此改用
    range_check[1115,1383]。互為反例的兩組資料（主鍵是 (name, date) 複合鍵）：

      甲、count 與 len(hacks) 自我一致（都是 1114），但 1114 跌破區間下界 1115
          -> **必須** GATE_FAIL。恆真式守門在這裡會放行。
      乙、count 故意說謊（宣稱 9999，實際 1116 筆、落在區間內）-> **必須** NORMAL。

    兩組移除量分別是 6 筆／4 筆（前日 1120 筆），熔斷門檻 max(5, 1.0%×1120=11.2)=11.2，
    都壓在門檻之下。合成項目不含 defillamaId，因此第四階段（任務 B）新增的
    reconcile_renames() 抵銷層 stable_identity() 一律回 None、不會被觸發，
    本檢查與該機制互不干擾。
    #mutant 把設定改回 total_match+count，甲案會放行，本檢查翻盤成 FAIL。
    """
    sandbox = new_sandbox("dd_cpl_taut_mut" if is_mutant else "dd_cpl_taut")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_crypto_project_liveness_tautological_gate(text)
    mod = load_module(_install_dd(sandbox, text))
    gcfg = mod.GROUP_SOURCES["crypto_project_liveness"]["groups"]["_hacks"]
    # 同上：#mutant 之後 "range" 鍵不存在，必須用 gcfg.get()。
    rng = gcfg.get("range")

    hacks = [{"name": "H%d" % i, "date": 1700000000 + i} for i in range(1120)]
    old = {"count": 1120, "hacks": hacks}
    judged_a, _ = _taut_pair(mod, "crypto_project_liveness", "_hacks",
                             old, {"count": 1114, "hacks": hacks[:1114]})
    judged_b, _ = _taut_pair(mod, "crypto_project_liveness", "_hacks",
                             old, {"count": 9999, "hacks": hacks[:1116]})

    cfg_clean = ("total_fields" not in gcfg) and (gcfg["completeness"] != "total_match")
    guard_active = (judged_a == "GATE_FAIL") and (judged_b == "NORMAL") and cfg_clean
    return Result(guard_active,
                  "range=%r；甲(count=1114==len=1114，跌破下界)judged=%s(期望 GATE_FAIL)；"
                  "乙(count=9999 說謊 但 len=1116 在區間內)judged=%s(期望 NORMAL)；"
                  "設定無 total_fields 且 completeness=%r -> %s"
                  % (rng, judged_a, judged_b, gcfg["completeness"], cfg_clean))


@check("detect_delistings.tautological_gates_real_replay",
       mutate_target="detect_delistings", mutate=mut_dd_group_integrity_gate)
def chk_dd_tautological_gates_real_replay(is_mutant):
    """real-replay：用 VPS 正式資料的**真實歷史快照**（唯讀複製，2026-09-07）驗證
    本輪三個新守門在真實 schema 上的行為，避免只靠合成資料。

      (a) 三個來源的真實完整資料自我比對 -> 全部 NORMAL（保證歷史重放不會整批
          變成 GATE_FAIL）。
      (b) 保留真實欄位形狀、只動一個地方：
            ofac                    ：注入 reported_total = 真實筆數 + 500
                                      （模擬「CSV 少收 500 筆」）-> 必須 GATE_FAIL
            openrouter_providers    ：清單截斷到 50 筆（< 下界 92）-> 必須 GATE_FAIL
            crypto_project_liveness ：清單截斷到 500 筆（< 下界 1115）-> 必須 GATE_FAIL
    真實資料本身從未跌出校準區間（區間即以此校準），純粹重放測不到「跌出區間」
    分支，因此沿用既有 detect_delistings.oracle_pyth_range_check_real_replay 的
    「真實 schema + 人為破壞」混合手法。
    #mutant 沿用既有 mut_dd_group_integrity_gate（關掉 range_check 比較），
    兩個 range_check 來源的破壞案會變成放行，本檢查翻盤成 FAIL。
    """
    sandbox = new_sandbox("dd_taut_real_mut" if is_mutant else "dd_taut_real")
    text = read_source("detect_delistings")
    if is_mutant:
        text = mut_dd_group_integrity_gate(text)
    mod = load_module(_install_dd(sandbox, text))

    date = "2026-09-07"
    specs = [
        ("ofac_sanctions_crypto", "_items", "items", None),
        ("openrouter_providers", "_providers", "providers", 50),
        ("crypto_project_liveness", "_hacks", "hacks", 500),
    ]
    detail = []
    ok_all = True
    for source, group, path_key, cut in specs:
        real_file = os.path.join(SOURCE_REPO, "track-crypto/data", source, date + ".json.gz")
        if not os.path.exists(real_file):
            return Result(False, "找不到真實歷史快照 %s，無法做 real-replay 驗證" % real_file)
        f_real = install_binary_copy(real_file, sandbox, "%s_real.json.gz" % source)
        data_full = mod.load(f_real)["data"]
        n_real = len(data_full[path_key])
        judged_full, _ = _taut_pair(mod, source, group, data_full, data_full)
        bad = dict(data_full)
        if cut is None:
            bad["reported_total"] = n_real + 500          # 真實 schema，只多注入上游自報總數
        else:
            bad = dict(data_full, **{path_key: data_full[path_key][:cut]})
        judged_bad, _ = _taut_pair(mod, source, group, data_full, bad)
        ok = (judged_full == "NORMAL") and (judged_bad == "GATE_FAIL")
        ok_all = ok_all and ok
        detail.append("%s(真實 n=%d 自我比對=%s，破壞案=%s)" % (source, n_real, judged_full, judged_bad))

    return Result(ok_all, "%s 真實快照：%s（各案期望 NORMAL / GATE_FAIL）" % (date, "；".join(detail)))


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
    _, finalize_msg = _finalize_workdir(any_fail)
    print(finalize_msg)
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
