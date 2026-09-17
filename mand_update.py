#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""曼德热系统大宗原材料价格采集 → docs/mand/data.json

品种分三类（共 13 项）：
  A 已接入（7） 长江有色网 3 项 + SMM 上海有色 4 项
  B 待接入（3） 镨钕金属（亚洲金属网）、PA6 / PA66（卓创资讯）
  C 无公开源（3）巴斯夫PA66（PCI 订阅制）、PP-TD20、PP-TD40（卓创未收录改性牌号）

铁律：抓不到一律留空，绝不编造 / 估算 / 沿用前值。
      当日未抓到的品种不会写入该日行，前端按缺失渲染。

用法：
    python3 mand_update.py            # 采集当日并写入
    python3 mand_update.py --dry-run  # 只抓取并打印，不落盘
    python3 mand_update.py --push     # 采集写入后提交推送 GitHub Pages
"""

import argparse
import asyncio
import datetime as dt
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OUT_PATH = SCRIPT_DIR / "docs" / "mand" / "data.json"

# 与精工/塑料共用同一交易日历（周末/法定节假日休市）
sys.path.insert(0, str(SCRIPT_DIR / "jinggong_monitor"))
from trading_calendar import is_trading_day, skip_reason  # noqa: E402

# (code, 显示名, 数据源, 单位, 接入状态)
#  status: live=已接入 / pending=待接入 / blocked=无公开源
SPEC = [
    # ---- 长江有色金属网 ----
    ("CU",          "铜（上海地区现货）", "长江有色网",   "元/吨",   "live"),
    ("AG",          "1#白银",             "长江有色网",   "元/千克", "live"),
    ("PCU",         "磷铜合金",           "长江有色网",   "元/吨",   "live"),
    # ---- 上海有色网 SMM ----
    ("AL_A00",      "SMM A00铝",          "SMM 上海有色", "元/吨",   "live"),
    ("AL_A380",     "A380铝合金",         "SMM 上海有色", "元/吨",   "live"),
    ("AL_ADC12",    "SMM铝合金ADC12",     "SMM 上海有色", "元/吨",   "live"),
    ("AL_ALSI12FE", "AlSi12(Fe)铝合金",   "SMM 上海有色", "元/吨",   "live"),
    # ---- 待接入 ----
    ("PRND",        "镨钕金属",           "亚洲金属网",   "元/吨",   "pending"),
    ("PA6",         "PA6",                "卓创资讯",     "元/吨",   "pending"),
    ("PA66",        "PA66",               "卓创资讯",     "元/吨",   "pending"),
    # ---- 无公开源，需换源或走采购口径 ----
    ("PA66_BASF",   "巴斯夫PA66",         "PCI",          "元/吨",   "blocked"),
    ("PP_TD20",     "PP-TD20",            "卓创资讯",     "元/吨",   "blocked"),
    ("PP_TD40",     "PP-TD40",            "卓创资讯",     "元/吨",   "blocked"),
]

LIVE_CCMN = ("CU", "AG", "PCU")

# SMM fetcher 内部沿用精工命名（A380 / ADC12），曼德看板统一用 AL_ 前缀，此处做映射
SMM_KEY_MAP = {
    "AL_A00":      "AL_A00",
    "AL_ALSI12FE": "AL_ALSI12FE",
    "A380":        "AL_A380",
    "ADC12":       "AL_ADC12",
}


def fetch_ccmn() -> dict:
    """长江有色网：铜 / 1#白银 / 磷铜合金"""
    print("  [长江有色] 抓取 ...", end=" ", flush=True)
    try:
        from jinggong_monitor.fetcher_ccmn import CcmnFetcher
        raw = CcmnFetcher().fetch()
    except Exception as e:
        print(f"失败：{e}")
        return {}
    out = {c: raw[c] for c in LIVE_CCMN if raw.get(c) is not None}
    missing = [c for c in LIVE_CCMN if c not in out]
    print(f"{len(out)}/{len(LIVE_CCMN)}" + (f"  缺 {','.join(missing)}" if missing else ""))
    return out


async def fetch_smm() -> dict:
    """SMM 上海有色：A00铝 / A380 / ADC12 / AlSi12(Fe)"""
    print("  [SMM] 抓取 ...", end=" ", flush=True)
    try:
        from jinggong_monitor.fetcher_smm import _fetch_smm_raw
        raw = await asyncio.wait_for(_fetch_smm_raw(), timeout=150)
    except asyncio.TimeoutError:
        print("超时（150s）")
        return {}
    except Exception as e:
        print(f"失败：{e}")
        return {}
    out = {}
    for src_key, code in SMM_KEY_MAP.items():
        if raw.get(src_key) is not None:
            out[code] = raw[src_key]
    missing = [c for c in SMM_KEY_MAP.values() if c not in out]
    print(f"{len(out)}/{len(SMM_KEY_MAP)}" + (f"  缺 {','.join(missing)}" if missing else ""))
    return out


def merge(prices: dict) -> dict:
    """把当日抓取结果合并进 data.json（保留历史，不覆盖他日）"""
    if OUT_PATH.exists():
        doc = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    else:
        doc = {}

    today = datetime.now().strftime("%Y-%m-%d")
    data = doc.setdefault("data", {})
    row = data.setdefault(today, {})

    # 只写抓到的值；未抓到的不写入该 key（前端按缺失处理），绝不沿用前值
    for code, val in prices.items():
        if val is not None:
            row[code] = val

    doc["source"] = "长江有色网 · SMM 上海有色（待接入：亚洲金属网 · 卓创资讯）"
    doc["unit"] = "元/吨（1#白银为 元/千克）"
    doc["last_updated"] = today
    doc["total_days"] = len(data)
    doc["varieties"] = [s[0] for s in SPEC]
    doc["display_names"] = {s[0]: s[1] for s in SPEC}
    doc["sources"] = {s[0]: s[2] for s in SPEC}
    doc["units"] = {s[0]: s[3] for s in SPEC}
    doc["status"] = {s[0]: s[4] for s in SPEC}
    doc["meta"] = {
        s[0]: {"name": s[1], "source": s[2], "unit": s[3], "status": s[4]}
        for s in SPEC
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )
    return doc


def publish(success: bool) -> bool:
    """提交并推送 docs/mand/ 变更，触发 GitHub Pages 部署。"""
    if not success:
        print("\n  ⚠️  本次无有效数据，跳过推送（不推送空变更）")
        return False
    try:
        from git_helper import publish_to_github
    except Exception as e:
        print(f"\n  ❌ 加载 git_helper 失败：{e}")
        return False
    msg = f"mand: {datetime.now().strftime('%Y-%m-%d')} 曼德热系统大宗原材料价格更新"
    ok = publish_to_github(["docs/mand/data.json"], msg)
    print("  ✅ 已推送" if ok else "  ❌ 推送失败")
    return bool(ok)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只抓取打印，不写 data.json")
    ap.add_argument("--push", action="store_true", help="写入后提交推送 GitHub Pages")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    # ===== 周末及法定节假日跳过 =====
    # 长江现货 / SMM 均为现货市场报价，周末与法定节假日休市，与精工主流程共用同一交易日历。
    today_d = dt.date.today()
    if not is_trading_day(today_d):
        print(f"⏸️  今日为{skip_reason(today_d)}（{today_d.isoformat()}），现货市场休市，跳过抓取。")
        return 0

    print("=== 曼德热系统大宗原材料采集 ===")

    prices: dict = {}
    prices.update(fetch_ccmn())
    prices.update(asyncio.run(fetch_smm()))

    if args.dry_run:
        doc = {"data": {datetime.now().strftime("%Y-%m-%d"): prices}}
        print("\n  （dry-run，未落盘）")
    else:
        doc = merge(prices)

    today = datetime.now().strftime("%Y-%m-%d")
    row = doc["data"].get(today, {})

    print(f"\n  日期 {today}：抓到 {len(row)}/{len(SPEC)} 项")
    for code, name, src, unit, st in SPEC:
        v = row.get(code)
        if v is not None:
            mark, shown = "OK ", f"{v:>12,.2f}"
        elif st == "live":
            mark, shown = "MISS", "         —"
        else:
            mark, shown = "n/a", "         —"
        print(f"    [{mark}] {name:<18} {shown}  {unit if v is not None else ''}")
    if not args.dry_run:
        print(f"\n  → {OUT_PATH.relative_to(SCRIPT_DIR)}")

    if args.push and not args.dry_run:
        got = sum(1 for code, *_ in SPEC if row.get(code) is not None)
        publish(got > 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
