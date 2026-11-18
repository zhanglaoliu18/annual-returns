#!/usr/bin/env python3
"""每日 15:10 收盘后：拉两只 ETF 收盘价 → 追加当日盈亏到 data/<year>.json → commit+push。

幂等：以日期为主键，已存在的日期重跑会覆盖（份额/收盘价变更后重跑即校正）。
节假日：取行情接口最新交易日，若已记录则跳过，不空写。
补算：某天没跑，下次运行会自然写入最新交易日；连续多天没跑可手动多次调用
      （脚本只写最新一天）；如需补多天用 --backfill N。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
POS_FILE = ROOT / "positions.json"
TZ = timezone(timedelta(hours=8))

KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{n},qfq"


def now() -> datetime:
    env = os.environ.get("ANNUAL_NOW")  # 测试用：2026-11-19T15:10
    return datetime.fromisoformat(env) if env else datetime.now(TZ)


def fetch_kline(code: str, n: int = 12) -> list[dict]:
    req = urllib.request.Request(KLINE_URL.format(code=code, n=n),
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    node = data["data"][code]
    rows = node.get("qfqday") or node.get("day") or []
    return [{"date": r[0], "close": float(r[2])} for r in rows]


def load_positions() -> list[dict]:
    return json.load(open(POS_FILE, encoding="utf-8"))["positions"]


def git(*args: str, check: bool = True) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="annual-bot", GIT_AUTHOR_EMAIL="bot@annual.local",
               GIT_COMMITTER_NAME="annual-bot", GIT_COMMITTER_EMAIL="bot@annual.local")
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def ensure_push_url() -> None:
    """优先用环境变量 GITHUB_TOKEN 组装 push URL（Cloady 上用）；本地直接用 origin。"""
    token = os.environ.get("GITHUB_TOKEN")
    url = git("remote", "get-url", "origin")
    if token and "x-access-token" not in url:
        m = url.replace("https://", f"https://x-access-token:{token}@")
        git("remote", "set-url", "origin", m)


def main() -> int:
    dry = "--dry-run" in sys.argv
    backfill = 1
    if "--backfill" in sys.argv:
        backfill = int(sys.argv[sys.argv.index("--backfill") + 1])

    positions = load_positions()
    t = now()
    klines = {p["code"]: fetch_kline(p["code"]) for p in positions}

    # 取各标的并集的最近 backfill 个交易日（收盘后）
    dates = sorted({k["date"] for kl in klines.values() for k in kl})
    todo = [d for d in dates if d <= t.strftime("%Y-%m-%d")][-backfill:]

    changed = []
    for d in todo:
        closes = {}
        for code, kl in klines.items():
            hit = [k for k in kl if k["date"] == d]
            if hit:
                closes[code] = hit[0]["close"]
        prev_closes = {}
        for code, kl in klines.items():
            before = [k["date"] for k in kl if k["date"] < d]
            if before:
                prev_closes[code] = next(k["close"] for k in kl if k["date"] == before[-1])

        pnl = sum(p["shares"] * (closes[p["code"]] - prev_closes[p["code"]])
                  for p in positions if p["code"] in closes and p["code"] in prev_closes)
        changed.append({"date": d, "pnl": round(pnl, 2), "closes": closes})
        print(f"[{d}] pnl={pnl:+,.2f} closes={closes}")

    if not changed:
        print(json.dumps({"applied": False, "reason": "no new trading day"}, ensure_ascii=False))
        return 0

    if dry:
        print(json.dumps({"applied": True, "dry_run": True, "changed": changed}, ensure_ascii=False))
        return 0

    # ---- 写盘（dry-run 不落盘） ----
    for c in changed:
        d = c["date"]
        path = DATA / f"{d[:4]}.json"
        doc = json.load(open(path, encoding="utf-8")) if path.exists() else {"year": int(d[:4]), "days": []}
        days = [x for x in doc["days"] if x["date"] != d]
        days.append({"date": d,
                     "closes": c["closes"],
                     "shares": {p["code"]: p["shares"] for p in positions},
                     "pnl": c["pnl"]})
        days.sort(key=lambda x: x["date"])
        doc["days"] = days
        doc["updated_at"] = t.strftime("%Y-%m-%d %H:%M:%S")
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    ensure_push_url()
    git("add", "data/")
    last = changed[-1]["date"]
    total = sum(c["pnl"] for c in changed)
    git("commit", "-m", f"data: {last} 大账户日盈亏 {total:+,.2f}")
    git("push", "origin", "HEAD")
    print(json.dumps({"applied": True, "changed": changed, "pushed": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
