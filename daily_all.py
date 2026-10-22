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
from datetime import date, timedelta
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

# 跑完后复核的窗口（有数据日）。取 5 是为了「漏一天能在当天或次日被发现」，
# 又不至于把上周的个别缺值天天报一遍。
POST_CHECK_DAYS = 5

# 凭证到期预警阈值（天）。隆众 token 到期后 daily_plastic_ext 会对 16 个
# 橡胶/助剂品种**整段留空**（符合铁律「抓不到就留空」，但历史上因此在
# 2026-10-19 静默缺数三轮未被发现）。故提前 N 天就在推送信息与汇总里喊。
TOKEN_WARN_DAYS = 5

# 隆众历史缺口回补（每日收尾自动跑）。回看天数决定「最久能自愈到几天前」，
# 取 7 是为了覆盖「周末 + 假期连休」又不至于每天都扫半个月。
LZ_BACKFILL_DAYS = 7
LZ_BACKFILL_TIMEOUT = 420
PLASTIC_JSON = "docs/plastic/data.json"

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
def _filled(row: Dict) -> int:
    """当日**真正有值**的品种数。

    只数 key 会把「键在、值为 None」当成有数（2026-10-21 验证发现：
    人为置 None 后 len 不变，缺口检测与回补增量双双失灵）。当前各脚本
    都是「有值才写键」，故行为不变，但判据从此不依赖这个约定。
    """
    return sum(1 for v in (row or {}).values() if v is not None and v != "")


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

    baseline = max(_filled(data[d]) for d in history)
    cur = _filled(data[today])
    if cur < baseline:
        return True, f"当日 {cur} 个品种 < 近 {len(history)} 日基线 {baseline}（疑有留空）"
    return False, f"当日 {cur} 个品种 ≥ 近 {len(history)} 日基线 {baseline}"


def _credential_warnings() -> List[str]:
    """凭证到期预警（只提示，不阻断）。目前只有隆众是「token 到期即静默留空」的源。"""
    warns: List[str] = []
    try:
        from jinggong_monitor.lz_price_center import token_expiry  # noqa: E402

        exp = token_expiry()
        if exp:
            days = (exp - time.time()) / 86400
            if days <= TOKEN_WARN_DAYS:
                state = "已过期" if days <= 0 else f"剩余 {days:.1f} 天"
                warns.append(
                    f"隆众 token {state} → 请重跑 lz_login_setup.py"
                    f"（否则橡胶 16 品种将整段留空）"
                )
    except Exception as e:  # noqa: BLE001
        warns.append(f"隆众 token 体检失败：{type(e).__name__}: {e}")
    return warns


def _post_check(plates: List[Dict]) -> List[str]:
    """跑完后复核每个 json 板块「近几日」的完整度。失败不阻断，只进告警。

    为什么要看近几日而不只看当日：2026-10-17 隆众 token 到期后，10-19 那轮
    照常「✓ 完成」并推送（当日有行、只是品种大半为空），直到三天后人工
    看图表才发现。故此处以「近 POST_CHECK_DAYS 个有数据日」为窗口，
    任一日的品种数低于窗口内峰值即视为有留空。

    与 --check 模式的判据同源，但此处**不做补跑**，只要求「看得到」。
    """
    issues: List[str] = []
    for p in plates:
        if p.get("check") != "json":
            continue
        try:
            issues.extend(_recent_gaps(p["json"], p["name"]))
        except Exception as e:  # noqa: BLE001
            issues.append(f"{p['name']}：完整性检查异常 {type(e).__name__}: {e}")
    return issues


def _recent_gaps(json_rel: str, plate_name: str) -> List[str]:
    """近 POST_CHECK_DAYS 个有数据日里，品种数低于窗口峰值的日子。"""
    p = SCRIPT_DIR / json_rel
    if not p.is_file():
        return [f"{plate_name}：数据文件不存在（{json_rel}）"]
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return [f"{plate_name}：数据文件解析失败 {type(e).__name__}: {e}"]

    data = doc.get("data") or {}
    if not data:
        return [f"{plate_name}：data 段为空"]

    days = sorted(data)[-POST_CHECK_DAYS:]
    peak = max(_filled(data[d]) for d in days)
    out = []
    for d in days:
        n = _filled(data[d])
        if n < peak:
            out.append(f"{plate_name}：{d} 仅 {n} 个品种（窗口峰值 {peak}），疑有留空")
    return out


# --------------------------------------------------------------------------
# 执行
# --------------------------------------------------------------------------
def _run_cmd(cmd: List[str], timeout: Optional[int] = None) -> Tuple[bool, float, str]:
    """运行单个子脚本，返回 (是否成功, 耗时秒, 输出摘要)。超时不算崩溃。"""
    limit = timeout or STEP_TIMEOUT
    full = [PY, str(SCRIPT_DIR / cmd[0])] + list(cmd[1:])
    label = " ".join(cmd)
    t0 = time.time()
    try:
        r = subprocess.run(full, cwd=str(SCRIPT_DIR), env=ENV,
                           capture_output=True, text=True, timeout=limit)
    except subprocess.TimeoutExpired:
        dur = time.time() - t0
        print(f"  ❌ {label} 超时（>{limit}s），已终止")
        return False, dur, f"超时（>{limit}s）"
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


# --------------------------------------------------------------------------
# 隆众历史缺口回补（收尾自动跑，只填空、幂等）
# --------------------------------------------------------------------------
def _plastic_counts(days: int = LZ_BACKFILL_DAYS) -> Dict[str, int]:
    """近 N 个数据日 → 当日有值品种数（用于算回补增量）。"""
    p = SCRIPT_DIR / PLASTIC_JSON
    try:
        data = json.loads(p.read_text(encoding="utf-8")).get("data") or {}
    except Exception:  # noqa: BLE001
        return {}
    return {d: _filled(data[d]) for d in sorted(data)[-days:]}


def _lz_backfill() -> Tuple[str, int]:
    """跑隆众回补脚本，返回 (状态, 回补点数)。失败只告警、不阻断整轮。

    为什么每天都要跑：隆众日报接口只给**最新一条**，历史缺口只能走曲线接口
    （`fetch_variety_curve`）。token 一旦到期（约 30 天），`daily_plastic_ext`
    会把 16 个橡胶/助剂品种整段留空；等人工从图表上发现时，往往已过 2~3 天。
    虽然曲线接口能补，但「补登后只能覆盖到最新报价日」的品种就永久缺了。
    故每日收尾扫最近 LZ_BACKFILL_DAYS 天，把漏的一两天当天就补回来。

    安全性：脚本**只填空、不覆盖已有值**（--refresh 才覆盖），逐日幂等；
    退出码非 0 只记 warn，不影响其他板块与本轮推送。
    """
    script = SCRIPT_DIR / "tools" / "backfill_plastic_lz_days.py"
    if not script.is_file():
        return "warn", 0

    before = _plastic_counts()
    d_from = (date.today() - timedelta(days=LZ_BACKFILL_DAYS)).isoformat()
    ok, _dur, _tail = _run_cmd(
        ["tools/backfill_plastic_lz_days.py", "--from", d_from],
        timeout=LZ_BACKFILL_TIMEOUT,
    )
    after = _plastic_counts()
    # 只填空不覆盖 ⇒ 品种数增量即回补点数
    added = sum(max(0, n - before.get(d, 0)) for d, n in after.items())
    return ("ok" if ok else "warn"), added


def _tungsten_pending() -> str:
    """当日钨粉(W)是否仍「已存证官方图、待视觉确认」。返回提示串（空串=无需关注）。

    背景（2026-10-22）：中钨在线**栏目页文章列表**已停更，但官方每日报价表
    图片仍按日发布（URL 规则固定）。`ChinatungstenFetcher.fetch()` 在原文章
    路径取不到时会自动下载该图存证并抛错——数值**不由程序猜**（水印压行、
    OCR 结构性不可靠），须视觉读取后经 `refetch_tungsten_fill.py --price` 写入。

    这里只做「把待办喊出来」：15:00 常因官方图尚未上传（实测 14:00~15:26 才发）
    而留空，17:00 `--check` 再取一次；若仍存证未回填，就在汇总与推送信息里
    明确列出图路径与命令，避免像 10-20~10-22 那样静默留空无人察觉。
    """
    today = date.today()
    try:
        doc = json.loads((SCRIPT_DIR / "docs/data.json").read_text(encoding="utf-8"))
        w = ((doc.get("data") or {}).get(today.isoformat()) or {}).get("W")
    except Exception as e:  # noqa: BLE001
        return f"钨粉状态检查失败：{type(e).__name__}: {e}"

    if w not in (None, ""):
        return ""

    try:
        from jinggong_monitor.tungsten_official import fill_command, pending_evidence
    except Exception as e:  # noqa: BLE001
        return f"钨粉待办模块不可用：{type(e).__name__}: {e}"

    img = pending_evidence(today)
    if img is not None:
        return (f"钨粉 W 待视觉确认：官方报价表已存证 {img}。"
                f"读取图内 Tungsten Powder 99.9% 的 Price(Domestic) 后执行 "
                f"{fill_command(today)}")
    return "钨粉 W 留空，且官方报价表当日不可得（可能未发布）→ 按铁律留空"


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

    # 凭证预检：到期预警要在开跑前就喊出来（跑完才发现就晚了）
    warns = _credential_warnings()
    if warns:
        print()
        for w in warns:
            print(f"  ⚠️  {w}")

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

    # ===== 收尾：隆众历史缺口回补（只填空、幂等，失败不阻断）=====
    backfill_note = ""
    if not args.dry_run and any(p["key"] == "plastic" for p in plates):
        print(f"\n{'-' * 72}")
        print(f"隆众历史缺口回补（近 {LZ_BACKFILL_DAYS} 天，只填空不覆盖）")
        print("-" * 72)
        bf_state, bf_added = _lz_backfill()
        if bf_state != "ok":
            backfill_note = "隆众回补失败（详见日志）"
        elif bf_added:
            backfill_note = f"隆众回补 {bf_added} 点"
        else:
            backfill_note = "隆众无缺口"
        print(f"  → {backfill_note}")

    # ===== 钨粉待视觉确认（官方图已存证但未取数，需读图后回填）=====
    tungsten_note = ""
    if not args.dry_run and any(p["key"] == "jinggong" for p in plates):
        tungsten_note = _tungsten_pending()
        if tungsten_note:
            print(f"\n{'-' * 72}")
            print("钨粉(W) 待办")
            print("-" * 72)
            print(f"  ⚠️  {tungsten_note}")

    # ===== 跑完复核当日完整度（只告警、不补跑，补跑交给 17:00 --check）=====
    data_issues: List[str] = []
    if not args.dry_run and not args.check:
        data_issues = _post_check(plates)
        if data_issues:
            print(f"\n{'!' * 72}")
            print("⚠️  数据完整度复核未通过（本轮有留空，17:00 --check 会再补一次）")
            print(f"{'!' * 72}")
            for it in data_issues:
                print(f"  · {it}")

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
        if backfill_note:
            notes.append(f"↺ {backfill_note}")
        # 告警一并写进提交信息，便于事后回溯「哪天开始缺数、缺多久」
        notes += [f"⚠ {w}" for w in warns]
        notes += [f"⚠ 不完整 {it}" for it in data_issues]
        if tungsten_note:
            notes.append(f"⚠ {tungsten_note}")
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
    if backfill_note:
        print(f"  回补：{backfill_note}")
    if tungsten_note:
        print(f"  ⚠️  钨粉待办：{tungsten_note}")
    if warns or data_issues:
        print(f"  ⚠️  告警 {len(warns) + len(data_issues)} 条：")
        for w in warns:
            print(f"     - {w}")
        for it in data_issues:
            print(f"     - 不完整 {it}")
    if not args.dry_run:
        print(f"  推送：{'✅ 已推送' if pushed else '❌ 未推送或失败'}")
    print()

    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
