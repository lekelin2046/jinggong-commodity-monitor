#!/usr/bin/env python3
"""LME 铝（官方 Cash Ask）——次日 9 点按「官方数据日」回填脚本

背景（2026-09-16 主人定口径）：
  LME 官方价在伦敦 12:30 定价、北京约 19:30-20:30 才发布，故北京 15:00 主流程
  能拿到的最新值必然是【前一伦敦交易日】的官方价。此前把该值写进「抓取日」行
  （日延一日口径），表上日期与官方数据日错位。现改为：

    · 15:00 主流程不再抓 LME，当日单元格留空（daily_update_all.py 已摘除该源）；
    · 次日 09:00 由本脚本查询官方接口，取 DateOfData（官方数据日）+ Aluminium
      Cash Ask，写入【官方数据日那一行】。
      即：D 日 9 点把 D-1 日的官方价补进 D-1 日行；周一 9 点补周五行。

规则：
  · 幂等 —— 目标单元格已有值则跳过，不重复写、不重复留痕；
  · 有值但 ≠ 官方值 → **不覆盖**（保护人工修正），仅告警退出；
  · 守铁律 —— 抓不到（CF 拦截 / 官方未公布 '-'）不写、不估、不沿用前值，留空；
  · 不按中国交易日历跳过：中国假期当日仍要跑，否则假期前最后一个工作日
    的 LME 行会永远空着（如周一为假期，周一 9 点正需补上周五的值）。
    目标行由接口返回的官方数据日决定，无对应行则自然跳过。

用法:
    python3 backfill_lme_official.py [--dry-run] [--no-push]
    环境要求：项目 venv + 先 unset NODE_OPTIONS（Playwright headed 模式）
"""

import os
import sys
import time
import json
import shutil
import datetime
import subprocess
import socket
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

os.environ.pop("NODE_OPTIONS", None)   # Playwright driver 兼容性，必须在 import 前清掉

import openpyxl  # noqa: E402

from changelog import (  # noqa: E402
    record_changes, current_commit_sha, SOURCE_AUTO_CRON, norm_value,
)

EXCEL_PATH = SCRIPT_DIR / "2026年有色金属市场价格.xlsx"
SHEET_NAME = "日均价（2026年市场）"
LME_COL = 27          # LME 铝 USD/t
CODE = "LME_AL"

DRY_RUN = "--dry-run" in sys.argv
NO_PUSH = "--no-push" in sys.argv


def log(msg: str):
    print(msg, flush=True)


# ===== 抓取 =====
def fetch_official():
    """抓 LME 官网官方价，返回 (price, date_of_data) ；失败抛 FetchError。"""
    from jinggong_monitor.fetcher_lme import LmeFetcher

    def _run():
        return LmeFetcher().fetch()

    # Playwright Sync API 不能在运行中的事件循环里调用 → 主动探测并派发线程
    try:
        import asyncio
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False

    if in_loop:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            res = ex.submit(_run).result()
    else:
        res = _run()

    price = res.get("LME_AL")
    dod = str(res.get("_date_of_data") or "")[:10]
    if price is None or not dod:
        raise RuntimeError(f"接口未返回可用数据: {res!r}")
    return float(price), dod


# ===== Git（直连优先，代理兜底，容忍龟速）=====
def _proxy_alive(port: int = 7890) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _git(args, timeout=120, retries=3):
    last = None
    for i in range(retries):
        try:
            r = subprocess.run(["git"] + args, cwd=str(SCRIPT_DIR),
                               capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0:
                return r
            last = r
            msg = (r.stdout + r.stderr).lower()
            if any(k in msg for k in ("timed out", "timeout", "connection",
                                      "resolve", "403", "502", "503")):
                time.sleep(3)
                continue
            return r
        except subprocess.TimeoutExpired:
            last = None
            time.sleep(3)
    return last


def push_robust(max_rounds: int = 8) -> bool:
    """推送。直连 + 可用代理轮换，允许龟速爬行（lowSpeedLimit=10）。

    2026-09-16 实测：github 直连时连时断（75s 连接超时 / <10B/s），把
    lowSpeedLimit 从 1000 降到 10 后循环重试可在第 4 次成功 —— 慢速重试
    比快速失败更有效，故此处保留低阈值 + 多轮重试。
    """
    paths = [["-c", "http.proxy=", "-c", "https.proxy="]]
    if _proxy_alive(7890):
        paths.append(["-c", "http.proxy=http://127.0.0.1:7890",
                      "-c", "https.proxy=http://127.0.0.1:7890"])
    base = ["-c", "http.lowSpeedLimit=10", "-c", "http.lowSpeedTime=45"]

    for i in range(1, max_rounds + 1):
        cfg = base + paths[(i - 1) % len(paths)]
        log(f"  push 第 {i}/{max_rounds} 次（{'代理' if len(cfg) > 4 else '直连'}）...")
        r = _git(cfg + ["push", "origin", "main"], timeout=180, retries=1)
        out = ((r.stdout + r.stderr).strip() if r else "timeout")
        if r is not None and r.returncode == 0:
            log(f"  ✅ push 成功: {out.splitlines()[-1][:120] if out else 'ok'}")
            return True
        log(f"  失败: {out.splitlines()[-1][:140]}")
        v = _git(["rev-list", "--left-right", "--count", "HEAD...origin/main"], timeout=30)
        if v is not None and v.returncode == 0 and v.stdout.split()[:2] == ["0", "0"]:
            log("  ✅ 本地/远端已一致（push 实为成功）")
            return True
        if i < max_rounds:
            time.sleep(30)
    return False


# ===== 主流程 =====
def main():
    today = datetime.date.today()
    log(f"{'='*54}")
    log(f"  LME 铝 · 官方价回填（按官方数据日）  {today}")
    log(f"{'='*54}")

    # 1) 抓取
    log("[1/4] 查询 LME 官网官方价（headed Playwright，Chrome 会短暂弹出）...")
    try:
        price, dod = fetch_official()
    except Exception as e:
        log(f"  ❌ 抓取失败：{e}")
        log("  守铁律：不写、不估、不沿用前值 → 目标单元格保持留空，等 17:00 兜底或人工处理。")
        return 2
    log(f"  官方数据日 = {dod}，Aluminium Cash Ask = {price} USD/t")

    # 2) 定位官方数据日所在行
    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb[SHEET_NAME]
    target_row = None
    for r in range(2, ws.max_row + 1):
        v = ws.cell(r, 1).value
        if isinstance(v, datetime.datetime) and v.strftime("%Y-%m-%d") == dod:
            target_row = r
            break
        if isinstance(v, str) and v.strip() == dod:
            target_row = r
            break

    if target_row is None:
        log(f"[2/4] 表中无 {dod} 行（该日非中国工作日，本就不记录）→ 无需回填，退出。")
        return 0

    old_val = norm_value(ws.cell(target_row, LME_COL).value)
    log(f"[2/4] 官方数据日 {dod} → Excel 行 {target_row}，现值 = {old_val}")

    if old_val is not None:
        if abs(old_val - price) < 1e-6:
            log(f"  已有值且与官方一致（{price}）→ 幂等跳过，不写不推送。")
            return 0
        log(f"  ⚠️ 现值 {old_val} ≠ 官方 {price}：**不覆盖**（保护人工修正）。")
        log("     如需以官方口径为准，请人工确认后修改。")
        return 3

    if DRY_RUN:
        log(f"  [dry-run] 将写入 行{target_row} 列{LME_COL} = {price}（未实际写入）")
        return 0

    # 3) 写入 + 留痕
    # 2026-09-23 整理：xlsx 备份统一落 backups/精工/
    bak_dir = SCRIPT_DIR / "backups" / "精工"
    bak_dir.mkdir(parents=True, exist_ok=True)
    bak = bak_dir / f"{EXCEL_PATH.name}.bak-{today.strftime('%Y%m%d')}"
    if not bak.exists():
        shutil.copy2(EXCEL_PATH, bak)
        log(f"[3/4] 已备份: {bak.name}（已存在则跳过）")

    ws.cell(target_row, LME_COL).value = price
    wb.save(EXCEL_PATH)
    log(f"  ✅ 写入 行{target_row}（{dod}）列{LME_COL} LME_AL = {price}")

    sha = current_commit_sha(str(SCRIPT_DIR))
    n = record_changes(
        [{"date_row": dod, "code": CODE, "old": old_val, "new": price}],
        source=SOURCE_AUTO_CRON, editor="—", commit=sha,
    )
    log(f"  📝 变更留痕 {n} 条（auto_cron）")

    # 4) 导出 + 推送
    log("[4/4] 导出 data.json 并推送...")
    subprocess.run([sys.executable, str(SCRIPT_DIR / "export_excel_to_json.py")],
                   cwd=str(SCRIPT_DIR), capture_output=True, text=True)
    if NO_PUSH:
        log("  --no-push 指定：已导出，未推送。")
        return 0

    r = _git(["add", "docs/data.json", "docs/changelog.json"])
    if r is None or r.returncode != 0:
        log(f"  ⚠️ git add 失败: {((r.stdout + r.stderr).strip() if r else 'timeout')}")
        return 1
    r = _git(["commit", "-m", f"LME 铝回填 {dod} = {price}（按官方数据日）"], timeout=60)
    if r is not None and r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr).lower():
        log(f"  ⚠️ git commit: {(r.stdout + r.stderr).strip()}")
        return 1

    if not push_robust():
        log("  ⚠️ 推送未成功 → 本地已提交，等下一轮（17:00 兜底/人工）补推。")
        v = _git(["rev-list", "--left-right", "--count", "HEAD...origin/main"], timeout=30)
        if v is not None:
            log(f"  当前 HEAD...origin/main = {v.stdout.strip()}")
        return 1

    log("  ✅ 完成：Excel / data.json / changelog 已推送")
    return 0


if __name__ == "__main__":
    sys.exit(main())
