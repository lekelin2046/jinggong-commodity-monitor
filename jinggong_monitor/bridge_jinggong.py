#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bridge_jinggong.py — 精工板块 → 诺博看板 的数据接续
====================================================================
把精工看板（`docs/data.json`）里**同源同口径**的序列接进诺博看板
（`docs/plastic/data.json`），避免重复抓取、避免口径漂移。

为什么需要它
------------------------------------------------------------------
诺博看板监控清单里有 **原油**，但原油的抓取在精工板块（ccmn/SMM 之外的
akshare 那条线）——主人在 2026-09-17 明确「原油用精工那个原油就可以了」。
另，SMM 铝的**历史**在源站是付费内容，而精工看板里有同样来自 SMM 的
A380 / AlSi9Cu3 序列（实测 2026-09-17 两板块取值完全一致：26250 / 25250），
可借来补齐诺博的季/月涨跌幅。

口径红线
------------------------------------------------------------------
  · 只接**同源同口径**的序列。已核实的映射见 BRIDGE / HISTORY_BRIDGE。
  · **A00 不借**：精工用的是 ccmn 长江现货、诺博用的是 SMM，出版方不同，
    尽管 2026-09-17 两值恰好相同（24180），仍不混用（只用 1 个重叠日无法
    证明历史等价）。
  · **不使用 akshare 的 WTI 历史**：那是**收盘价**，精工用的是 **15:00 实时价**，
    混进同一条序列会造出假跳变。
  · 默认**不覆盖**已有值（幂等）；只在诺博侧为空时写入。

用法
------------------------------------------------------------------
    # 每日（由 daily_plastic_ext.py 末尾自动调用）：只补当日
    python3 -m jinggong_monitor.bridge_jinggong

    # 一次性历史补齐（借 SMM 铝的历史）
    python3 -m jinggong_monitor.bridge_jinggong --history
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JINGGONG_FILE = ROOT / "docs" / "data.json"
NOBO_FILE = ROOT / "docs" / "plastic" / "data.json"

logger = logging.getLogger("jinggong.bridge")

# 每日接续：诺博键 -> 精工键。同源同口径，值完全一致。
BRIDGE: dict[str, str] = {
    "OIL_WTI": "WTI",
}

# 仅历史借道（一次性）：SMM 铝历史在源站付费，精工侧有同源序列
HISTORY_BRIDGE: dict[str, str] = {
    "AL_A380": "A380",
    "AL_ALSI9CU3": "AlSi9Cu3",
}

# 新品种登记（写进 varieties / display_names / meta）
META: dict[str, dict[str, str]] = {
    "OIL_WTI": {"name": "WTI 原油", "source": "akshare（同精工板块）",
                "cat": "原油", "unit": "美元/桶"},
}


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sync(history: bool = False, refresh: bool = False,
         dry_run: bool = False) -> int:
    """返回写入的数据点数。"""
    if not JINGGONG_FILE.exists() or not NOBO_FILE.exists():
        logger.error("数据文件缺失：%s / %s", JINGGONG_FILE, NOBO_FILE)
        return 0

    jg = _load(JINGGONG_FILE)
    nb = _load(NOBO_FILE)
    jg_data = jg.get("data", {})
    nb_data = nb.setdefault("data", {})

    mapping = dict(BRIDGE)
    if history:
        mapping.update(HISTORY_BRIDGE)

    written = 0
    report: list[str] = []
    for nb_key, jg_key in mapping.items():
        src = {d: v for d, v in ((dt, (row or {}).get(jg_key))
                                 for dt, row in jg_data.items()) if v is not None}
        if not src:
            report.append(f"  ✗ {nb_key:14s} 精工侧无 {jg_key} 序列")
            continue
        added = 0
        for d, p in src.items():
            row = nb_data.setdefault(d, {})
            cur = row.get(nb_key)
            if cur is None:
                row[nb_key] = p
                added += 1
            elif refresh and abs(float(cur) - float(p)) > 1e-9:
                row[nb_key] = p
                added += 1
        written += added
        ds = sorted(src)
        report.append(f"  ✓ {nb_key:14s} ← 精工 {jg_key:12s} 源 {len(src):3d} 点"
                      f"（新增 {added:3d}）{ds[0]} ~ {ds[-1]}")

    # 品种登记
    vlist = nb.setdefault("varieties", [])
    dn = nb.setdefault("display_names", {})
    meta = nb.setdefault("meta", {})
    for key, cfg in META.items():
        if key in mapping:
            if key not in vlist:
                vlist.append(key)
            dn[key] = cfg["name"]
            meta.setdefault(key, dict(cfg))

    print("精工 → 诺博 接续" + ("（含历史借道）" if history else "（仅当日）"))
    print("\n".join(report))
    print(f"合计写入 {written} 点")

    if dry_run:
        print("（--dry-run：未写入文件）")
        return written

    dates = sorted(nb_data)
    nb["last_updated"] = dates[-1]
    nb["total_days"] = len(dates)
    with open(NOBO_FILE, "w", encoding="utf-8") as f:
        json.dump(nb, f, ensure_ascii=False, indent=1)
    print(f"✓ 已写入 {NOBO_FILE}")
    return written


def main():
    ap = argparse.ArgumentParser(description="精工 → 诺博 看板数据接续")
    ap.add_argument("--history", action="store_true",
                    help="一次性历史借道（同源同口径的 SMM 铝）")
    ap.add_argument("--refresh", action="store_true", help="覆盖已有值")
    ap.add_argument("--dry-run", action="store_true", help="只算不写")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    sync(history=args.history, refresh=args.refresh, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
