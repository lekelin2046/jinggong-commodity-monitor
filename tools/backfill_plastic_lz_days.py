#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隆众系 16 品种「历史缺口回补」工具（塑料/橡胶看板）

背景
------------------------------------------------------------------
2026-10-17 前后 cookies/lz.json 的 token 到期（有效期约 7 天），
daily_plastic_ext.py 的登录体检判为不可用后**整段留空**（符合铁律，
但当天无人察觉），导致 10-19 起橡胶 16 品种集体缺数。

`fetch_daily()` 只能拿「当日最新」，历史缺口必须走曲线接口
`fetch_variety_curve(key, start, end)` 才能补。

口径说明（重要）
------------------------------------------------------------------
曲线口径（middlePrice）与日报口径（当日发布值）**不完全等价**，
历史实测差异集中在 5 个品种（C2_ETHYLENE / EPDM_13561C /
NR_SCRWF / NR_RSS3 / BR9000），量级 1~2%，其余 11 个品种逐日一致。
本工具默认用曲线值回补，并在报告里逐条列出「回补值」，供主人复核。
**只填空，不覆盖已有值**（--refresh 才覆盖）。

用法
------------------------------------------------------------------
    unset NODE_OPTIONS
    /Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/python \\
        tools/backfill_plastic_lz_days.py                    # 自动扫最近 15 天
    ... tools/backfill_plastic_lz_days.py --from 2026-10-19 --to 2026-10-21
    ... tools/backfill_plastic_lz_days.py --dry-run          # 只看不写
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

os.environ.pop("NODE_OPTIONS", None)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jinggong_monitor.safe_io import atomic_write_json          # noqa: E402
from jinggong_monitor.trading_calendar import is_trading_day     # noqa: E402
from jinggong_monitor.lz_price_center import (                   # noqa: E402
    fetch_variety_curve, check_login,
)

DATA_FILE = ROOT / "docs" / "plastic" / "data.json"
BACKUP_DIR = ROOT / "backups" / "塑料"

# 隆众内部 key → data.json 品种键（与 daily_plastic_ext.LZ_KEY_MAP 保持一致）
LZ_KEY_MAP = {
    "ETHYLENE": "C2_ETHYLENE", "PROPYLENE": "C3_PROPYLENE",
    "EPDM_6950C": "EPDM_6950C", "EPDM_3110M": "EPDM_3110M",
    "EPDM_13561C": "EPDM_13561C", "EPDM_3092PM": "EPDM_3092PM",
    "CARBON_BLACK_N550": "CB_N550",
    "NR_SCRWF": "NR_SCRWF", "NR_RSS3": "NR_RSS3",
    "BR9000": "BR9000", "SBR1712": "SBR1712",
    "ANTIOXIDANT_4020": "AO_4020",
    "ACCEL_DM": "ACC_DM", "ACCEL_CZ": "ACC_CZ",
    "ACCEL_M": "ACC_M", "ACCEL_TMTD": "ACC_TMTD",
}

# 已知与日报口径有差异的品种（曲线回补时提示）
DRIFT_KEYS = {"C2_ETHYLENE", "EPDM_13561C", "NR_SCRWF", "NR_RSS3", "BR9000"}


def main() -> int:
    ap = argparse.ArgumentParser(description="隆众 16 品种历史缺口回补")
    ap.add_argument("--from", dest="d_from", help="起始日 YYYY-MM-DD（默认：最近 15 天）")
    ap.add_argument("--to", dest="d_to", help="结束日 YYYY-MM-DD（默认：今天）")
    ap.add_argument("--dry-run", action="store_true", help="只抓取与报告，不写文件")
    ap.add_argument("--refresh", action="store_true", help="覆盖已有值（默认只填空）")
    args = ap.parse_args()

    today = datetime.date.today()
    d_to = datetime.date.fromisoformat(args.d_to) if args.d_to else today
    d_from = (datetime.date.fromisoformat(args.d_from) if args.d_from
              else d_to - datetime.timedelta(days=15))
    s_from, s_to = d_from.isoformat(), d_to.isoformat()

    print("=" * 74)
    print(f"隆众历史缺口回补 · 区间 {s_from} ~ {s_to}")
    print("=" * 74)

    ok, msg = check_login()
    print(f"登录态：{'✓' if ok else '✗'} {msg}")
    if not ok:
        print("✗ 登录态不可用，无法回补。请先跑 lz_login_setup.py")
        return 2

    db = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    data = db["data"]

    # 目标日期：区间内的工作日（调休上班的周六也算，取不到值会自动跳过）
    targets: list[str] = []
    d = d_from
    while d <= d_to:
        if is_trading_day(d):
            targets.append(d.isoformat())
        d += datetime.timedelta(days=1)
    print(f"目标工作日 {len(targets)} 天：{', '.join(targets)}")

    # 逐品种取曲线（一次取整段，避免逐日请求）
    filled: list[tuple[str, str, float, bool]] = []   # (data_key, 日期, 值, 是否口径分歧品种)
    created_days: set[str] = set()
    failed: list[str] = []

    for lz_key, dk in LZ_KEY_MAP.items():
        r = fetch_variety_curve(lz_key, s_from, s_to)
        if r.get("error"):
            failed.append(f"{dk}: {r['error']}")
            print(f"  ✗ {dk:14s} {r['error']}")
            continue
        series = r.get("series") or {}
        n = 0
        for day in targets:
            v = series.get(day)
            if v is None:
                continue
            row = data.get(day)
            if row is None:
                row = data[day] = {}
                created_days.add(day)
            old = row.get(dk)
            if old is None or args.refresh:
                if old is not None and abs(float(old) - v) < 1e-9:
                    continue
                row[dk] = v
                filled.append((dk, day, v, dk in DRIFT_KEYS))
                n += 1
        print(f"  {'✓' if n else '·'} {dk:14s} 曲线 {len(series)} 点 → 回补 {n} 个")

    print("-" * 74)
    if not filled:
        print("无可回补数据点（区间内各品种均已有值，或源方无报价）。")
        return 0

    drift = [f for f in filled if f[3]]
    print(f"共回补 {len(filled)} 个数据点，涉及 {len({f[1] for f in filled})} 天"
          f"（其中口径分歧品种 {len(drift)} 个）")
    print("\n明细（口径分歧品种标 *）：")
    for dk, day, v, is_drift in sorted(filled, key=lambda x: (x[1], x[0])):
        print(f"  {day}  {dk:14s} {v:>10,.0f}{'  *' if is_drift else ''}")

    if args.dry_run:
        print("\n（--dry-run：未写入文件）")
        return 0

    dates = sorted(data.keys())
    db["last_updated"] = dates[-1]
    db["total_days"] = len(dates)
    atomic_write_json(DATA_FILE, db, indent=1, backup=True, backup_dir=BACKUP_DIR)
    print(f"\n✓ 已写入 {DATA_FILE.name}"
          f"（共 {db['total_days']} 天，最新 {db['last_updated']}）")
    if created_days:
        print(f"  新建日期行：{', '.join(sorted(created_days))}")
    if failed:
        print("  ⚠ 失败品种：" + "; ".join(failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
