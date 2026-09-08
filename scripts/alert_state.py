#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/alert_state.py — 告警檔語意登記表 + 死人開關判定（單一事實來源）

為什麼要有這支程式（2026-09-09，修死人開關永久紅燈）
--------------------------------------------------------------------------
`scripts/push.sh` 原本用「根目錄有沒有這 7 個檔名」判斷要不要對 healthchecks.io
回報 /fail。這個前提對其中 6 個檔成立、對另外 2 個不成立：

  - `ALERT.md`／`ALERT-DETECT.md`／`ALERT-HEALTH.md`／`ALERT-BACKUP.md`／
    `ALERT-CEXGATE.md`／`ALERT-DELISTGATE.md` 是**即時狀態旗標**：
    產生它的程式每次執行都重新計算目前的真相，異常排除就把檔案刪掉。
    對這 6 個檔，「存在」＝「現在有事」，用檔案存不存在判斷是正確的。

  - `ALERT-DELIST.md`（`track-crypto/scripts/detect_delistings.py` 獨佔）與
    `ALERT-CEXBREAKER.md`（`scripts/cex_events.py` 獨佔）是**永久事件帳本**：
    檔頭自己寫著「本檔案只會新增，不會自動刪除既有區塊：每一則對應一組已發生的
    熔斷事件（特定來源×特定比對日期），**不是「現在是否有異常」的即時狀態旗標**」。
    全 repo 沒有任何程式碼路徑會刪除它們。對這 2 個檔，「存在」＝「歷史上曾經
    發生過至少一次需要人工複核的事」，**不等於**「現在有事」。

實測後果：`ALERT-DELIST.md` 於 2026-09-07 11:31:54（commit 5d29907）產生後從未消失，
死人開關自該日起每天回報 /fail 且永遠不會轉綠 —— 一個永遠紅著的燈跟沒有燈一樣，
「排程今天沒跑」這個它唯一該偵測的訊號被淹沒了。
`scripts/cex_events.py` 的 `write_alert_block_cexbreaker()` docstring 已經預見這件事
（「而 scripts/push.sh 的死人開關是用「檔案存不存在」判斷的，等於部署即報 fail」），
但只用「只寫最新一組轉換」緩解，沒有根治判定方式本身。

本程式做的事
--------------------------------------------------------------------------
1. 把「每一個告警檔是哪一種語意」集中登記在 ALERT_REGISTRY（唯一事實來源）。
   在此之前這份清單被硬編碼兩份（`scripts/push.sh` 的 `[ -f ... ]` 條件式、
   `scripts/daily_report.py` 的 `alert_files`），彼此不同步：`cex_events.py`
   2026-09-08 新增的 `ALERT-CEXBREAKER.md` 兩邊都漏掉，熔斷已寫檔卻零通知管道。
2. 依語意分別算出兩個訊號：
     PRIMARY（排程健康）：任何**即時狀態旗標**存在 → fail。
       語意＝「今天的抓取／偵測／備份流程本身現在有問題」，異常排除隔天自動轉綠。
     REVIEW （待人工複核）：任何**永久事件帳本**裡有**未確認**的區塊 → fail。
       語意＝「有已發生的熔斷事件還沒有人看過」，人工加註 ack 後轉綠。
3. 「未確認」的判定沿用兩個帳本檔頭**已經公開寫出來的慣例**（不是新發明）：
   在該區塊內任一行加上 `<!-- ack:YYYY-MM-DD -->` 這個 HTML 註解即視為已確認。
   `--ack` 子命令提供安全的加註方式（指定 marker，一次只確認一則）。

fail-closed（硬性設計原則）
--------------------------------------------------------------------------
所有「判斷不出來」的情況一律往報警倒，絕不預設綠燈：
  a. 根目錄出現**登記表裡沒有**的 `ALERT*.md` → PRIMARY fail。
     這條直接消滅「新增第 9 個告警檔但忘了接線」這類漏報（ALERT-CEXBREAKER.md
     就是這樣被漏掉 4 天的）。
  b. 帳本檔讀取／解析失敗 → 該檔視為「有未確認區塊」→ REVIEW fail。
  c. 帳本檔存在但解析不出任何 `## ` 區塊（檔案形狀不符預期）→ REVIEW fail。
  d. ack 註解的日期必須是 `\\d{4}-\\d{2}-\\d{2}`。檔頭說明文字裡的字面
     `<!-- ack:YYYY-MM-DD -->` 範例不會被誤認為真的 ack（YYYY 不是數字），
     寫壞的 ack（例如 `<!-- ack:soon -->`）也不算數。
  e. 本程式自己丟例外 → 不會印出 `DEADMAN_PRIMARY=ok`，`scripts/push.sh` 那側
     的預設值是 fail，因此整支程式炸掉＝紅燈，不會靜默變綠。

輸出契約（`--deadman`，供 scripts/push.sh 解析）
--------------------------------------------------------------------------
stdout **最後兩行**固定為：
    DEADMAN_PRIMARY=ok|fail
    DEADMAN_REVIEW=ok|fail
在這兩行之前是人類可讀的逐項原因（**實際觸發的是哪些檔案**，這正是原本
`push.sh` 第 139 行寫死成「ALERT.md 存在 → 回報 fail」所隱藏的資訊）。
呼叫端必須「只有明確看到 `=ok` 才當綠燈」，這樣任何當機／缺檔／輸出被截斷
都自動落在紅燈側。

結束碼：0＝兩者皆 ok；1＝PRIMARY fail；2＝PRIMARY ok 但 REVIEW fail；3＝判定本身失敗。
（呼叫端不應只靠結束碼，見上面的輸出契約。）
"""
import argparse
import os
import re
import sys
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --------------------------------------------------------------------------
# 告警檔語意登記表（唯一事實來源）
# --------------------------------------------------------------------------
# kind:
#   "realtime" 即時狀態旗標：產生者每次執行重算，異常排除時自己刪檔。
#                「檔案存在」＝「現在有事」→ 直接進 PRIMARY。
#   "ledger"   永久事件帳本：只增不刪，每則區塊對應一次已發生的事件。
#                「檔案存在」不代表現在有事 → 改看「有沒有未 ack 的區塊」，進 REVIEW。
#
# owner／evidence 欄位記錄「誰寫這個檔、哪一行刪、哪一行寫」，方便日後查核；
# 行號是 2026-09-09 對 VPS HEAD fecb309 ＋本補丁後的檔案實測的結果（push.sh／healthcheck.py
# 為套用本補丁後的行號），程式邏輯不依賴這些數字，僅供人工查核。
ALERT_REGISTRY = {
    "ALERT.md": {
        "kind": "realtime",
        "owner": "scripts/healthcheck.py",
        "evidence": "healthcheck.py:849 open(OUT,'w') 寫；:819-821 issues 為空時 os.remove(OUT)",
        "desc": "每日自我檢查（缺檔／體積異常／manifest 失敗）",
    },
    "ALERT-DETECT.md": {
        "kind": "realtime",
        "owner": "scripts/push.sh",
        "evidence": "push.sh:59 寫；:61 rm -f（detect_changes.py 成功時）",
        "desc": "track-gov 內容改寫／下架偵測程式執行失敗",
    },
    "ALERT-HEALTH.md": {
        "kind": "realtime",
        "owner": "scripts/push.sh",
        "evidence": "push.sh:90 寫；:92 rm -f（healthcheck.py 成功時）",
        "desc": "自我檢查程式本身執行失敗",
    },
    "ALERT-BACKUP.md": {
        "kind": "realtime",
        "owner": "scripts/push.sh",
        "evidence": "push.sh:111（同步失敗）／:121（HF_TOKEN 未設定）寫；:108 rm -f（hf_sync.py 成功時）",
        "desc": "Hugging Face 異地備份未同步",
    },
    "ALERT-CEXGATE.md": {
        "kind": "realtime",
        "owner": "scripts/healthcheck.py（check_cex_gate_skips）",
        "evidence": "healthcheck.py:794 寫；:762-764 今日無觸發時 os.remove",
        "desc": "cex_events 完整性守門觸發（只反映最新一次轉換）",
    },
    "ALERT-DELISTGATE.md": {
        "kind": "realtime",
        "owner": "scripts/healthcheck.py（check_delist_gate_fail）",
        "evidence": "healthcheck.py:727 寫；:690-692 今日無觸發時 os.remove",
        "desc": "track-crypto 下架偵測完整性守門觸發（只反映最新一次轉換）",
    },
    "ALERT-DELIST.md": {
        "kind": "ledger",
        "owner": "track-crypto/scripts/detect_delistings.py",
        "evidence": ("detect_delistings.py:2920（write_alert_block）／:2053（write_alert_block_group）"
                     "open(...,'w') 整檔重寫（讀既有→合併）；檔頭 :2914／:2048 明文"
                     "『只會新增，不會自動刪除既有區塊』；"
                     "全 repo 無任何 os.remove/rm -f 命中此檔名"),
        "desc": "軌一「自清單消失」規模異常熔斷（每則＝一組來源×比對日期）",
    },
    "ALERT-CEXBREAKER.md": {
        "kind": "ledger",
        "owner": "scripts/cex_events.py",
        "evidence": ("cex_events.py:264（write_alert_block_cexbreaker）open(...,'w') 整檔重寫"
                     "（讀既有→合併）；檔頭 :259-261 明文『只會新增，不會自動刪除既有區塊』；"
                     "全 repo 無任何 os.remove/rm -f 命中此檔名"),
        "desc": "CEX 上下架規模異常熔斷（每則＝一組交易所×比對日期）",
    },
}

REALTIME_ALERTS = [k for k, v in ALERT_REGISTRY.items() if v["kind"] == "realtime"]
LEDGER_ALERTS = [k for k, v in ALERT_REGISTRY.items() if v["kind"] == "ledger"]
# 對外提供的完整檔名清單（daily_report.py 用；順序固定＝先即時旗標後永久帳本）。
ALL_ALERTS = REALTIME_ALERTS + LEDGER_ALERTS

# 根目錄裡「看起來像告警檔」的命名規則。用來偵測登記表以外的新檔案（fail-closed a）。
ALERT_FILENAME_RE = re.compile(r"^ALERT(-[A-Z0-9]+)*\.md$")

# ack 註解：日期必須是真的數字，檔頭說明裡的 `<!-- ack:YYYY-MM-DD -->` 範例不會命中。
ACK_RE = re.compile(r"<!--\s*ack:(\d{4}-\d{2}-\d{2})\s*-->")
# 區塊識別 marker：detect_delistings.py 與 cex_events.py 各自寫入的 HTML 註解。
# 本程式**不解析它的內部格式**（目前實測有三種：
#   <!-- detect_delistings:<source>:<date> -->
#   <!-- detect_delistings:GROUP:<source>:<group>:<date> -->
#   <!-- cex_events:<exchange>:<date> -->），
# 只把「第一個非 ack 的 HTML 註解」當成這一則的識別碼，
# 未來新增第四種格式不需要改本程式。
MARKER_RE = re.compile(r"<!--\s*(?!ack:)([^>]*?)\s*-->")


class Block(object):
    """帳本檔裡的一則事件區塊（從 `## ` 標題行到下一個 `## ` 標題行之前）。"""

    def __init__(self, heading, text, start_line):
        self.heading = heading
        self.text = text
        self.start_line = start_line

    @property
    def marker(self):
        m = MARKER_RE.search(self.text)
        return m.group(0) if m else None

    @property
    def ack_date(self):
        m = ACK_RE.search(self.text)
        return m.group(1) if m else None

    @property
    def acked(self):
        return self.ack_date is not None


def split_blocks(text):
    """把帳本檔切成一則一則的事件區塊。

    切法：以行首 `## ` 為界。第一個 `## ` 之前的內容是檔頭說明，**不算區塊**
    （檔頭裡有 `<!-- ack:YYYY-MM-DD -->` 的字面範例，不能被當成任何一則的 ack）。
    """
    blocks = []
    cur_heading = None
    cur_lines = []
    cur_start = 0
    for i, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            if cur_heading is not None:
                blocks.append(Block(cur_heading, "\n".join(cur_lines), cur_start))
            cur_heading = line[3:].strip()
            cur_lines = [line]
            cur_start = i
        elif cur_heading is not None:
            cur_lines.append(line)
    if cur_heading is not None:
        blocks.append(Block(cur_heading, "\n".join(cur_lines), cur_start))
    return blocks


def scan_ledger(path):
    """讀一個帳本檔，回傳 (blocks, unacked, error)。

    error 不是 None 時代表這個檔沒辦法可靠判定 —— 呼叫端一律當成「有未確認區塊」
    （fail-closed b／c），不可以因為讀不到就當作沒事。
    """
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        return [], [], "讀取失敗：%s: %s" % (type(e).__name__, e)
    blocks = split_blocks(text)
    if not blocks:
        return [], [], "檔案存在但解析不出任何 `## ` 區塊（形狀不符預期，不敢當成沒事）"
    return blocks, [b for b in blocks if not b.acked], None


def evaluate(repo=REPO):
    """算出 PRIMARY／REVIEW 兩個訊號。回傳 dict，不寫任何檔案、不連外網。"""
    res = {
        "primary_fail": False,
        "review_fail": False,
        "realtime_present": [],   # [(fname, desc)]
        "unregistered": [],       # [fname]
        "ledgers": {},            # fname -> dict(total, unacked, error, blocks)
        "reasons": [],            # 人類可讀的逐項原因
    }

    # ---- PRIMARY：即時狀態旗標 ----
    for fname in REALTIME_ALERTS:
        if os.path.isfile(os.path.join(repo, fname)):
            res["realtime_present"].append((fname, ALERT_REGISTRY[fname]["desc"]))
            res["primary_fail"] = True
            res["reasons"].append(
                "PRIMARY fail ← 即時狀態旗標 %s 存在（%s；由 %s 產生，異常排除時會自動刪除）"
                % (fname, ALERT_REGISTRY[fname]["desc"], ALERT_REGISTRY[fname]["owner"]))

    # ---- fail-closed a：登記表以外的告警檔 ----
    try:
        entries = sorted(os.listdir(repo))
    except Exception as e:
        res["primary_fail"] = True
        res["reasons"].append("PRIMARY fail ← 無法列出 repo 根目錄（%s: %s），fail-closed"
                              % (type(e).__name__, e))
        entries = []
    for fname in entries:
        if not ALERT_FILENAME_RE.match(fname):
            continue
        if fname in ALERT_REGISTRY:
            continue
        if not os.path.isfile(os.path.join(repo, fname)):
            continue
        res["unregistered"].append(fname)
        res["primary_fail"] = True
        res["reasons"].append(
            "PRIMARY fail ← 發現未登記的告警檔 %s。它的語意（即時旗標／永久帳本）不明，"
            "依 fail-closed 一律報警：請到 scripts/alert_state.py 的 ALERT_REGISTRY 登記它。"
            % fname)

    # ---- REVIEW：永久事件帳本 ----
    for fname in LEDGER_ALERTS:
        path = os.path.join(repo, fname)
        if not os.path.isfile(path):
            res["ledgers"][fname] = {"present": False, "total": 0, "unacked": [], "error": None}
            continue
        blocks, unacked, error = scan_ledger(path)
        res["ledgers"][fname] = {"present": True, "total": len(blocks),
                                 "unacked": unacked, "error": error}
        if error:
            res["review_fail"] = True
            res["reasons"].append("REVIEW fail ← 永久事件帳本 %s %s" % (fname, error))
            continue
        if unacked:
            res["review_fail"] = True
            res["reasons"].append(
                "REVIEW fail ← 永久事件帳本 %s 有 %d/%d 則未確認：%s"
                % (fname, len(unacked), len(blocks),
                   "、".join((b.marker or b.heading) for b in unacked)))
        else:
            res["reasons"].append(
                "REVIEW ok  ← 永久事件帳本 %s 全部 %d 則都已加註 ack" % (fname, len(blocks)))

    if not res["realtime_present"] and not res["unregistered"]:
        res["reasons"].insert(0, "PRIMARY ok  ← %d 個即時狀態旗標全部不存在，且根目錄沒有未登記的告警檔"
                              % len(REALTIME_ALERTS))
    return res


def cmd_deadman(repo):
    try:
        res = evaluate(repo)
    except Exception:
        # fail-closed e：任何未預期例外都不得印出 =ok。
        sys.stdout.write("判定程式本身發生未預期例外，依 fail-closed 視同紅燈：\n")
        sys.stdout.write(traceback.format_exc())
        sys.stdout.write("DEADMAN_PRIMARY=fail\nDEADMAN_REVIEW=fail\n")
        sys.stdout.flush()
        return 3
    for r in res["reasons"]:
        print(r)
    # 契約：這兩行固定放最後，且只有確定綠燈時才會出現 =ok。
    print("DEADMAN_PRIMARY=%s" % ("fail" if res["primary_fail"] else "ok"))
    print("DEADMAN_REVIEW=%s" % ("fail" if res["review_fail"] else "ok"))
    if res["primary_fail"]:
        return 1
    if res["review_fail"]:
        return 2
    return 0


def cmd_list(repo):
    print("== 告警檔語意登記表（scripts/alert_state.py ALERT_REGISTRY）==")
    for fname in ALL_ALERTS:
        meta = ALERT_REGISTRY[fname]
        exists = os.path.isfile(os.path.join(repo, fname))
        print("%-22s %-8s %-6s %s" % (fname, meta["kind"], "存在" if exists else "不存在", meta["desc"]))
        print("%-22s %s" % ("", meta["evidence"]))
    print("")
    print("== 永久事件帳本的區塊確認狀態 ==")
    for fname in LEDGER_ALERTS:
        path = os.path.join(repo, fname)
        if not os.path.isfile(path):
            print("%s：不存在" % fname)
            continue
        blocks, unacked, error = scan_ledger(path)
        if error:
            print("%s：%s" % (fname, error))
            continue
        print("%s：共 %d 則，未確認 %d 則" % (fname, len(blocks), len(unacked)))
        for b in blocks:
            print("  [%s] 第 %d 行 %s  %s"
                  % ("ack " + b.ack_date if b.acked else "未確認", b.start_line,
                     b.marker or "(無 marker)", b.heading))
    return 0


def cmd_ack(repo, fname, marker, date):
    """對指定帳本檔裡「marker 命中的那一則」加上 `<!-- ack:YYYY-MM-DD -->`。

    刻意設計成一次只確認一則、且必須明確指定 marker：
    「全部一次 ack」等於橡皮圖章，會把這個機制變成另一個恆真式。
    """
    if fname not in LEDGER_ALERTS:
        print("錯誤：%s 不是永久事件帳本（可 ack 的檔案：%s）" % (fname, "、".join(LEDGER_ALERTS)))
        return 2
    if not ACK_RE.match("<!-- ack:%s -->" % date):
        print("錯誤：日期格式必須是 YYYY-MM-DD，收到 %r" % date)
        return 2
    path = os.path.join(repo, fname)
    if not os.path.isfile(path):
        print("錯誤：%s 不存在" % path)
        return 2
    with open(path, encoding="utf-8") as f:
        text = f.read()
    blocks = split_blocks(text)
    hit = [b for b in blocks if b.marker and marker in b.marker]
    if len(hit) != 1:
        print("錯誤：marker %r 命中 %d 則（必須剛好 1 則）。用 --list 看可用的 marker。"
              % (marker, len(hit)))
        return 2
    b = hit[0]
    if b.acked:
        print("略過：該則已有 ack:%s" % b.ack_date)
        return 0
    lines = text.splitlines()
    # 加在該則的 marker 那一行行尾（檔頭說明寫的就是「在行尾加」）。
    for i in range(b.start_line - 1, len(lines)):
        if b.marker and b.marker in lines[i]:
            lines[i] = lines[i] + " <!-- ack:%s -->" % date
            break
    else:
        print("錯誤：找不到 marker 所在行，未修改任何內容")
        return 2
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("已對 %s 的 %s 加註 ack:%s" % (fname, marker, date))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="告警檔語意登記表 + 死人開關判定")
    p.add_argument("--repo", default=REPO, help="repo 根目錄（預設＝本檔往上一層）")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--deadman", action="store_true", help="輸出死人開關判定（供 scripts/push.sh 解析）")
    g.add_argument("--list", action="store_true", help="列出登記表與各帳本區塊的確認狀態")
    g.add_argument("--ack", nargs=3, metavar=("FILE", "MARKER", "DATE"),
                   help="對某帳本檔裡 marker 命中的那一則加註 ack，例如："
                        "--ack ALERT-DELIST.md 'detect_delistings:x402_bazaar:2026-09-07' 2026-09-09")
    a = p.parse_args(argv)
    if a.deadman:
        return cmd_deadman(a.repo)
    if a.list:
        return cmd_list(a.repo)
    return cmd_ack(a.repo, a.ack[0], a.ack[1], a.ack[2])


if __name__ == "__main__":
    sys.exit(main())
