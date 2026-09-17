#!/usr/bin/env python3
"""SMM 定向补抓并回填当日行（用于 15:00 主流程 SMM 整块失败时的补救）

背景：2026-09-17 主流程 SMM 全列「正则未匹配」→ 触发内部重登录 → 外层
`fetch_smm()` 的 90s 超时把登录流程掐断 → SMM 12 键全空。页面与 cookies
事后实测均正常，属时点性渲染失败。

用法：
    unset NODE_OPTIONS
    ~/.workbuddy/binaries/python/envs/jinggong/bin/python refetch_smm_fill.py [--dry]

- 复用主流程的 fetch_smm / write_excel / export_and_push，写表、留痕、导出、
  推送行为与主流程完全一致（changelog source=auto_cron）。
- 只传 SMM 相关键，Excel 其余列不受影响（write_excel 对缺键列只打印不写入）。
- 铁律：抓不到即不写，绝不沿用前值。
"""

import argparse
import asyncio
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from daily_update_all import fetch_smm, write_excel, export_and_push  # noqa: E402

SMM_CODES = {
    "ADC12", "A380", "AlSi9Cu3", "A356",
    "AM60B", "AZ91D", "ADC12_JAPAN_CIF",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只抓取不写表")
    args = ap.parse_args()

    prices = asyncio.run(fetch_smm())
    sub = {k: v for k, v in prices.items() if k in SMM_CODES}

    print(f"\n抓到 SMM 目标品种 {len(sub)}/{len(SMM_CODES)}: {sub}")
    missing = SMM_CODES - set(sub)
    if missing:
        print(f"⚠️ 仍未抓到（保持留空）: {sorted(missing)}")

    if not sub:
        print("❌ 无任何 SMM 数据，不写表。")
        return 1
    if args.dry:
        print("（--dry 模式，未写表）")
        return 0

    row = write_excel(sub)
    ok = export_and_push(row)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
