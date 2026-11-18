#!/usr/bin/env python3
"""每日 15:10 收盘后：拉两只 ETF 收盘价 → 追加当日盈亏到 data/daily/<year>.json → commit+push。

幂等：以日期为主键，已存在的日期重跑会覆盖（份额/收盘价变更后重跑即校正）。
节假日：取行情接口最新交易日，若已记录则跳过，不空写。
补算：默认回看最近 5 个交易日（backfill=5），逐日与已存记录比对，缺哪天补哪天
      ——接口日K晚生成导致某天漏记时，第二天会自动补回。也可用 --backfill N 指定天数。
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
DATA = ROOT / "data" / "daily"          # 按年归档的每日记录
POS_FILE = ROOT / "data" / "portfolio" / "positions.json"
REPO = "zhanglaoliu18/annual-returns"
TZ = timezone(timedelta(hours=8))

# 东方财富日K（不复权，全精度3位小数）。腾讯qfq接口会把ETF价格舍入到2位小数，不可用。
# 收盘价：东方财富日K（不复权，3 位小数）。腾讯日K作为兜底（实测两边价格完全一致）
KLINE_URL = ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
             "?secid={secid}&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55"
             "&klt=101&fqt=0&end=20500101&lmt={n}")
KLINE_URL_BK = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{n},"


def now() -> datetime:
    env = os.environ.get("ANNUAL_NOW")  # 测试用：2026-11-19T15:10
    return datetime.fromisoformat(env) if env else datetime.now(TZ)


def _http_get(url: str, timeout: int = 20) -> str:
    """优先走 curl（部分行情接口会拒掉 urllib 的 TLS 握手），失败再退回 urllib。"""
    try:
        r = subprocess.run(["curl", "-s", "--max-time", str(timeout), "-A", "Mozilla/5.0", url],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    except Exception:
        pass
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def _kline_em(code: str, n: int) -> list[dict]:
    mkt, sym = code[:2], code[2:]
    secid = ("1." if mkt == "sh" else "0.") + sym
    data = json.loads(_http_get(KLINE_URL.format(secid=secid, n=n)))
    rows = data["data"]["klines"]  # "date,open,close,high,low"
    return [{"date": r.split(",")[0], "close": float(r.split(",")[2])} for r in rows]


def _kline_tencent(code: str, n: int) -> list[dict]:
    data = json.loads(_http_get(KLINE_URL_BK.format(code=code, n=n)))
    rows = data["data"][code]["day"]  # [date, open, close, high, low, volume]
    return [{"date": r[0], "close": float(r[2])} for r in rows]


def fetch_kline(code: str, n: int = 12) -> list[dict]:
    """腾讯不复权日K为主（与 etf_report 同源），东财兜底。两边价格均为 3 位小数、口径一致。

    注意必须用不复权（fq=空 / fqt=0）：ETF 分红后复权价会整体平移，
    历史 pnl 重算就会错，annual-returns 只看当日实际成交价。
    """
    try:
        rows = _kline_tencent(code, n)
        if rows:
            return rows
    except Exception as e:
        print(f"tencent kline failed ({code}): {e}, fallback to eastmoney")
    return _kline_em(code, n)


def load_positions() -> list[dict]:
    return json.load(open(POS_FILE, encoding="utf-8"))["positions"]


# 腾讯行情：现价 [3] / 昨收 [4] / 溢价率 [77]（仅交叉校验）/ IOPV [78]
# 与 etf_report 同源同口径：溢价率自算，不用 [77]。
QT_URL = "https://qt.gtimg.cn/q={codes}"


def fetch_quotes(codes: list[str]) -> dict:
    """返回 {code: {"price","prev","iopv","pct","pct_raw"}}；接口异常时返回 {}（不影响主流程）。

    溢价率 = (现价 / IOPV − 1) × 100 自行计算（etf_report 口径）。
    IOPV 是官方份额参考净值，QDII 已含汇率折算，不再乘 USDCNY。
    """
    req = urllib.request.Request(
        QT_URL.format(codes=",".join(codes)),
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        txt = r.read().decode("gbk", "ignore")
    out = {}
    for line in txt.strip().splitlines():
        if "=" not in line:
            continue
        code_part, raw = line.split("=", 1)
        code = code_part.replace("v_", "").strip()
        f = raw.strip().strip(";").strip('"').split("~")
        if len(f) < 35:              # 字段改版保护：宁可报错也不静默写错数
            raise ValueError(f"quote format changed ({code}): only {len(f)} fields")
        try:
            price = float(f[3]) or float(f[4])   # 集合竞价前/停牌可能返回 0 → 回退昨收
            prev = float(f[4])
            iopv = float(f[78]) if len(f) > 78 else 0.0
        except (ValueError, IndexError):
            continue
        if price <= 0:
            continue
        rec = {"price": price, "prev": prev}
        if iopv > 0:                              # IOPV 缺失或 ≤0 就不出溢价，不编数
            pct = (price / iopv - 1) * 100
            rec.update({"iopv": round(iopv, 4), "pct": round(pct, 2)})
            try:
                rec["pct_raw"] = round(float(f[77]), 2)   # 仅交叉校验
            except (ValueError, IndexError):
                pass
        out[code] = rec
    return out


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
    backfill = 5
    if "--backfill" in sys.argv:
        backfill = int(sys.argv[sys.argv.index("--backfill") + 1])

    positions = load_positions()
    t = now()
    klines = {p["code"]: fetch_kline(p["code"]) for p in positions}

    # 取各标的并集的最近 backfill 个交易日（收盘后）
    dates = sorted({k["date"] for kl in klines.values() for k in kl})
    todo = [d for d in dates if d <= t.strftime("%Y-%m-%d")][-backfill:]
    last_market_day = todo[-1] if todo else None

    # 最新交易日当天的溢价率/IOPV（历史日补算时无从获取，故只挂最新一天）
    quotes = {}
    try:
        quotes = fetch_quotes([p["code"] for p in positions])
        for code, q in quotes.items():
            raw = q.get("pct_raw")
            note = ""
            if raw is not None and abs(raw - q["pct"]) > 1:
                note = f"  ⚠️ 与接口字段[77]={raw:+.2f}% 偏差较大，以自算为准"
            print(f"quote {code}: price={q['price']} iopv={q.get('iopv', 0)} "
                  f"prem={q.get('pct', 0):+.2f}%{note}")
    except Exception as e:      # 接口抽风不阻断写盘
        print("quote fetch failed:", e)
        quotes = {}

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

    # ---- 写盘（dry-run 不落盘；内容与上次一致则不写不提交） ----
    written = []
    for c in changed:
        d = c["date"]
        path = DATA / f"{d[:4]}.json"
        doc = json.load(open(path, encoding="utf-8")) if path.exists() else {"year": int(d[:4]), "days": []}
        entry = {"date": d,
                 "closes": c["closes"],
                 "shares": {p["code"]: p["shares"] for p in positions},
                 "pnl": c["pnl"]}
        if quotes and d == last_market_day:
            # 场内溢价自算（现价/IOPV−1）：{代码: 溢价率%} / {代码: IOPV}
            prem = {code: q["pct"] for code, q in quotes.items() if code in c["closes"] and "pct" in q}
            iopv = {code: q["iopv"] for code, q in quotes.items() if code in c["closes"] and "iopv" in q}
            if prem:
                entry["premium"] = prem
                entry["iopv"] = iopv
        old = next((x for x in doc["days"] if x["date"] == d), None)
        if old != entry:
            days = [x for x in doc["days"] if x["date"] != d]
            days.append(entry)
            days.sort(key=lambda x: x["date"])
            doc["days"] = days
            doc["updated_at"] = t.strftime("%Y-%m-%d %H:%M:%S")
            path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            written.append(d)

    if not written:
        print(json.dumps({"applied": False, "reason": "no change since last run"}, ensure_ascii=False))
        return 0

    ensure_push_url()
    git("add", "data/")
    last_market = changed[-1]["date"]
    last_pnl = changed[-1]["pnl"]
    if written[-1] == last_market:
        extra = f"（含补录 {len(written) - 1} 天）" if len(written) > 1 else ""
        msg = f"data: {last_market} 大账户日盈亏 {last_pnl:+,.2f}{extra}"
    else:
        # 最新交易日已存在且无变化，本次只补了历史缺口
        msg = f"data: 补录 {len(written)} 天 {written[0]} ~ {written[-1]}"
    git("commit", "-m", msg)
    git("push", "origin", "HEAD")
    purge_jsdelivr([f"data/daily/{d[:4]}.json" for d in {c["date"] for c in changed}])
    print(json.dumps({"applied": True, "changed": changed, "pushed": True}, ensure_ascii=False))
    return 0


def purge_jsdelivr(paths: list[str]) -> None:
    """推送后刷新 jsDelivr 对这些文件的 CDN 缓存（无需鉴权），保证国内节点当天拿到新数据。"""
    for p in paths:
        url = f"https://purge.jsdelivr.net/gh/{REPO}@main/{p}"
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                st = json.load(r).get("status")
            print(f"jsDelivr purge {p}: {st}")
        except Exception as e:  # 刷新失败不影响主流程，最坏情况国内节点晚几小时更新
            print(f"jsDelivr purge {p}: failed ({e})")


if __name__ == "__main__":
    sys.exit(main())
