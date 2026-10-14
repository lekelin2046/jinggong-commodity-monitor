#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""曼德热系统大宗原材料价格采集 → docs/mand/data.json

品种分两类（共 14 项）：
  A 已接入（13） 长江有色网 3 项 + SMM 上海有色 5 项 + 卓创资讯 5 项
  B 已暂停（1） 巴斯夫PA66（PCI 订阅制，曼德 2026-10-14 明确「暂停」）

2026-10-14 依曼德逐项确认的口径完成「未接入品种」优化：
  · 镨钕金属  源由亚洲金属网改为**卓创资讯**（亚洲金属网价格栏为会员权限，无账号）
  · PA6 / PA66 由「只缺口径」转为已接入（按卓创品种编号精确定位唯一行）
  · PP-TD20 / PP-TD40 → 替换为源站实际可取的 **PP T30S / PP EP548R**
    （卓创价格库不收录改性牌号 TD20/TD40，检索 0 条）

铁律：抓不到一律留空，绝不编造 / 估算 / 沿用前值。
      当日未抓到的品种不会写入该日行，前端按缺失渲染。
      **日期不伪标**：卓创行的报价日期随行返回，非当日者按其真实日期归位
      （历史补位且不覆盖已发布值），避免把上一交易日的价写成当日价。

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
#  status: live=已接入 / pending=待接入 / blocked=无公开源 / paused=已暂停
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
    ("AL_A360",     "A360铝合金",         "SMM 上海有色", "元/吨",   "live"),
    # ---- 卓创资讯（2026-10-14 依曼德确认口径接入，按品种编号精确定位）----
    ("PRND",        "镨钕金属",           "卓创资讯",     "元/吨",   "live"),
    ("PA6",         "PA6",                "卓创资讯",     "元/吨",   "live"),
    ("PA66",        "PA66",               "卓创资讯",     "元/吨",   "live"),
    ("PP_T30S",     "PP T30S",            "卓创资讯",     "元/吨",   "live"),
    ("PP_EP548R",   "PP EP548R",          "卓创资讯",     "元/吨",   "live"),
    # ---- 已暂停：PCI 为订阅制付费数据，曼德 2026-10-14 明确「暂停」----
    ("PA66_BASF",   "巴斯夫PA66",         "PCI",          "元/吨",   "paused"),
]

LIVE_CCMN = ("CU", "AG", "PCU")
LIVE_SCI99 = ("PRND", "PA6", "PA66", "PP_T30S", "PP_EP548R")

# SMM fetcher 内部沿用精工命名（A380 / ADC12），曼德看板统一用 AL_ 前缀，此处做映射
SMM_KEY_MAP = {
    "AL_A00":      "AL_A00",
    "AL_ALSI12FE": "AL_ALSI12FE",
    "A360":        "AL_A360",
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
    """SMM 上海有色：A00铝 / A380 / ADC12 / AlSi12(Fe) / A360"""
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


def fetch_sci99() -> dict:
    """卓创资讯：镨钕金属 / PA6 / PA66 / PP T30S / PP EP548R

    按**品种编号**（SCI99_MAND_TARGETS）精确检索单行，口径唯一、不含歧义；
    返回项自带「源报价日期」，由 merge() 按真实日期归位。
    """
    print("  [卓创] 抓取（5 个编号，登录态 Playwright）...")
    try:
        from jinggong_monitor.fetcher_sci99 import fetch_sci99_mand_sync
        raw = fetch_sci99_mand_sync()
    except Exception as e:                                       # noqa: BLE001
        print(f"     失败：{type(e).__name__}: {e}")
        return {}
    out = {c: v for c, v in raw.items() if c in LIVE_SCI99 and (v or {}).get("value")}
    missing = [c for c in LIVE_SCI99 if c not in out]
    print(f"     {len(out)}/{len(LIVE_SCI99)}"
          + (f"  缺 {','.join(missing)}" if missing else ""))
    return out


def merge(prices: dict) -> dict:
    """把抓取结果合并进 data.json（保留历史，不覆盖他日）

    prices 的取值支持两种形态：
      · 数值                      → 视为**当日**取值
      · {"value": v, "date": d}   → 按**源报价日期** d 归位

    写入规则（守铁律，既不伪标日期、也不沿用前值）：
      · 源报价日期 == 今天 → 覆盖写（当日盘中源方可修订，允许刷新）
      · 源报价日期 <  今天 → 该键不存在才写（历史补位，不覆盖已发布值）
    """
    if OUT_PATH.exists():
        doc = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    else:
        doc = {}

    today = datetime.now().strftime("%Y-%m-%d")
    data = doc.setdefault("data", {})

    for code, raw in prices.items():
        if raw is None:
            continue
        if isinstance(raw, dict):
            val, src_date = raw.get("value"), raw.get("date") or today
        else:
            val, src_date = raw, today
        if val is None:
            continue                       # 未抓到 ⇒ 不写该键，绝不沿用前值
        row = data.setdefault(src_date, {})
        if src_date != today and code in row:
            continue                       # 历史补位：不覆盖已发布值
        row[code] = val

    doc["source"] = ("长江有色网 · SMM 上海有色 · 卓创资讯"
                     "（已暂停：PCI 巴斯夫PA66）")
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
    prices.update(fetch_sci99())

    today = datetime.now().strftime("%Y-%m-%d")

    if args.dry_run:
        tmp: dict = {}
        for code, raw in prices.items():
            if raw is None:
                continue
            val, d = ((raw.get("value"), raw.get("date") or today)
                      if isinstance(raw, dict) else (raw, today))
            if val is not None:
                tmp.setdefault(d, {})[code] = val
        doc = {"data": tmp}
        print("\n  （dry-run，未落盘）")
    else:
        doc = merge(prices)

    # 每项的“源报价日期”（用于展示与归位核对）
    src_dates = {}
    for code, raw in prices.items():
        if raw is None:
            continue
        src_dates[code] = (raw.get("date") if isinstance(raw, dict) else today) or today

    def _resolve(code):
        """本次落位：(值, 日期)；当日行优先，其次按源日期归位的补位值"""
        v = doc["data"].get(today, {}).get(code)
        if v is not None:
            return v, today
        d = src_dates.get(code)
        if d and d != today and code in doc["data"].get(d, {}):
            return doc["data"][d][code], d
        return None, None

    n_live = sum(1 for *_x, st in SPEC if st == "live")
    n_ok = sum(1 for code, *_x in SPEC if _resolve(code)[0] is not None)
    print(f"\n  日期 {today}：抓到 {n_ok} 项（live 共 {n_live} 项，另 1 项暂停）")
    for code, name, src, unit, st in SPEC:
        v, d = _resolve(code)
        if v is not None:
            mark, shown = "OK ", f"{v:>12,.2f}"
            tail = f"  {unit}"
            if d != today:
                tail += f"  ←源报价日 {d}（已按其真实日期归位，未伪标为今日）"
        elif st == "live":
            mark, shown, tail = "MISS", "         —", "  （当日未抓到 → 留空）"
        else:
            mark, shown, tail = "n/a", "         —", f"  （{st}）"
        print(f"    [{mark}] {name:<18} {shown}{tail}")
    if not args.dry_run:
        print(f"\n  → {OUT_PATH.relative_to(SCRIPT_DIR)}")

    if args.push and not args.dry_run:
        publish(n_ok > 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
