#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_plastic.py — 中塑在线 9 个塑料/橡塑牌号历史回填
====================================================================
从 2026-06-01 起逐交易日抓取，生成 docs/plastic/data.json（格式对齐精工看板）。
用法：python3 jinggong_monitor/backfill_plastic.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetcher_21cp import (TARGETS, DISPLAY_NAMES, search_detail_ids,
                          parse_detail, match_brand, prefer_match,
                          safe_get, _parse_price_rows, DETAIL_URL)

START = "2026-06-01"
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


def fetch_history(pid):
    """翻页抓历史，返回 [(date, price)] 新→旧，覆盖到 START 之前即停"""
    rows_all = []
    for page in range(1, 10):
        if page == 1:
            url = DETAIL_URL.format(pid=pid)
        else:
            url = DETAIL_URL.format(pid=pid).replace("--.html", f"--{page}.html")
        r = safe_get(url)
        if not r:
            break
        rows = _parse_price_rows(r.text)
        if not rows:
            break
        rows_all.extend(rows)
        if rows[-1][0] < START:
            break
        time.sleep(1.2)
    return rows_all


def main():
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    data = {}  # date -> {key: price}
    meta = {}
    print("=" * 70)
    print(f"中塑在线 9 牌号历史回填（起点 {START}）")
    print("=" * 70)
    for key, keyword, brand_kw, prefer, name in TARGETS:
        print(f"\n▶ {name} ({key})")
        pid = resolve_pid(keyword, brand_kw, prefer)
        if not pid:
            print("    ✗ 未找到 pid")
            continue
        rows = fetch_history(pid)
        if not rows:
            print("    ✗ 无历史数据")
            continue
        seen = {}
        for d, p in rows:
            if d >= START and d not in seen:
                seen[d] = p
        print(f"    ✓ pid={pid} | 覆盖 {len(seen)} 个交易日 | "
              f"最新 {rows[0][0]} {rows[0][1]:,} | 最早 {rows[-1][0]}")
        for d, p in seen.items():
            data.setdefault(d, {})[key] = p
        meta[key] = {"name": name, "pid": pid}
        time.sleep(1.2)

    data_sorted = {d: data[d] for d in sorted(data)}
    out = {
        "source": "中塑在线市场参考价（余姚中国塑料城，人民币含税现货，交易日日更）",
        "unit": "元/吨",
        "last_updated": max(data_sorted) if data_sorted else "",
        "total_days": len(data_sorted),
        "varieties": [t[0] for t in TARGETS],
        "display_names": DISPLAY_NAMES,
        "meta": meta,
        "data": data_sorted,
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n" + "=" * 70)
    print(f"完成：{DATA_FILE}")
    print(f"  {len(data_sorted)} 个交易日 × {len(meta)} 个品种")
    print(f"  最新日期 {out['last_updated']}")


if __name__ == "__main__":
    main()
