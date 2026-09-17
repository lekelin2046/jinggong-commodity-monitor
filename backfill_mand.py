#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从精工历史存档回填曼德（mand）看板历史数据。

## 为什么走这条路
曼德 7 项里，`1#白银`/`磷铜合金` 的历史需要 ccmn **会员登录**
（`POST /metalquote/query` 返回 `{"isLogin": false}`），`SMM A00铝`/`AlSi12(Fe)`
的历史需 SMM 会员态 cookie。而精工看板已连续运行多月，其 `docs/data.json`
本身就存有与曼德**同源同口径**的品种序列，可直接复用 —— 无需任何登录。

## 同源映射（已用 09-17 当日值交叉验证，三项完全一致）
    CU       ← 精工 CU        同一 ccmn 长江现货「1#铜」
    AL_A380  ← 精工 A380      同一 SMM 页
    AL_ADC12 ← 精工 ADC12     同一 SMM 页

⚠️ 精工 `A00_AL` 是**长江有色** A00铝，曼德 `AL_A00` 要的是 **SMM** A00铝，
   口径不同，**不得回填**（同日同为 24180 属两个市场联动，非同一口径）。

## 铁律
- **只回填上表 3 项**，其余 10 项一律不写入该日行（宁可缺，不编造）。
- 与 mand 已有值冲突时**不覆盖**，仅打印告警待人工核对。

用法：
    python3 backfill_mand.py --dry-run   # 预演，不落盘
    python3 backfill_mand.py             # 实际回填
"""

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "docs" / "data.json"          # 精工历史（源）
DST = ROOT / "docs" / "mand" / "data.json"  # 曼德看板（目标）

# 精工键 → 曼德键；只有同源同口径才可映射
BACKFILL_MAP = {
    "CU":    "CU",        # ccmn 长江现货 1#铜
    "A380":  "AL_A380",   # SMM A380铝合金
    "ADC12": "AL_ADC12",  # SMM铝合金ADC12
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只预演打印，不写入")
    ap.add_argument("--from", dest="start", default=None, help="起始日期 YYYY-MM-DD（可选）")
    args = ap.parse_args()

    if not SRC.exists():
        print(f"[FATAL] 精工历史不存在: {SRC}")
        return 1
    if not DST.exists():
        print(f"[FATAL] 曼德数据不存在: {DST}（请先跑 mand_update.py）")
        return 1

    src = json.loads(SRC.read_text(encoding="utf-8")).get("data", {})
    doc = json.loads(DST.read_text(encoding="utf-8"))
    dst = doc.setdefault("data", {})

    src_dates = sorted(d for d in src if not args.start or d >= args.start)
    print(f"=== 曼德历史回填（源：精工 docs/data.json）===")
    print(f"  源日期范围 : {src_dates[0]} ~ {src_dates[-1]}（{len(src_dates)} 天）")
    print(f"  映射品种   : {{{', '.join(f'{k}→{v}' for k, v in BACKFILL_MAP.items())}}}")
    print(f"  目标已有   : {len(dst)} 天\n")

    added = {v: 0 for v in BACKFILL_MAP.values()}
    skipped = 0
    conflicts = []

    for d in src_dates:
        row_src = src.get(d, {})
        picked = {}
        for k_src, k_dst in BACKFILL_MAP.items():
            v = row_src.get(k_src)
            if v is not None:
                picked[k_dst] = v
        if not picked:
            continue

        row_dst = dst.setdefault(d, {})
        for code, val in picked.items():
            cur = row_dst.get(code)
            if cur is None:
                row_dst[code] = val
                added[code] += 1
            elif abs(float(cur) - float(val)) > 1e-9:
                conflicts.append((d, code, cur, val))
            else:
                skipped += 1
        # 该日若三项都没取到值，清掉空 dict 以免污染
        if not row_dst:
            dst.pop(d, None)

    print("  回填明细：")
    for code, n in added.items():
        print(f"    + {code:<10} 新增 {n:>3} 天")
    print(f"    = 已存在且一致      {skipped:>3} 条（跳过）")
    if conflicts:
        print(f"\n  ⚠️ 冲突 {len(conflicts)} 条（**保留曼德原值，未覆盖**，请人工核对）：")
        for d, code, cur, val in conflicts[:20]:
            print(f"      {d}  {code}: 曼德={cur}  精工={val}")

    dates = sorted(dst.keys())
    doc["total_days"] = len(dates)
    # last_updated 保持为最新数据日（回填不改变"最新"，只补历史）
    doc["last_updated"] = dates[-1] if dates else doc.get("last_updated")
    doc.setdefault("backfill_note", (
        "历史（2026-01-05 起）中 CU / AL_A380 / AL_ADC12 三项回填自精工同源存档；"
        "AG、PCU（ccmn 历史需会员）、AL_A00、AL_ALSI12FE（SMM 历史需会员）无历史，按日留空。"
    ))

    print(f"\n  结果：{len(dates)} 天（{dates[0]} ~ {dates[-1]}）")
    empty = [c for c in doc.get("varieties", []) if not any(r.get(c) is not None for r in dst.values())]
    if empty:
        print(f"  仍全空品种（{len(empty)}）：{', '.join(empty)}")

    if args.dry_run:
        print("\n  （--dry-run，未落盘）")
        return 0

    backup = DST.with_suffix(f".json.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(DST, backup)
    DST.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"\n  → 已写入 {DST.relative_to(ROOT)}")
    print(f"  → 备份   {backup.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
