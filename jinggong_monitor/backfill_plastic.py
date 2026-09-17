#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_plastic.py — 中塑在线塑料/橡塑牌号历史回填
====================================================================
逐交易日抓取中塑在线牌号历史，写入 docs/plastic/data.json（格式对齐精工看板）。

用法：
  python3 jinggong_monitor/backfill_plastic.py                      # 全量重建（TARGETS 全部牌号）
  python3 jinggong_monitor/backfill_plastic.py --only PP_K8003       # 增量：只回填指定牌号，合并进现有 data.json
        （新增牌号时用增量模式，避免全量重跑；多个 key 用逗号分隔）

⚠⚠ 危险：不带 --only 的「全量重建」会按 START 起算重建 varieties 并覆盖
   docs/plastic/data.json —— 该文件是 诺博橡胶页 /rubber/ 与 诺博内外饰页 /plastic/
   **共用**的数据文件，重建后将丢失：
     ① 隆众 15 项 2020-07-01 起的长历史（供「较XX年均价涨幅」使用）
     ② 桥接进来的 WTI 原油 / A380 / AlSi9Cu3（bridge_jinggong.py 写入）
     ③ 百川盈孚 高温煤焦油
   补救：重建后依次执行
     python3 -m jinggong_monitor.backfill_plastic_ext --from 2020-07-01
     python3 -m jinggong_monitor.bridge_jinggong --history
   日常更新请用 daily_plastic.py / daily_plastic_ext.py（按日期 merge，幂等，安全）。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetcher_21cp import (TARGETS, DISPLAY_NAMES, search_detail_ids,
                          parse_detail, match_brand, prefer_match,
                          safe_get, _parse_price_rows, DETAIL_URL)

# 中塑在线详情页是「滚动一年窗口」：翻到最老一页恰好是 T-1 年
# （2026-09-17 实测：13 个牌号最老页统一落在 2025-09-17 / p23~p25）
START = "2025-09-17"
MAX_PAGES = 36          # 一年约需 25 页（每页 10 条），留足余量
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
    """翻页抓历史，返回 [(date, price)] 新→旧，覆盖到 START 之前即停
    注：每页 10 条；回填满一年（约 245 个交易日）需 25 页，上限 MAX_PAGES"""
    rows_all = []
    for page in range(1, MAX_PAGES + 1):
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

    # --only KEY1,KEY2：增量模式，只回填指定牌号并合并进现有 data.json
    only_keys = None
    if "--only" in sys.argv:
        i = sys.argv.index("--only")
        if i + 1 >= len(sys.argv):
            print("用法：--only PP_K8003[,PP_XXXX]")
            sys.exit(1)
        only_keys = {k.strip() for k in sys.argv[i + 1].split(",") if k.strip()}
    targets = [t for t in TARGETS if only_keys is None or t[0] in only_keys]
    if only_keys and not targets:
        print(f"✗ --only 指定的 key 不在 TARGETS 中：{sorted(only_keys)}")
        sys.exit(1)

    if only_keys:
        if not os.path.exists(DATA_FILE):
            print(f"✗ 增量模式需先有 {DATA_FILE}，请先全量回填")
            sys.exit(1)
        with open(DATA_FILE, encoding="utf-8") as f:
            base = json.load(f)
        data = base.get("data", {})        # date -> {key: price}
        meta = base.get("meta", {})
        # ⚠️ 增量模式**必须继承**已有品种表：data.json 里除 13 个中塑牌号外
        #    还有扩品类 20 项（铝/隆众/百川），若用 TARGETS 重建会把它们抹掉
        base_varieties = list(base.get("varieties", []))
        base_names = dict(base.get("display_names", {}))
        print(f"○ 增量模式：基底 {len(data)} 天 / {len(base_varieties)} 品种，"
              f"本次仅回填 {[t[0] for t in targets]}")
    else:
        data = {}  # date -> {key: price}
        meta = {}
        base_varieties, base_names = [], {}

    print("=" * 70)
    print(f"中塑在线 {len(targets)} 牌号历史回填（起点 {START}）")
    print("=" * 70)
    for key, keyword, brand_kw, prefer, name in targets:
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
    # 品种表 = 既有（含扩品类 20 项）+ 本次回填的 13 个中塑牌号
    varieties = [v for v in base_varieties]
    for t in TARGETS:
        if t[0] not in varieties:
            varieties.append(t[0])
    display_names = {**base_names, **DISPLAY_NAMES}
    out = {
        "source": "中塑在线市场参考价（余姚中国塑料城，人民币含税现货，交易日日更）",
        "unit": "元/吨",
        "last_updated": max(data_sorted) if data_sorted else "",
        "total_days": len(data_sorted),
        "varieties": varieties,
        "display_names": display_names,
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
