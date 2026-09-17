#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_plastic_ext.py — 塑料看板「扩品类」历史回填（隆众 15 项）

背景（2026-09-17 实测）
------------------------------------------------------------------
扩品类 20 项上线时**只从当天开始记**，历史为空（看板上一片 `-`）。
而隆众的结构化价格库**可回溯**，靠的是曲线接口：

    POST /ndc/price/curve/getSingleCurve
    {"businessId":<行id>, "businessType":3, "twoLevelBusinessType":0,
     "indexPriceType":0, "timeType":0,
     "queryStartDate":"2026-07-01", "queryEndDate":"2026-09-17"}

返回 `priceDataList`，是**整段日序列**（不像 `queryPricePage` 只给 5 个日期），
每条带 `lowPrice / highPrice / **middlePrice(主流价)**`。
→ 一次请求 = 一个品种一段完整历史。

`businessId` 是「品种 × 市场 × 规格」的行 id，稳定。本脚本先用
`queryPricePage` 枚举行、按 `VARIETY_MAP` 的 specs/markets/strict 口径选中目标行，
再调曲线接口（复用 `lz_price_center.resolve_business_row` / `fetch_variety_curve`）。

口径
------------------------------------------------------------------
  · 价格优先取 `middlePrice`（主流价），与主流程 `pick_price()` 同哲学；
    区间型品种（丙烯/炭黑/防老剂/促进剂）隆众的 middlePrice 就是区间中值。
  · 默认 **不覆盖已存在的值**（幂等）；要按源最新口径重刷加 `--refresh`。
  · 取不到的日期留空，**绝不编造、绝不沿用前值**。

范围
------------------------------------------------------------------
  · 隆众 15 项：可回填至 **2026-07-01**（本脚本负责）
  · SMM 铝 4 项 / 百川煤焦油 1 项：源站免费历史不可得，**不在本脚本范围**（见 SKILL.md）

用法
------------------------------------------------------------------
    unset NODE_OPTIONS
    /Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/python \
        jinggong_monitor/backfill_plastic_ext.py --from 2026-07-01 [--to YYYY-MM-DD] \
        [--dry-run] [--refresh] [--only KEY1,KEY2]
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
from pathlib import Path

os.environ.pop("NODE_OPTIONS", None)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jinggong_monitor.daily_plastic_ext import NEW_VARIETIES, LZ_KEY_MAP  # noqa: E402
from jinggong_monitor.lz_price_center import (                           # noqa: E402
    fetch_variety_curve, check_login,
)

DATA_FILE = ROOT / "docs" / "plastic" / "data.json"

logger = logging.getLogger("jinggong.backfill_ext")


def main():
    ap = argparse.ArgumentParser(description="塑料看板扩品类历史回填（隆众 15 项）")
    ap.add_argument("--from", dest="start", default="2026-07-01",
                    help="起始日期 YYYY-MM-DD（默认 2026-07-01）")
    ap.add_argument("--to", dest="end", default=None,
                    help="结束日期 YYYY-MM-DD（默认今天）")
    ap.add_argument("--only", default="", help="只回填指定 data 键，逗号分隔")
    ap.add_argument("--dry-run", action="store_true", help="只抓取不写文件")
    ap.add_argument("--refresh", action="store_true",
                    help="覆盖已有值（默认只补空缺，幂等）")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    end = args.end or datetime.date.today().isoformat()
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    if not DATA_FILE.exists():
        print(f"✗ 找不到 {DATA_FILE}")
        sys.exit(1)

    print("=" * 78)
    print(f"扩品类历史回填 · 隆众 {len(LZ_KEY_MAP)} 项   {args.start} ~ {end}")
    print("=" * 78)

    ok, msg = check_login()
    print(f"隆众登录态：{'✓' if ok else '✗'} {msg}")
    if not ok:
        print("✗ 登录态不可用，终止（不用旧值兜底）")
        sys.exit(1)

    # ---- 抓取 ----
    series_by_key: dict[str, dict[str, float]] = {}
    rows_used: dict[str, str] = {}
    for lz_key, dk in LZ_KEY_MAP.items():
        if only and dk not in only:
            continue
        r = fetch_variety_curve(lz_key, args.start, end)
        if r["error"]:
            print(f"  ✗ {r['name']:16s} {r['error']}")
            continue
        vals = {d: v for d, v in r["series"].items() if v is not None}
        if not vals:
            print(f"  ✗ {r['name']:16s} 序列为空（{r['source']}）")
            continue
        series_by_key[dk] = vals
        rows_used[dk] = r["source"]
        ds = sorted(vals)
        print(f"  ✓ {r['name']:16s} {r['source']:14s} {len(vals):3d} 点  "
              f"{ds[0]} ~ {ds[-1]}")

    if not series_by_key:
        print("\n✗ 未取到任何数据，未写入。")
        return

    # ---- 写入 ----
    with open(DATA_FILE, encoding="utf-8") as f:
        db = json.load(f)

    added, overwritten, skipped = 0, 0, 0
    for dk, vals in series_by_key.items():
        for d, p in vals.items():
            if d not in db["data"]:
                db["data"][d] = {}
            cur = db["data"][d].get(dk)
            if cur is None:
                db["data"][d][dk] = p
                added += 1
            elif args.refresh and abs(float(cur) - p) > 1e-9:
                db["data"][d][dk] = p
                overwritten += 1
            else:
                skipped += 1

    # 品种登记（幂等，保证前端常量对应的键都在）
    vlist = db.setdefault("varieties", [])
    dn = db.setdefault("display_names", {})
    meta = db.setdefault("meta", {})
    for dk, cfg in NEW_VARIETIES.items():
        if dk not in vlist:
            vlist.append(dk)
        dn[dk] = cfg["name"]
        meta.setdefault(dk, {"name": cfg["name"], "source": cfg["source"],
                             "cat": cfg["cat"]})

    dates = sorted(db["data"].keys())
    db["last_updated"] = dates[-1]
    db["total_days"] = len(dates)

    print("\n" + "-" * 78)
    print(f"新增 {added} 点｜覆盖 {overwritten} 点｜跳过（已有值）{skipped} 点"
          f"｜现共 {db['total_days']} 天")

    if args.dry_run:
        print("（--dry-run：未写入文件）")
        return

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)
    print(f"✓ 已写入 {DATA_FILE}")

    # ---- 回填后各品种覆盖度 ----
    print("-" * 78)
    print("回填后各品种覆盖（含原有）：")
    start_d = datetime.date.fromisoformat(args.start)
    span = [d for d in dates if d >= args.start]
    for dk in sorted(series_by_key):
        have = sum(1 for d in span if db["data"][d].get(dk) is not None)
        print(f"  {NEW_VARIETIES[dk]['name']:16s} {have:3d}/{len(span)} 天"
              f"   {rows_used.get(dk, '')}")


if __name__ == "__main__":
    main()
