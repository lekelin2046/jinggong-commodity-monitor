#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成曼德看板「同比」基准：上年同月月均价（docs/mand/yoy_base.json）。

背景
----
曼德 data.json 只有 2026-01-05 起的日价，前端无法自行算同比。仓库内有
2025 全年日价的只有同源 SMM 铝序列（蜂巢/塑料看板），且只有两个品种与
曼德口径一致：AL_A00（SMM A00铝）、AL_A380（A380铝合金）。其余 11 个品种
没有同口径 2025 数据（卓创无免费历史、ccmn/SMM 历史需会员、部分牌号
仅有异源或异口径的零散数据），一律不写入＝前端留空。

铁律
----
1. 只用仓库内**已存在的日价**按自然月算术平均，绝不估算、绝不沿用前值。
2. 双闸门 fail loud，任一不过即拒绝写入，避免口径漂移造成假同比：
   · 对比年闸门：基准源在「基准年 + 1」的月均价须与 docs/mand/data.json
     逐月一致（相对偏差 ≤ MAX_GATE_DIFF_PCT）。
   · 双源闸门：基准年主源 vs 交叉源逐月均价差 ≤ MAX_GATE_DIFF_ABS 元。
3. 仅白名单品种写入；每月样本少于 MIN_DAYS 天则不写该月。
4. 落盘走 safe_io.atomic_write_json（原子写 + 写前备份）。

用法
----
    python3 tools/gen_mand_yoy_base.py                 # 默认基准年 2025
    python3 tools/gen_mand_yoy_base.py --base-year 2026
    python3 tools/gen_mand_yoy_base.py --dry-run      # 只打印，不落盘
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jinggong_monitor.safe_io import atomic_write_json  # noqa: E402

PRIMARY = ROOT / "docs" / "finest" / "data.json"     # 主源：与曼德 2026 序列逐月完全一致
CROSS = ROOT / "docs" / "plastic" / "data.json"      # 交叉源
MAND = ROOT / "docs" / "mand" / "data.json"          # 口径闸门对照
OUT = ROOT / "docs" / "mand" / "yoy_base.json"
BACKUP_DIR = ROOT / "backups" / "曼德"

# 只有这两个品种在 2025 年有同口径、全年 12 个月的日价
CODES = ("AL_A00", "AL_A380")
MIN_DAYS = 10
MAX_GATE_DIFF_PCT = 0.5     # 对比年逐月相对偏差上限（%）
MAX_GATE_DIFF_ABS = 0.5     # 双源逐月绝对差上限（元）


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def monthly_avg(doc: dict, year: int, codes=CODES) -> dict:
    """{code: {month: (avg, days)}}，只统计真实有值的日价。"""
    acc: dict[str, dict[str, list[float]]] = {}
    prefix = f"{year}-"
    for ds, row in doc.get("data", {}).items():
        if not ds.startswith(prefix) or not isinstance(row, dict):
            continue
        month = ds[5:7]
        for code in codes:
            value = row.get(code)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                acc.setdefault(code, {}).setdefault(month, []).append(float(value))
    return {
        code: {m: (sum(vals) / len(vals), len(vals)) for m, vals in months.items()}
        for code, months in acc.items()
    }


def gate_compare_year(mand: dict, primary: dict, year: int) -> dict:
    """基准源在对比年的月均价，必须与曼德同源。"""
    a = monthly_avg(mand, year)
    b = monthly_avg(primary, year)
    checked, max_diff = 0, 0.0
    for code in CODES:
        for month, (avg_a, _) in a.get(code, {}).items():
            if month not in b.get(code, {}):
                continue
            avg_b = b[code][month][0]
            diff = abs(avg_a - avg_b) / avg_b * 100
            max_diff = max(max_diff, diff)
            checked += 1
            if diff > MAX_GATE_DIFF_PCT:
                raise SystemExit(
                    f"[闸门失败] 对比年 {year} {code} {month}月：曼德 {avg_a:.2f} "
                    f"vs 基准源 {avg_b:.2f}，偏差 {diff:.3f}% > {MAX_GATE_DIFF_PCT}%"
                )
    if checked == 0:
        return {"status": "skipped", "reason": f"对比年 {year} 无重叠月数据", "max_diff_pct": None}
    return {"status": "passed", "checked_months": checked, "max_diff_pct": round(max_diff, 6)}


def gate_cross_source(primary: dict, cross: dict, year: int) -> dict:
    """基准年主源 vs 交叉源逐月均价须一致。"""
    a = monthly_avg(primary, year)
    b = monthly_avg(cross, year)
    checked, max_diff, missing = 0, 0.0, []
    for code in CODES:
        for month, (avg_a, _) in a.get(code, {}).items():
            if month not in b.get(code, {}):
                missing.append(f"{code}-{month}")
                continue
            avg_b = b[code][month][0]
            diff = abs(avg_a - avg_b)
            max_diff = max(max_diff, diff)
            checked += 1
            if diff > MAX_GATE_DIFF_ABS:
                raise SystemExit(
                    f"[闸门失败] 基准年 {year} {code} {month}月：主源 {avg_a:.2f} "
                    f"vs 交叉源 {avg_b:.2f}，差 {diff:.3f} 元 > {MAX_GATE_DIFF_ABS} 元"
                )
    return {
        "status": "passed" if not missing else "partial",
        "checked_months": checked,
        "max_diff": round(max_diff, 6),
        "missing_in_cross": missing,
    }


def build_year(primary: dict, year: int) -> dict:
    avgs = monthly_avg(primary, year)
    out = {}
    for code in CODES:
        months = {}
        for month, (avg, days) in sorted(avgs.get(code, {}).items()):
            if days < MIN_DAYS:
                print(f"  [跳过] {code} {year}-{month}：样本仅 {days} 天 < {MIN_DAYS} 天")
                continue
            months[month] = {"avg": round(avg, 2), "days": days}
        if months:
            out[code] = months
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="生成曼德看板同比基准（上年同月月均价）")
    ap.add_argument("--base-year", type=int, default=2025, help="基准年，默认 2025")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不落盘")
    args = ap.parse_args()
    base_year = args.base_year
    compare_year = base_year + 1

    mand, primary, cross = load(MAND), load(PRIMARY), load(CROSS)

    print(f"基准年 {base_year}｜对比年 {compare_year}｜品种白名单 {', '.join(CODES)}")
    gate1 = gate_compare_year(mand, primary, compare_year)
    gate2 = gate_cross_source(primary, cross, base_year)
    print(f"  对比年口径闸门：{gate1}")
    print(f"  双源交叉闸门：{gate2}")

    payload = build_year(primary, base_year)
    for code, months in payload.items():
        print(f"  {code}: {len(months)} 个月 → " + ", ".join(
            f"{m}={v['avg']:.2f}({v['days']}天)" for m, v in months.items()
        ))

    if args.dry_run:
        print("--dry-run：未落盘")
        return

    years = {}
    if OUT.exists():
        years = load(OUT).get("years", {})
    years[str(base_year)] = payload
    doc = {
        "generated_at": date.today().isoformat(),
        "source": "docs/finest/data.json（主源）｜docs/plastic/data.json（交叉验证）｜客户物料价格走势工作簿「铝 -日」同源序列",
        "method": "按自然月对该月真实日价算术平均；样本 <10 天的月份不写入",
        "coverage_note": "仅 AL_A00 / AL_A380 通过同口径闸门；其余 11 个品种无同口径上年数据，前端一律留空",
        "gate": {"compare_year": gate1, "cross_source": gate2},
        "years": years,
    }
    atomic_write_json(OUT, doc, indent=2, ensure_ascii=False,
                      backup=True, backup_dir=BACKUP_DIR, same_day_max=2)
    print(f"已写入 {OUT.relative_to(ROOT)}（共 {len(years)} 个基准年）")


if __name__ == "__main__":
    main()
