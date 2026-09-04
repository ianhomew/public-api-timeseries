#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/hf_sync.py — 把軌一 4 個大型來源的歷史快照同步備份到 Hugging Face 私有 dataset

## 背景
`.gitignore` 排除了 4 個軌一大型來源的快照檔（*.json.gz)：
x402_bazaar、cex_symbols、mcp_registry、vast_gpu（累積 3 個月後才考慮改發布到
Hugging Face Datasets）。這 4 個來源的原始快照因此只存在 VPS 單一副本，
VPS 毀損就永久遺失。本程式把這 4 個來源目錄的**全部檔案**（.json.gz 快照、
.stats.json、事件日誌等）以及 track-crypto/data/_manifest/ 同步到一個
Hugging Face **私有** dataset repo，當作第三副本（異地備份），不涉及對外公開。

## 設計原則
1. **冪等、增量**：只上傳「遠端沒有、或內容 sha256 與已知遠端紀錄不同」的檔案。
   遠端紀錄存放在 repo 內的 `_sync_state/sha256_manifest.json`（本程式自己維護），
   每次同步後跟著資料一起原子性更新（同一個 commit）。
2. **唯讀本地**：只讀取來源檔案計算 sha256／上傳，絕不修改或刪除本地任何檔案。
   `--verify` 模式下載回來比對用的檔案，一律寫到獨立的 verify 目錄
   （預設系統暫存目錄下的子目錄），並會拒絕該目錄落在來源 repo 目錄之內。
3. **只增不減**：即使本地檔案未來消失（例如來源目錄異常），本程式也**不會**
   反向刪除遠端已備份的檔案 —— 備份工具本身不該成為資料遺失的第二個原因。
4. **分批、串流**：上傳依檔案數與位元組數雙門檻分批（預設每批 ≤10 檔或 ≤40MB，
   以先到者為準），且用檔案路徑而非把整包位元組讀進 Python 物件，避免記憶體暴衝；
   批次之間有小延遲，並對可能的暫時性錯誤（含 429）做有限次重試退避。
5. **祕密零外洩**：HF_TOKEN 只從 `.env` 讀進「行程序內的環境變數／區域變數」，
   全程只以 huggingface_hub 的 Python API 物件參數傳遞，絕不寫進命令列參數、
   絕不整段印出；任何要印出的錯誤訊息都會先做 token 字面值的遮蔽處理。
   任何要印出的祕密資訊，一律只印「長度」「前 3 碼」「sha256 前 16 碼」。
6. **失敗要響**：任何一步失敗都印清楚的錯誤訊息到 stderr 並以非 0 結束碼結束，
   方便日後掛進 push.sh 用 `$?` 判斷（本程式目前**尚未**掛進 push.sh）。

## 用法
    python3 scripts/hf_sync.py                    # 一般同步（增量、冪等）
    python3 scripts/hf_sync.py --dry-run           # 只列出差異，不建 repo、不上傳
    python3 scripts/hf_sync.py --whoami            # 只驗證 token（whoami），不觸碰資料
    python3 scripts/hf_sync.py --verify            # 同步後，把遠端全部在範圍內的檔案
                                                    # 下載到 verify 目錄，逐檔比對 sha256
    python3 scripts/hf_sync.py --verify --verify-only
                                                    # 只做下載比對，不先執行同步

## 環境變數（皆非必要，供覆寫預設值／測試用）
    HF_SYNC_ENV_FILE          .env 檔路徑，預設 ~/snap/.env
    HF_SYNC_REPO_ID           目標 dataset repo id，預設 "<whoami 使用者名稱>/public-api-timeseries-archive"
    HF_SYNC_REPO_ROOT         專案根目錄，預設用 __file__ 往上兩層推算（scripts/ 的上一層）
    HF_SYNC_VERIFY_DIR        --verify 下載目的地，預設 "<系統暫存目錄>/hf_sync_verify"
    HF_SYNC_BATCH_MAX_FILES   每批最多檔案數，預設 10
    HF_SYNC_BATCH_MAX_BYTES   每批最多位元組數，預設 41943040（40MiB）
    HF_SYNC_SLEEP_BETWEEN     批次間延遲秒數，預設 1.5

## 結束碼
    0   成功（含「零上傳」的冪等情形、--whoami 成功、--dry-run 執行完畢）
    1   環境／設定錯誤（找不到 .env、HF_TOKEN 空、找不到來源目錄...）
    2   Hugging Face API 呼叫失敗（whoami、建 repo、上傳、列目錄、下載皆算）
    3   --verify 完整性驗證失敗（有檔案 sha256 不吻合，或數量對不上）
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

# 在 import huggingface_hub 之前設定：關閉進度條，避免掛進 push.sh 的 log 檔
# 被 tqdm 的 \r 逐字元進度輸出洗版（不影響上傳行為本身，只影響終端機輸出）。
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

# ---------------------------------------------------------------------------
# 常數
# ---------------------------------------------------------------------------

SOURCE_SUBDIRS = ["x402_bazaar", "cex_symbols", "mcp_registry", "vast_gpu"]
MANIFEST_SUBDIR = "_manifest"
DATA_REL = "track-crypto/data"
STATE_PATH_IN_REPO = "_sync_state/sha256_manifest.json"
README_PATH_IN_REPO = "README.md"
DEFAULT_REPO_SUFFIX = "public-api-timeseries-archive"

DEFAULT_BATCH_MAX_FILES = 10
DEFAULT_BATCH_MAX_BYTES = 40 * 1024 * 1024  # 40 MiB
DEFAULT_SLEEP_BETWEEN = 1.5
RETRY_ATTEMPTS = 4
RETRY_BASE_DELAY = 2.0

README_TEMPLATE = """---
license: unknown
---

# public-api-timeseries-archive（私有異地備份）

**這是私有 dataset，不是公開發布。**

本 repo 是 `public-api-timeseries` 專案（VPS 每日快照）的**第三副本異地備份**，
只包含 `.gitignore` 排除、未進 GitHub 的 4 個軌一大型來源歷史快照
（`x402_bazaar`、`cex_symbols`、`mcp_registry`、`vast_gpu`）以及
`track-crypto/data/_manifest/`（每日執行證明）。

- 由 `scripts/hf_sync.py` 產生與維護（增量、冪等，只上傳遠端沒有或雜湊不同的檔案）。
- `_sync_state/sha256_manifest.json`：本程式自己維護的同步狀態紀錄，
  記錄每個檔案上次同步時的 sha256，供下次執行比對用，非資料本體。
- 若要改為公開發布，需要額外的資料授權／隱私複核（見本機記錄 repo 的
  `docs/hf-backup-report.md`「若要改為公開發布需要做什麼」一節），
  **本 repo 目前刻意維持 private，未經使用者同意不得改動可見性。**

生成時間（UTC）：{generated_at}
"""

# ---------------------------------------------------------------------------
# 祕密處理
# ---------------------------------------------------------------------------


def load_env_file(path: str) -> dict:
    """極簡 .env 解析：KEY=VALUE，忽略註解／空白行，不經過 shell 解譯。"""
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            out[k] = v
    return out


def mask_secret(secret: str) -> str:
    """祕密處理鐵律：只回傳長度、前 3 碼、sha256 前 16 碼。"""
    if not secret:
        return "(empty)"
    sha16 = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]
    return f"len={len(secret)} prefix={secret[:3]}*** sha256_16={sha16}"


def redact(text: str, *secrets: str) -> str:
    """把任何字面出現的祕密值從文字中換成 <REDACTED>，用於印錯誤訊息前的最後防線。"""
    out = text
    for s in secrets:
        if s and len(s) >= 6:
            out = out.replace(s, "<REDACTED>")
    return out


def get_token(env_file: str) -> str:
    env = load_env_file(env_file)
    token = env.get("HF_TOKEN") or os.environ.get("HF_TOKEN") or ""
    if not token:
        raise ConfigError(f"HF_TOKEN 為空或不存在（讀取自 {env_file} 與行程序環境變數）")
    return token


# ---------------------------------------------------------------------------
# 例外分級（對應結束碼）
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """結束碼 1：環境／設定錯誤"""


class HFApiError(Exception):
    """結束碼 2：Hugging Face API 呼叫失敗"""


class VerifyError(Exception):
    """結束碼 3：完整性驗證失敗"""


# ---------------------------------------------------------------------------
# 本地檔案列舉與雜湊
# ---------------------------------------------------------------------------


@dataclass
class LocalFile:
    relpath: str  # 相對 repo_root，同時也是 path_in_repo
    abspath: Path
    size: int
    sha256: str


def sha256_of_file(path: Path, bufsize: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(bufsize)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def iter_scope_dirs(repo_root: Path):
    data_root = repo_root / DATA_REL
    for name in SOURCE_SUBDIRS + [MANIFEST_SUBDIR]:
        yield name, data_root / name


def build_local_index(repo_root: Path, log=print) -> "dict[str, LocalFile]":
    """列舉 4 個來源目錄＋_manifest 目錄底下的『所有檔案』（不遞迴子目錄，
    這些目錄本身就是平的），計算 sha256。回傳 relpath -> LocalFile。"""
    index: "dict[str, LocalFile]" = {}
    for name, d in iter_scope_dirs(repo_root):
        if not d.is_dir():
            log(f"[hf_sync] WARN 來源目錄不存在，略過: {d}")
            continue
        for entry in sorted(d.iterdir()):
            if not entry.is_file():
                continue
            relpath = str(entry.relative_to(repo_root)).replace(os.sep, "/")
            size = entry.stat().st_size
            sha = sha256_of_file(entry)
            index[relpath] = LocalFile(relpath=relpath, abspath=entry, size=size, sha256=sha)
    return index


# ---------------------------------------------------------------------------
# 重試包裝（處理暫時性錯誤／429）
# ---------------------------------------------------------------------------


def call_with_retry(fn, *, what: str, attempts: int = RETRY_ATTEMPTS,
                     base_delay: float = RETRY_BASE_DELAY, log=print, no_retry: tuple = ()):
    """呼叫 fn()，失敗時重試（指數退避）。no_retry 列出的例外型別視為『預期中的狀態』
    （例如遠端本來就還沒有這個 repo/檔案），立刻原樣拋出，不浪費重試次數。"""
    last_exc = None
    for i in range(1, attempts + 1):
        try:
            return fn()
        except no_retry:
            raise
        except Exception as e:  # noqa: BLE001 - 這裡刻意廣捕，統一轉型與重試
            last_exc = e
            if i == attempts:
                break
            delay = base_delay * (2 ** (i - 1))
            log(f"[hf_sync] WARN {what} 第 {i} 次失敗（{type(e).__name__}），{delay:.1f}s 後重試")
            time.sleep(delay)
    raise last_exc


# ---------------------------------------------------------------------------
# 遠端狀態
# ---------------------------------------------------------------------------


def fetch_remote_state(api, repo_id: str, token: str, log=print) -> dict:
    """下載並解析 _sync_state/sha256_manifest.json；repo 或檔案不存在都回傳 {}。"""
    from huggingface_hub.utils import EntryNotFoundError, RepositoryNotFoundError, RevisionNotFoundError

    try:
        local_path = call_with_retry(
            lambda: api.hf_hub_download(
                repo_id=repo_id, filename=STATE_PATH_IN_REPO, repo_type="dataset", token=token,
            ),
            what="下載遠端同步狀態檔",
            log=log,
            no_retry=(EntryNotFoundError, RepositoryNotFoundError, RevisionNotFoundError),
        )
    except (EntryNotFoundError, RepositoryNotFoundError, RevisionNotFoundError):
        return {}
    except Exception as e:
        # 404 有時包成別的例外型別，用訊息內容再判斷一次，避免把「本來就沒有」誤判成錯誤
        msg = str(e)
        if "404" in msg or "not found" in msg.lower() or "No such file" in msg:
            return {}
        raise HFApiError(f"下載遠端同步狀態檔失敗: {type(e).__name__}: {redact(msg, token)}") from e
    try:
        with open(local_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"[hf_sync] WARN 遠端同步狀態檔解析失敗，視為空狀態: {type(e).__name__}")
        return {}


def list_remote_paths(api, repo_id: str, token: str, log=print) -> set:
    from huggingface_hub.utils import RepositoryNotFoundError

    try:
        entries = call_with_retry(
            lambda: list(api.list_repo_tree(repo_id, recursive=True, repo_type="dataset", token=token)),
            what="列出遠端檔案樹",
            log=log,
            no_retry=(RepositoryNotFoundError,),
        )
    except RepositoryNotFoundError:
        return set()
    except Exception as e:
        raise HFApiError(f"列出遠端檔案樹失敗: {type(e).__name__}: {redact(str(e), token)}") from e
    paths = set()
    for e in entries:
        # RepoFile 有 .path；RepoFolder 沒有內容意義，略過
        p = getattr(e, "path", None)
        if p and getattr(e, "size", None) is not None:
            paths.add(p)
    return paths


# ---------------------------------------------------------------------------
# 同步規劃與批次
# ---------------------------------------------------------------------------


@dataclass
class SyncPlan:
    to_upload: "list[str]"
    unchanged: "list[str]"


def plan_sync(local_index: "dict[str, LocalFile]", remote_state: dict, remote_paths: set) -> SyncPlan:
    to_upload, unchanged = [], []
    for relpath, lf in sorted(local_index.items()):
        if relpath not in remote_paths:
            to_upload.append(relpath)
            continue
        known_sha = (remote_state.get(relpath) or {}).get("sha256")
        if known_sha != lf.sha256:
            to_upload.append(relpath)
        else:
            unchanged.append(relpath)
    return SyncPlan(to_upload=to_upload, unchanged=unchanged)


def make_batches(relpaths: "list[str]", local_index: "dict[str, LocalFile]",
                  max_files: int, max_bytes: int):
    batch, batch_bytes = [], 0
    for relpath in relpaths:
        size = local_index[relpath].size
        if batch and (len(batch) >= max_files or batch_bytes + size > max_bytes):
            yield batch
            batch, batch_bytes = [], 0
        batch.append(relpath)
        batch_bytes += size
    if batch:
        yield batch


# ---------------------------------------------------------------------------
# 上傳
# ---------------------------------------------------------------------------


def ensure_repo(api, repo_id: str, token: str, log=print):
    from huggingface_hub import RepoUrl

    try:
        url = call_with_retry(
            lambda: api.create_repo(repo_id, repo_type="dataset", private=True, exist_ok=True, token=token),
            what="建立/確認 dataset repo",
            log=log,
        )
    except Exception as e:
        raise HFApiError(f"建立/確認 dataset repo 失敗: {type(e).__name__}: {redact(str(e), token)}") from e
    info = call_with_retry(
        lambda: api.repo_info(repo_id, repo_type="dataset", token=token),
        what="讀取 repo 資訊",
        log=log,
    )
    if info.private is not True:
        raise HFApiError(f"repo {repo_id} 目前 private={info.private!r}，未通過 private=True 檢查，中止")
    log(f"[hf_sync] repo 就緒: {repo_id} (private={info.private})")
    return url


def upload_batches(api, repo_id: str, token: str, plan: SyncPlan,
                    local_index: "dict[str, LocalFile]", remote_state: dict,
                    *, max_files: int, max_bytes: int, sleep_between: float,
                    dry_run: bool, log=print) -> int:
    from huggingface_hub import CommitOperationAdd

    if not plan.to_upload:
        log("[hf_sync] 無檔案需要上傳（已與遠端同步）")
        return 0

    batches = list(make_batches(plan.to_upload, local_index, max_files, max_bytes))
    log(f"[hf_sync] 待上傳 {len(plan.to_upload)} 檔，分成 {len(batches)} 批"
        f"（每批 <= {max_files} 檔 或 <= {max_bytes / 1e6:.1f}MB）")

    if dry_run:
        for i, batch in enumerate(batches, 1):
            total = sum(local_index[p].size for p in batch)
            log(f"[hf_sync] [dry-run] 批次 {i}/{len(batches)}: {len(batch)} 檔, {total/1e6:.2f}MB")
            for p in batch:
                log(f"[hf_sync] [dry-run]   + {p} ({local_index[p].size} bytes)")
        return len(plan.to_upload)

    state = dict(remote_state)  # 逐批累加更新，最後一批完成時已是完整新狀態
    uploaded = 0
    for i, batch in enumerate(batches, 1):
        total = sum(local_index[p].size for p in batch)
        log(f"[hf_sync] 上傳批次 {i}/{len(batches)}: {len(batch)} 檔, {total/1e6:.2f}MB ...")
        ops = []
        for relpath in batch:
            lf = local_index[relpath]
            log(f"[hf_sync]   + {relpath} ({lf.size} bytes)")
            ops.append(CommitOperationAdd(path_in_repo=relpath, path_or_fileobj=str(lf.abspath)))
            state[relpath] = {
                "sha256": lf.sha256,
                "size": lf.size,
                "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        state_bytes = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        ops.append(CommitOperationAdd(path_in_repo=STATE_PATH_IN_REPO, path_or_fileobj=state_bytes))
        try:
            call_with_retry(
                lambda ops=ops, i=i: api.create_commit(
                    repo_id=repo_id, repo_type="dataset", token=token, operations=ops,
                    commit_message=f"hf_sync: batch {i}/{len(batches)} ({len(batch)} files)",
                ),
                what=f"提交批次 {i}/{len(batches)}",
                log=log,
            )
        except Exception as e:
            raise HFApiError(
                f"上傳批次 {i}/{len(batches)} 失敗（此批之前的批次已成功上傳且已記錄狀態）: "
                f"{type(e).__name__}: {redact(str(e), token)}"
            ) from e
        uploaded += len(batch)
        log(f"[hf_sync] 批次 {i}/{len(batches)} 完成，累計已上傳 {uploaded}/{len(plan.to_upload)} 檔")
        if i < len(batches) and sleep_between > 0:
            time.sleep(sleep_between)
    return uploaded


def ensure_readme(api, repo_id: str, token: str, remote_paths: set, dry_run: bool, log=print):
    if README_PATH_IN_REPO in remote_paths or dry_run:
        return
    from huggingface_hub import CommitOperationAdd

    content = README_TEMPLATE.format(generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    try:
        call_with_retry(
            lambda: api.create_commit(
                repo_id=repo_id, repo_type="dataset", token=token,
                operations=[CommitOperationAdd(path_in_repo=README_PATH_IN_REPO,
                                                path_or_fileobj=content.encode("utf-8"))],
                commit_message="hf_sync: add README (private archive notice)",
            ),
            what="寫入 README",
            log=log,
        )
        log("[hf_sync] 已寫入 README.md（說明本 repo 為私有備份）")
    except Exception as e:
        # README 純粹是輔助說明，失敗不影響資料備份的成敗，只警告
        log(f"[hf_sync] WARN 寫入 README 失敗（不影響資料同步）: {type(e).__name__}: {redact(str(e), token)}")


# ---------------------------------------------------------------------------
# 完整性驗證（下載回本地逐檔比對 sha256）
# ---------------------------------------------------------------------------


def verify_download(api, repo_id: str, token: str, local_index: "dict[str, LocalFile]",
                     verify_dir: Path, repo_root: Path, log=print) -> bool:
    if repo_root in verify_dir.parents or verify_dir == repo_root:
        raise ConfigError(f"verify_dir 不得落在來源 repo 目錄之內: {verify_dir}")
    verify_dir.mkdir(parents=True, exist_ok=True)

    total = len(local_index)
    log(f"[hf_sync] 開始完整性驗證：下載 {total} 檔到 {verify_dir} 逐檔比對 sha256（全數，不抽樣）")
    mismatches = []
    missing = []
    ok = 0
    for n, (relpath, lf) in enumerate(sorted(local_index.items()), 1):
        try:
            downloaded_path = call_with_retry(
                lambda relpath=relpath: api.hf_hub_download(
                    repo_id=repo_id, filename=relpath, repo_type="dataset", token=token,
                    local_dir=str(verify_dir), force_download=True,
                ),
                what=f"下載 {relpath}",
                log=log,
            )
        except Exception as e:
            missing.append(relpath)
            log(f"[hf_sync] [verify] {n}/{total} MISSING {relpath}: {type(e).__name__}")
            continue
        remote_sha = sha256_of_file(Path(downloaded_path))
        if remote_sha == lf.sha256:
            ok += 1
        else:
            mismatches.append(relpath)
            log(f"[hf_sync] [verify] {n}/{total} MISMATCH {relpath} local={lf.sha256[:16]} remote={remote_sha[:16]}")
        if n % 10 == 0 or n == total:
            log(f"[hf_sync] [verify] 進度 {n}/{total}（ok={ok} mismatch={len(mismatches)} missing={len(missing)}）")

    log(f"[hf_sync] [verify] 完成：ok={ok} mismatch={len(mismatches)} missing={len(missing)} / total={total}")
    if mismatches or missing or ok != total:
        log(f"[hf_sync] [verify] FAILED，不相符清單: mismatches={mismatches} missing={missing}")
        return False
    return True


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def resolve_repo_root() -> Path:
    override = os.environ.get("HF_SYNC_REPO_ROOT")
    if override:
        return Path(override).resolve()
    # scripts/hf_sync.py -> repo root 是上兩層（與 milestone.py 相同的推算方式）
    return Path(__file__).resolve().parent.parent


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="只列出將上傳的檔案，不建立 repo、不上傳")
    p.add_argument("--verify", action="store_true", help="同步後，下載遠端全部範圍內檔案逐檔比對 sha256")
    p.add_argument("--verify-only", action="store_true", help="只做 --verify 的下載比對，跳過同步步驟")
    p.add_argument("--verify-dir", default=None, help="verify 下載目的地，預設系統暫存目錄下的子目錄")
    p.add_argument("--whoami", action="store_true", help="只驗證 token（whoami），不觸碰資料，驗證完即結束")
    return p


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    log = print

    env_file = os.environ.get("HF_SYNC_ENV_FILE", os.path.expanduser("~/snap/.env"))
    try:
        token = get_token(env_file)
    except ConfigError as e:
        print(f"[hf_sync] ERROR {e}", file=sys.stderr)
        return 1
    log(f"[hf_sync] HF_TOKEN 已讀取（{mask_secret(token)}）")

    from huggingface_hub import HfApi
    api = HfApi()

    try:
        whoami = call_with_retry(lambda: api.whoami(token=token), what="whoami", log=log)
    except Exception as e:
        print(f"[hf_sync] ERROR whoami 失敗: {type(e).__name__}: {redact(str(e), token)}", file=sys.stderr)
        return 2
    owner = whoami.get("name")
    log(f"[hf_sync] whoami OK: name={owner} type={whoami.get('type')}")

    if args.whoami:
        return 0

    repo_id = os.environ.get("HF_SYNC_REPO_ID") or f"{owner}/{DEFAULT_REPO_SUFFIX}"
    repo_root = resolve_repo_root()
    log(f"[hf_sync] repo_id={repo_id} repo_root={repo_root}")

    try:
        local_index = build_local_index(repo_root, log=log)
    except Exception as e:
        print(f"[hf_sync] ERROR 本地檔案列舉失敗: {type(e).__name__}: {redact(str(e), token)}", file=sys.stderr)
        return 1
    if not local_index:
        print("[hf_sync] ERROR 範圍內找不到任何本地檔案，中止（請確認 repo_root 是否正確）", file=sys.stderr)
        return 1
    total_bytes = sum(lf.size for lf in local_index.values())
    log(f"[hf_sync] 本地範圍內檔案數={len(local_index)} 總位元組數={total_bytes}（{total_bytes/1e6:.2f}MB）")

    if not args.verify_only:
        try:
            if not args.dry_run:
                ensure_repo(api, repo_id, token, log=log)
            remote_state = fetch_remote_state(api, repo_id, token, log=log)
            remote_paths = list_remote_paths(api, repo_id, token, log=log)
            plan = plan_sync(local_index, remote_state, remote_paths)
            log(f"[hf_sync] 同步規劃: 待上傳={len(plan.to_upload)} 已同步略過={len(plan.unchanged)}")

            batch_max_files = int(os.environ.get("HF_SYNC_BATCH_MAX_FILES", DEFAULT_BATCH_MAX_FILES))
            batch_max_bytes = int(os.environ.get("HF_SYNC_BATCH_MAX_BYTES", DEFAULT_BATCH_MAX_BYTES))
            sleep_between = float(os.environ.get("HF_SYNC_SLEEP_BETWEEN", DEFAULT_SLEEP_BETWEEN))

            uploaded = upload_batches(
                api, repo_id, token, plan, local_index, remote_state,
                max_files=batch_max_files, max_bytes=batch_max_bytes,
                sleep_between=sleep_between, dry_run=args.dry_run, log=log,
            )
            if not args.dry_run:
                ensure_readme(api, repo_id, token, remote_paths, dry_run=args.dry_run, log=log)
            log(f"[hf_sync] SUMMARY mode={'dry-run' if args.dry_run else 'sync'} "
                f"local_files={len(local_index)} uploaded={uploaded} skipped={len(plan.unchanged)}")
        except (HFApiError, ConfigError) as e:
            print(f"[hf_sync] ERROR {e}", file=sys.stderr)
            return 2
        except Exception as e:
            print(f"[hf_sync] ERROR 未預期例外: {type(e).__name__}: {redact(str(e), token)}", file=sys.stderr)
            # traceback 也要過一次 redact，防止巢狀例外字面值意外把 token 印出來（縱深防禦）
            print(redact(traceback.format_exc(), token), file=sys.stderr)
            return 2

    if args.verify or args.verify_only:
        verify_dir = Path(args.verify_dir or os.environ.get("HF_SYNC_VERIFY_DIR")
                           or (Path(tempfile.gettempdir()) / "hf_sync_verify")).resolve()
        try:
            ok = verify_download(api, repo_id, token, local_index, verify_dir, repo_root, log=log)
        except ConfigError as e:
            print(f"[hf_sync] ERROR {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"[hf_sync] ERROR verify 未預期例外: {type(e).__name__}: {redact(str(e), token)}", file=sys.stderr)
            print(redact(traceback.format_exc(), token), file=sys.stderr)
            return 2
        if not ok:
            print("[hf_sync] ERROR 完整性驗證失敗，見上方 mismatch/missing 清單", file=sys.stderr)
            return 3
        log("[hf_sync] 完整性驗證通過：遠端與本地全數 sha256 相同")

    return 0


if __name__ == "__main__":
    sys.exit(main())
