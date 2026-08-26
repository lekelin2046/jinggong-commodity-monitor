#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_plastic.py — 塑料/橡塑 9 牌号每日增量更新
====================================================================
抓取 9 牌号最新市场参考价，追加到 docs/plastic/data.json。
- 某牌号当日无新价（未发布/非交易日）则跳过该牌号，不编造、不沿用前值（铁律）
- 幂等：若最新日期已存在则跳过，不会重复写
用法：python3 jinggong_monitor/daily_plastic.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetcher_21cp import (TARGETS, search_detail_ids, parse_detail,
                          match_brand, prefer_match, safe_get,
                          _parse_price_rows, DETAIL_URL)

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "docs", "plastic", "data.json")


def resolve_pid(keyword, brand_kw, prefer):
    pids = search_detail_ids(keyword)
    if not pids:
        return None
    cands = []
    for pid in pids:
        d = parse_detail(pid)
        if d:
            cands.append(d)
        time.sleep(0.8)
    brand_hits = [c for c in cands if match_brand(c, brand_kw)]
    pool = brand_hits if brand_hits else cands
    if not pool:
        return None
    picked = next((c for c in pool if prefer_match(c, prefer)), pool[0])
    return picked["pid"]


def main():
    if not os.path.exists(DATA_FILE):
        print(f"✗ 找不到 {DATA_FILE}，请先运行 backfill_plastic.py")
        sys.exit(1)
    with open(DATA_FILE, encoding="utf-8") as f:
        db = json.load(f)

    today = {}
    print("=" * 70)
    print("塑料/橡塑 9 牌号每日更新")
    print("=" * 70)
    for key, keyword, brand_kw, prefer, name in TARGETS:
        pid = resolve_pid(keyword, brand_kw, prefer)
        if not pid:
            print(f"  {name:16s} ✗ 未找到 pid")
            continue
        r = safe_get(DETAIL_URL.format(pid=pid))
        if not r:
            print(f"  {name:16s} ✗ 抓取失败（留空）")
            continue
        rows = _parse_price_rows(r.text)
        if not rows:
            print(f"  {name:16s} ✗ 无价格数据（留空）")
            continue
        d, p = rows[0]
        today[key] = (d, p)
        print(f"  {name:16s} {d}  {p:>6,} 元/吨")
        time.sleep(1.2)

    # 追加
    added_days = 0
    for key, (d, p) in today.items():
        if d not in db["data"]:
            db["data"][d] = {}
            added_days += 1
        if key not in db["data"][d]:
            db["data"][d][key] = p
    # 更新元信息
    dates = sorted(db["data"].keys())
    db["last_updated"] = dates[-1]
    db["total_days"] = len(dates)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)

    print("-" * 70)
    if added_days:
        print(f"✓ 已新增 {added_days} 个交易日数据 | 现共 {db['total_days']} 天 | 最新 {db['last_updated']}")
    else:
        print(f"· 无新交易日（最新已是 {db['last_updated']}），未追加")
    # 今日行情摘要
    print("-" * 70)
    print("今日行情：")
    for key, (d, p) in today.items():
        prev = None
        for dd in sorted(db["data"], reverse=True):
            if dd < d and key in db["data"][dd]:
                prev = db["data"][dd][key]
                break
        chg = (p - prev) / prev * 100 if prev else None
        if chg is not None:
            arrow = "▲" if chg > 0 else ("▼" if chg < 0 else "—")
            print(f"  {key:12s} {p:>6,} 元/吨  {arrow} {chg:+.2f}%")
        else:
            print(f"  {key:12s} {p:>6,} 元/吨  （无前值）")


if __name__ == "__main__":
    main()
