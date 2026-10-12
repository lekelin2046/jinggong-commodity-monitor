#!/usr/bin/env python3
"""卓创资讯定向补抓并回填当日行（用于 15:00 主流程卓创部分品种失败时的补救）

背景：2026-10-12 主流程卓创「高碳铬铁」页面 goto 超时（45s networkidle），
其余 5 品种正常。单源失败不该让该列留空过夜——17:00 补抓也会兜底，
但如当时段网络恢复，可直接定向补齐。

用法：
    unset NODE_OPTIONS
    ~/.workbuddy/binaries/python/envs/jinggong/bin/python refetch_sci99_fill.py [--dry] [--only HIGH_CARBON_FECR]

- 复用主流程的 fetch_sci99 / write_excel / export_and_push，写表、留痕、导出、
  推送行为与主流程完全一致（changelog source=auto_cron）。
- 默认只写当日缺失的键（与已写入行做差集），避免重复覆盖已成功列。
- 铁律：抓不到即不写，绝不沿用前值。
"""

import argparse
import asyncio
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import openpyxl  # noqa: E402

from daily_update_all import (  # noqa: E402
    COL_MAP, EXCEL_PATH, SHEET_NAME,
    fetch_sci99, write_excel, export_and_push,
)


def current_missing() -> set[str]:
    """当日行中值为空的品种代码集合（LME_AL 等延后列除外）。"""
    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb[SHEET_NAME]
    row = ws.max_row
    missing: set[str] = set()
    for col, (code, _src) in COL_MAP.items():
        v = ws.cell(row, col).value
        if v is None or (isinstance(v, str) and not v.strip()):
            missing.add(code)
    return missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只抓取不写表")
    ap.add_argument("--only", nargs="*", default=None,
                    help="只写指定品种代码（默认：当日行缺失的品种）")
    args = ap.parse_args()

    targets = set(args.only) if args.only else None
    print(f"写入目标：{sorted(targets) if targets else '(读取当日缺失列)'}")

    prices = asyncio.run(fetch_sci99())
    print(f"\n卓创抓到 {len(prices)} 项: {prices}")

    if targets is None:
        targets = current_missing()
        print(f"当日缺失品种: {sorted(targets)}")

    sub = {k: v for k, v in prices.items() if k in targets}
    missing = targets - set(sub)
    if missing:
        print(f"⚠️ 仍未抓到（保持留空）: {sorted(missing)}")
    if not sub:
        print("❌ 无可写数据，不写表。")
        return 1
    if args.dry:
        print(f"（--dry 模式，未写表。将写入 {len(sub)} 项）")
        return 0

    row = write_excel(sub)
    ok = export_and_push(row)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
