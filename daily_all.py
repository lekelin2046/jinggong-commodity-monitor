#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily_all.py — 五板块统一编排器（15:00 全量抓取 / 17:00 统一补差）

背景
----
原先 5 档定时任务错峰运行（精工 15:00 / 塑料 15:30 / 曼德 15:35 / 塑料扩品
15:40 / 蜂巢 15:50）。错峰的唯一原因是**五档共用同一批登录凭证**
（cookies/smm*.json、cookies/lz.json、data/asianmetal_cookies.json），并发
会相互覆盖。合并为一个**串行**编排后该约束自然消失，且 git 推送由 4~5 次
收敛为 1 次（push 是本项目历史失败最集中的环节）。

用法
----
    python daily_all.py              # 全量：五板块依次抓取 → 统一推送
    python daily_all.py --check      # 补差：只补当日不完整的板块 → 统一推送
    python daily_all.py --only mand  # 只跑指定板块（排障用，逗号分隔）
    python daily_all.py --dry-run    # 只列出将要执行的步骤，不实跑

设计约束
--------
1. **串行**：各板块共用 cookies，禁止并发（这是合并的前提，不是限制）。
2. **板块间隔离**：任一板块失败或超时，其余照常执行，最后统一汇报
   （对齐铁律 2「单源故障不得中止整轮」）。
3. **单板块超时保护**：子进程设 `STEP_TIMEOUT`，超时即杀并记失败，不拖垮整轮。
4. **抓取到即推送**：即使只有部分板块成功，也要把成功的成果推上去；
   全部板块都没产出时才不提交。
5. **补差是「先检查、缺才跑」**：
   - 精工复用 `daily_check_missed.py`（按 Excel 列精准判定，含 LME 兜底）；
   - 其余板块比对「当日品种数 vs 最近 `BASELINE_DAYS` 个交易日基线」，
     低于基线即视为不完整。重跑是安全的——各脚本幂等（曼德当日值刷新、
     塑料「不存在才写」、蜂巢同日合并）。
6. **推送统一由本编排器做一次**：子脚本以 `--no-push` 或不带 `--push` 运行。

⚠️ 不合并的定时任务：次日 9:00 的 LME 官方价回填（依赖 LME 官网发布节奏，
且偶遭 Cloudflare 拦截）、每月 3 日的 LME 月度核验——二者保持独立。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from jinggong_monitor.trading_calendar import is_trading_day, skip_reason  # noqa: E402

PY = sys.executable

# 子进程环境：SMM 抓取需 Playwright，NODE_OPTIONS 残留会导致启动失败
ENV = os.environ.copy()
ENV.pop("NODE_OPTIONS", None)

# 单板块超时（秒）。实测各板块正常 1~5 分钟，LME 回填曾跑到 10 分钟，留足余量。
STEP_TIMEOUT = 900

# 补差基线：最近 N 个交易日
BASELINE_DAYS = 10

PLATES: List[Dict] = [
    {
        "key": "jinggong",
        "name": "精工 26 品种",
        "cmds": [["daily_update_all.py", "--no-push"]],
        # 补差走现成的精准检查（按 Excel 列判定，另含 LME 铝兜底）
        "check_cmds": [["daily_check_missed.py", "--no-push"]],
        "json": "docs/data.json",
        "check": "script",
    },
    {
        "key": "plastic",
        "name": "诺博内外饰 13 牌号 + 诺博橡胶 21 项",
        "cmds": [["jinggong_monitor/daily_plastic.py"],
                 ["jinggong_monitor/daily_plastic_ext.py"]],
        "json": "docs/plastic/data.json",
        "check": "json",
    },
    {
        "key": "mand",
        "name": "曼德热系统 13 项",
        "cmds": [["mand_update.py"]],
        "json": "docs/mand/data.json",
        "check": "json",
    },
    {
        "key": "finest",
        "name": "蜂巢汽车 13 项",
        "cmds": [["finest_update.py"]],
        "json": "docs/finest/data.json",
        "check": "json",
    },
]

# 统一推送的文件清单（显式列出，避免把工作区无关文件一起提交）
PUSH_FILES = [
    "docs/data.json",
    "docs/changelog.json",
    "docs/plastic/data.json",
    "docs/mand/data.json",
    "docs/finest/data.json",
]


# --------------------------------------------------------------------------
# 补差判定
# --------------------------------------------------------------------------
def _json_incomplete(json_rel: str) -> Tuple[bool, str]:
    """当日数据是否疑似不完整（当日行缺失，或品种数低于近 N 日基线）。"""
    p = SCRIPT_DIR / json_rel
    if not p.is_file():
        return True, f"数据文件不存在（{json_rel}）"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return True, f"数据文件解析失败：{type(e).__name__}: {e}"

    data = doc.get("data") or {}
    if not data:
        return True, "数据文件无 data 段"

    today = date.today().isoformat()
    if today not in data:
        return True, "当日无数据行"

    # 日期键为 YYYY-MM-DD，字典序即时间序
    history = [d for d in sorted(data) if d < today][-BASELINE_DAYS:]
    if not history:
        return False, "无历史基线可比，视为正常"

    baseline = max(len(data[d]) for d in history)
    cur = len(data[today])
    if cur < baseline:
        return True, f"当日 {cur} 个品种 < 近 {len(history)} 日基线 {baseline}（疑有留空）"
    return False, f"当日 {cur} 个品种 ≥ 近 {len(history)} 日基线 {baseline}"


# --------------------------------------------------------------------------
# 执行
# --------------------------------------------------------------------------
def _run_cmd(cmd: List[str]) -> Tuple[bool, float, str]:
    """运行单个子脚本，返回 (是否成功, 耗时秒, 输出摘要)。超时不算崩溃。"""
    full = [PY, str(SCRIPT_DIR / cmd[0])] + list(cmd[1:])
    label = " ".join(cmd)
    t0 = time.time()
    try:
        r = subprocess.run(full, cwd=str(SCRIPT_DIR), env=ENV,
                           capture_output=True, text=True, timeout=STEP_TIMEOUT)
    except subprocess.TimeoutExpired:
        dur = time.time() - t0
        print(f"  ❌ {label} 超时（>{STEP_TIMEOUT}s），已终止")
        return False, dur, f"超时（>{STEP_TIMEOUT}s）"
    except Exception as e:  # noqa: BLE001
        dur = time.time() - t0
        print(f"  ❌ {label} 启动失败：{type(e).__name__}: {e}")
        return False, dur, f"启动失败：{type(e).__name__}"

    dur = time.time() - t0
    out = (r.stdout or "") + (r.stderr or "")
    tail = [ln for ln in out.strip().splitlines() if ln.strip()][-6:]
    if r.returncode == 0:
        print(f"  ✓ {label} 完成（{dur:.0f}s）")
    else:
        print(f"  ❌ {label} 退出码 {r.returncode}（{dur:.0f}s）")
    for ln in tail:
        print(f"      | {ln.strip()[:150]}")
    return r.returncode == 0, dur, "\n".join(tail)


def _push_all(notes: List[str]) -> bool:
    """统一提交并推送一次。"""
    try:
        from git_helper import publish_to_github  # noqa: E402
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ 加载 git_helper 失败：{e}")
        return False

    files = [f for f in PUSH_FILES if (SCRIPT_DIR / f).is_file()]
    msg = (f"daily_all: {date.today().isoformat()} 五板块统一更新\n\n"
           + "\n".join(f"- {n}" for n in notes))
    return bool(publish_to_github(files, msg, cwd=str(SCRIPT_DIR)))


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="精工系五看板统一编排")
    ap.add_argument("--check", action="store_true",
                    help="补差模式：只补当日不完整的板块")
    ap.add_argument("--only", default="", help="只跑指定板块，逗号分隔（排障用）")
    ap.add_argument("--dry-run", action="store_true", help="只列出步骤，不实跑")
    args = ap.parse_args()

    mode = "补差" if args.check else "全量"
    today = date.today()

    print("=" * 72)
    print(f"五板块统一编排 · {mode}模式 · {today.isoformat()}")
    print("=" * 72)

    # 非交易日直接退出（各板块脚本自身也有同样的守卫，这里提前拦住省时间）
    if not is_trading_day(today):
        print(f"⏸️  今日为{skip_reason(today)}（{today.isoformat()}），市场休市，跳过。")
        return 0

    plates = PLATES
    if args.only:
        want = {k.strip() for k in args.only.split(",") if k.strip()}
        plates = [p for p in plates if p["key"] in want]
        if not plates:
            print(f"❌ --only 未匹配到任何板块：{args.only}")
            return 2

    results: List[Tuple[str, str, str, float]] = []  # (板块, 状态, 说明, 耗时)
    pushed = False
    total_t0 = time.time()

    for idx, plate in enumerate(plates, 1):
        print(f"\n{'-' * 72}")
        print(f"[{idx}/{len(plates)}] {plate['name']}")
        print("-" * 72)

        cmds = plate["cmds"]
        if args.check:
            # 精工走自带检查脚本；其余板块比对当日品种数
            if plate["check"] == "script":
                cmds = plate["check_cmds"]
                print("  → 精工：交由 daily_check_missed.py 判定（缺才补）")
            else:
                need, why = _json_incomplete(plate["json"])
                print(f"  → 完整性检查：{why}")
                if not need:
                    results.append((plate["name"], "skip", why, 0.0))
                    continue

        if args.dry_run:
            for c in cmds:
                print(f"  [dry-run] 将执行：{' '.join(c)}")
            results.append((plate["name"], "dry", "仅列出", 0.0))
            continue

        plate_ok = True
        plate_dur = 0.0
        for c in cmds:
            ok, dur, _ = _run_cmd(c)
            plate_dur += dur
            plate_ok = plate_ok and ok
        results.append((plate["name"], "ok" if plate_ok else "fail",
                        "完成" if plate_ok else "有步骤失败", plate_dur))

    # ===== 统一推送 =====
    print(f"\n{'=' * 72}")
    print("统一推送")
    print("=" * 72)

    todo = [r for r in results if r[1] in ("ok", "fail")]
    if args.dry_run:
        print("  [dry-run] 跳过推送")
    elif not todo:
        print("  （本轮无板块产出，不提交）")
    else:
        notes = [f"{n}：{s}（{d:.0f}s）" for n, s, _, d in results if s != "dry"]
        pushed = _push_all(notes) if notes else False

    # ===== 汇总 =====
    total_dur = time.time() - total_t0
    ok_n = sum(1 for r in results if r[1] == "ok")
    fail_n = sum(1 for r in results if r[1] == "fail")
    skip_n = sum(1 for r in results if r[1] in ("skip", "dry"))

    print(f"\n{'=' * 72}")
    print(f"汇总 · {mode}模式 · 总耗时 {total_dur / 60:.1f} 分钟")
    print("=" * 72)
    for name, st, note, dur in results:
        icon = {"ok": "✓", "fail": "❌", "skip": "－", "dry": "·"}.get(st, "?")
        print(f"  {icon} {name:34s} {note}（{dur:.0f}s）")
    print(f"\n  成功 {ok_n} / 失败 {fail_n} / 跳过 {skip_n}")
    if not args.dry_run:
        print(f"  推送：{'✅ 已推送' if pushed else '❌ 未推送或失败'}")
    print()

    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
