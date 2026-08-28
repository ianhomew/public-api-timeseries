# -*- coding: utf-8 -*-
"""payment_protocol_repos：支付協議規格版本 GitHub Repo 中繼資料快照（B9，含併入的 B3）。

對應規格：/Users/monica/Documents/temp/終端機/vps-161.97.82.83/adapters-wip/specs/batch4.md 4-D（B9／B3）

已知的坑（2026-08-28 VPS 實測）：
    1. B3（x402 facilitator 清單）原目標 repo `x402-foundation/x402` 與 B9 第一個目標完全相同，
       規格書指示併入 B9，不重複規格、不重複請求，本 adapter 只保留 B9 的三個 repo。
    2. GitHub API 匿名請求速率限制為每小時 60 次，本 adapter 每次只打 3 次，完全無壓力，
       但若未來擴充追蹤更多 repo 需留意。
    3. `api.github.com/robots.txt` 本輪實測回 404（無限制）。
    4. 規格書自己評價本項「不推薦」（GitHub git log 本身就是最好的歷史紀錄），收錄只是為了
       湊齊「45 個全部要做」，其獨佔性價值很低，但成本極低（3 次請求、<20KB/日）沒有不做的理由。
"""
import json

KEY = "payment_protocol_repos"
DESC = "支付協議規格版本 GitHub Repo 中繼資料（x402／AP2／L402，含併入的 B3）"
SOURCE_HOME = (
    "https://api.github.com/repos/x402-foundation/x402 ; "
    "https://api.github.com/repos/google-agentic-commerce/AP2 ; "
    "https://api.github.com/repos/lightninglabs/L402"
)
ROBOTS_VERIFIED = "2026-08-28 親驗 https://api.github.com/robots.txt：HTTP 404（無限制）"
PARSER_VERSION = 1

REPOS = ("x402-foundation/x402", "google-agentic-commerce/AP2", "lightninglabs/L402")
MIN_SUCCESS = 2

_FIELDS = (
    "id", "full_name", "description", "stargazers_count", "forks_count",
    "open_issues_count", "pushed_at", "default_branch", "archived",
)


def _collect_one(fetch, repo):
    raw = fetch("https://api.github.com/repos/" + repo)
    data = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict) or "full_name" not in data:
        raise RuntimeError(f"payment_protocol_repos({repo})：回應非預期物件：{data!r}")
    if "stargazers_count" not in data or "pushed_at" not in data:
        raise RuntimeError(f"payment_protocol_repos({repo})：缺少 stargazers_count 或 pushed_at")
    rec = {k: data.get(k) for k in _FIELDS}
    rec["owner_login"] = (data.get("owner") or {}).get("login")
    return rec


def collect(fetch) -> dict:
    """回傳 dict：{"repos": [...], "errors": {repo: 錯誤訊息}}
    三者至少 2 個成功才算整體成功，否則 raise；個別失敗記錄在 errors，不讓下游誤判為空資料。
    """
    repos = []
    errors = {}
    seen = set()
    for repo in REPOS:
        try:
            rec = _collect_one(fetch, repo)
            full_name = rec["full_name"]
            if full_name in seen:
                raise RuntimeError(f"payment_protocol_repos：full_name 重複 {full_name!r}")
            seen.add(full_name)
            repos.append(rec)
        except Exception as exc:  # noqa: BLE001 - 個別 repo 失敗需被容忍並記錄
            errors[repo] = str(exc)

    if len(repos) < MIN_SUCCESS:
        raise RuntimeError(
            f"payment_protocol_repos：成功數 {len(repos)} 低於下限 {MIN_SUCCESS}"
            f"（共 {len(REPOS)} 個），errors={errors!r}"
        )

    return {"count": len(repos), "repos": repos, "errors": errors}
