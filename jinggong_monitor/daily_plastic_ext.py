#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_plastic_ext.py — 塑料/橡塑看板「扩品类」每日增量更新（20 项）

与 daily_plastic.py 的分工
------------------------------------------------------------------
  daily_plastic.py      → 13 个塑料牌号（源：中塑在线 intl.21cp.com）
  daily_plastic_ext.py  → 20 个新品类（源：SMM / 百川盈孚 / 隆众资讯）  ← 本脚本

两者写同一个 docs/plastic/data.json，均为**按日期 merge**、幂等。
⚠️ 两个脚本不可同时运行（同一文件会互相覆盖）——定时任务须错开。

本脚本负责的 20 项（key 即 data.json 中的品种键）
------------------------------------------------------------------
  铝(4)      AL_A00 / AL_A380 / AL_ZLD104 / AL_ALSI9CU3        ← SMM
  化工(2)    C2_ETHYLENE / C3_PROPYLENE                        ← 隆众
  三元乙丙(3) EPDM_6950C / EPDM_3110M / EPDM_13561C             ← 隆众
  炭黑原料(1) CB_COALTAR                                        ← 百川盈孚
  炭黑(1)    CB_N550                                            ← 隆众
  天然橡胶(2) NR_SCRWF / NR_RSS3                                ← 隆众
  合成橡胶(2) BR9000 / SBR1712                                  ← 隆众
  防老剂(1)   AO_4020                                           ← 隆众
  促进剂(4)   ACC_DM / ACC_CZ / ACC_M / ACC_TMTD                ← 隆众

（原油按主人要求走精工现有路径，不纳入本看板。）

铁律
------------------------------------------------------------------
  · 某品种当日无新价 → 跳过该品种、留空，**绝不编造、绝不沿用前值**
  · 各源相互独立：一个源失败不影响其他源出数
  · 写入时使用**数据自身的日期**（非今天）——各源数据日可能相差一天

用法
------------------------------------------------------------------
    unset NODE_OPTIONS   # SMM 需 Playwright
    /Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/python \
        jinggong_monitor/daily_plastic_ext.py [--dry-run] [--only smm,bai,lz]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import logging
import os
import sys
from pathlib import Path

# ⚠️ 必须在 import playwright 之前清掉，否则 Chromium 启动失败
os.environ.pop("NODE_OPTIONS", None)

ROOT = Path(__file__).resolve().parent.parent
PKG = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from jinggong_monitor.trading_calendar import is_trading_day, skip_reason  # noqa: E402
from jinggong_monitor.fetcher_baiinfo import fetch_coal_tar               # noqa: E402
from jinggong_monitor.lz_price_center import (                            # noqa: E402
    fetch_daily as lz_fetch_daily, check_login as lz_check_login,
)

DATA_FILE = ROOT / "docs" / "plastic" / "data.json"

logger = logging.getLogger("jinggong.daily_plastic_ext")

# ---------------------------------------------------------------------------
# 新增品种登记表：data.json 键 → 元信息（前端常量须与此保持一致）
# ---------------------------------------------------------------------------
NEW_VARIETIES: dict[str, dict[str, str]] = {
    # ---- 铝（SMM）----
    "AL_A00":       {"name": "A00铝",          "unit": "元/吨", "source": "SMM 上海有色", "cat": "铝"},
    "AL_A380":      {"name": "A380铝合金",      "unit": "元/吨", "source": "SMM 上海有色", "cat": "铝"},
    "AL_ZLD104":    {"name": "ZLD104铝合金",    "unit": "元/吨", "source": "SMM 上海有色", "cat": "铝"},
    "AL_ALSI9CU3":  {"name": "AlSi9Cu3铝合金",  "unit": "元/吨", "source": "SMM 上海有色", "cat": "铝"},
    # ---- 化工（隆众）----
    "C2_ETHYLENE":  {"name": "乙烯",           "unit": "元/吨", "source": "隆众资讯", "cat": "化工"},
    "C3_PROPYLENE": {"name": "丙烯",           "unit": "元/吨", "source": "隆众资讯", "cat": "化工"},
    # ---- 三元乙丙橡胶（隆众·牌号级）----
    "EPDM_6950C":   {"name": "三元乙丙 6950C",  "unit": "元/吨", "source": "隆众资讯", "cat": "三元乙丙"},
    "EPDM_3110M":   {"name": "三元乙丙 3110M",  "unit": "元/吨", "source": "隆众资讯", "cat": "三元乙丙"},
    "EPDM_13561C":  {"name": "三元乙丙 13561C", "unit": "元/吨", "source": "隆众资讯", "cat": "三元乙丙"},
    # ---- 炭黑及原料 ----
    "CB_COALTAR":   {"name": "高温煤焦油",      "unit": "元/吨", "source": "百川盈孚", "cat": "炭黑"},
    "CB_N550":      {"name": "炭黑 N550",       "unit": "元/吨", "source": "隆众资讯", "cat": "炭黑"},
    # ---- 天然橡胶（隆众品种库中名为「干胶」）----
    "NR_SCRWF":     {"name": "天然橡胶 SCRWF",  "unit": "元/吨", "source": "隆众资讯", "cat": "天然橡胶"},
    "NR_RSS3":      {"name": "天然橡胶 RSS3",   "unit": "元/吨", "source": "隆众资讯", "cat": "天然橡胶"},
    # ---- 合成橡胶 ----
    "BR9000":       {"name": "顺丁橡胶 9000",   "unit": "元/吨", "source": "隆众资讯", "cat": "合成橡胶"},
    "SBR1712":      {"name": "丁苯橡胶 1712",   "unit": "元/吨", "source": "隆众资讯", "cat": "合成橡胶"},
    # ---- 橡胶助剂 ----
    "AO_4020":      {"name": "防老剂 4020",     "unit": "元/吨", "source": "隆众资讯", "cat": "橡胶助剂"},
    "ACC_DM":       {"name": "促进剂 DM",       "unit": "元/吨", "source": "隆众资讯", "cat": "橡胶助剂"},
    "ACC_CZ":       {"name": "促进剂 CZ",       "unit": "元/吨", "source": "隆众资讯", "cat": "橡胶助剂"},
    "ACC_M":        {"name": "促进剂 M",        "unit": "元/吨", "source": "隆众资讯", "cat": "橡胶助剂"},
    "ACC_TMTD":     {"name": "促进剂 TMTD",     "unit": "元/吨", "source": "隆众资讯", "cat": "橡胶助剂"},
}

# SMM 品种名 → data.json 键
SMM_KEY_MAP = {"A00": "AL_A00", "A380": "AL_A380",
               "ZLD104": "AL_ZLD104", "AlSi9Cu3": "AL_ALSI9CU3"}

# 隆众 VARIETY_MAP 键 → data.json 键
LZ_KEY_MAP = {
    "ETHYLENE": "C2_ETHYLENE", "PROPYLENE": "C3_PROPYLENE",
    "EPDM_6950C": "EPDM_6950C", "EPDM_3110M": "EPDM_3110M", "EPDM_13561C": "EPDM_13561C",
    "CARBON_BLACK_N550": "CB_N550",
    "NR_SCRWF": "NR_SCRWF", "NR_RSS3": "NR_RSS3",
    "BR9000": "BR9000", "SBR1712": "SBR1712",
    "ANTIOXIDANT_4020": "AO_4020",
    "ACCEL_DM": "ACC_DM", "ACCEL_CZ": "ACC_CZ",
    "ACCEL_M": "ACC_M", "ACCEL_TMTD": "ACC_TMTD",
}


# ---------------------------------------------------------------------------
def fetch_smm_aluminum() -> dict[str, float]:
    """SMM 铝 4 品种（复用 fetcher_smm 的 cookies + SSR 解析）"""
    from jinggong_monitor.fetcher_smm import _fetch_smm_raw, SMM_VARIETIES
    try:
        raw = asyncio.run(_fetch_smm_raw())
    except Exception as e:                        # noqa: BLE001
        logger.error("SMM 抓取异常：%s: %s", type(e).__name__, e)
        return {}
    out = {}
    for smm_key, dk in SMM_KEY_MAP.items():
        if smm_key in raw:
            out[dk] = raw[smm_key]
        else:
            logger.warning("SMM 未取到 %s（留空）", smm_key)
    return out


def fetch_lz() -> dict[str, tuple[str, float]]:
    """隆众 15 品种 → {data_key: (YYYY-MM-DD, price)}"""
    ok, msg = lz_check_login()
    print(f"  隆众登录态：{'✓' if ok else '✗'} {msg}")
    if not ok:
        logger.error("隆众登录态不可用，本轮全部留空")
        return {}
    out: dict[str, tuple[str, float]] = {}
    for lz_key, r in lz_fetch_daily().items():
        dk = LZ_KEY_MAP.get(lz_key)
        if not dk:
            continue
        if r["price"] is None or not r["date"]:
            logger.warning("隆众 %s 未取到价格（%s，留空）", r["name"], r["auth"] or "无值")
            continue
        out[dk] = (str(r["date"]).replace("/", "-"), float(r["price"]))
    return out


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="塑料看板扩品类每日更新（20 项）")
    ap.add_argument("--dry-run", action="store_true", help="只抓取不写文件")
    ap.add_argument("--refresh", action="store_true",
                    help="覆盖本脚本 20 项的已有值（口径调整后重算用；不影响 13 个塑料牌号）")
    ap.add_argument("--only", default="smm,bai,lz", help="只跑指定源，逗号分隔")
    args = ap.parse_args()
    sources = {s.strip() for s in args.only.split(",") if s.strip()}

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    today_d = datetime.date.today()
    print("=" * 74)
    print(f"塑料看板 · 扩品类每日更新（{len(NEW_VARIETIES)} 项）  {today_d.isoformat()}")
    print("=" * 74)

    if not is_trading_day(today_d):
        print(f"⏸️  今日为{skip_reason(today_d)}（{today_d.isoformat()}），现货市场休市，跳过抓取。")
        return

    if not DATA_FILE.exists():
        print(f"✗ 找不到 {DATA_FILE}，请先运行 daily_plastic.py / backfill_plastic.py")
        sys.exit(1)

    got: dict[str, tuple[str, float]] = {}          # data_key → (日期, 价格)

    # ---- 1. SMM 铝 ----
    if "smm" in sources:
        print("\n[1] SMM 上海有色 · 铝 4 品种")
        smm = fetch_smm_aluminum()
        for dk, v in smm.items():
            got[dk] = (today_d.isoformat(), v)
            print(f"    ✓ {NEW_VARIETIES[dk]['name']:18s} {v:>8,.0f} 元/吨")
        miss = [dk for dk in SMM_KEY_MAP.values() if dk not in smm]
        for dk in miss:
            print(f"    ✗ {NEW_VARIETIES[dk]['name']:18s} 未取到（留空）")

    # ---- 2. 百川盈孚 煤焦油 ----
    if "bai" in sources:
        print("\n[2] 百川盈孚 · 高温煤焦油")
        ct = fetch_coal_tar()
        if ct:
            got["CB_COALTAR"] = (ct["date"], ct["price"])
            chg = "" if ct["change"] is None else f"（{ct['change_word']}{abs(ct['change']):.0f}）"
            print(f"    ✓ {NEW_VARIETIES['CB_COALTAR']['name']:18s} {ct['price']:>8,.0f} 元/吨  {ct['date']} {chg}")
        else:
            print(f"    ✗ {NEW_VARIETIES['CB_COALTAR']['name']:18s} 未取到（留空）")

    # ---- 3. 隆众资讯 15 品种 ----
    if "lz" in sources:
        print("\n[3] 隆众资讯 · 化工/橡胶/助剂 15 品种")
        lz = fetch_lz()
        for dk, (d, p) in sorted(lz.items()):
            got[dk] = (d, p)
            print(f"    ✓ {NEW_VARIETIES[dk]['name']:18s} {p:>8,.0f} 元/吨  {d}")
        lz_all = {v for v in LZ_KEY_MAP.values()}
        for dk in sorted(lz_all - set(lz)):
            print(f"    ✗ {NEW_VARIETIES[dk]['name']:18s} 未取到（留空）")

    # ---- 汇总 ----
    print("\n" + "-" * 74)
    print(f"抓取结果：{len(got)}/{len(NEW_VARIETIES)} 项有值")

    if not got:
        print("✗ 本轮无任何数据，未写入。")
        return
    if args.dry_run:
        print("（--dry-run：未写入文件）")
        return

    # ---- 写入（按日期 merge，幂等）----
    with open(DATA_FILE, encoding="utf-8") as f:
        db = json.load(f)

    added_to_existing, new_days, overwritten = 0, 0, 0
    for dk, (d, p) in got.items():
        if d not in db["data"]:
            db["data"][d] = {}
            new_days += 1
        if dk not in db["data"][d]:
            db["data"][d][dk] = p
            added_to_existing += 1
        elif args.refresh:
            old = db["data"][d][dk]
            db["data"][d][dk] = p
            if abs(float(old) - p) > 1e-9:
                overwritten += 1
                print(f"    ↻ 覆盖 {NEW_VARIETIES[dk]['name']:18s} {old:>8,.0f} → {p:>8,.0f}（{d}）")

    # ---- 同步品种登记（幂等）----
    vlist = db.setdefault("varieties", [])
    dn = db.setdefault("display_names", {})
    meta = db.setdefault("meta", {})
    for dk, cfg in NEW_VARIETIES.items():
        if dk not in vlist:
            vlist.append(dk)
        dn[dk] = cfg["name"]
        meta[dk] = {"name": cfg["name"], "source": cfg["source"], "cat": cfg["cat"]}

    db["source"] = ("多源：中塑在线（塑料牌号）· SMM 上海有色（铝）· "
                    "百川盈孚（煤焦油）· 隆众资讯（化工/橡胶/助剂）")
    dates = sorted(db["data"].keys())
    db["last_updated"] = dates[-1]
    db["total_days"] = len(dates)

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)

    print(f"✓ 写入完成：本次新增 {added_to_existing} 个数据点"
          f"（新交易日 {new_days} 个，覆盖 {overwritten} 个）"
          f"| 现共 {db['total_days']} 天 | 最新 {db['last_updated']}")

    # ---- 与前一交易日对比 ----
    print("-" * 74)
    print("较前值涨跌：")
    for dk, (d, p) in sorted(got.items()):
        prev = None
        for dd in sorted(db["data"], reverse=True):
            if dd < d and dk in db["data"][dd]:
                prev = db["data"][dd][dk]
                break
        if prev:
            chg = (p - prev) / prev * 100
            arrow = "▲" if chg > 0 else ("▼" if chg < 0 else "—")
            print(f"  {NEW_VARIETIES[dk]['name']:18s} {p:>8,.0f}  {arrow} {chg:+.2f}%")
        else:
            print(f"  {NEW_VARIETIES[dk]['name']:18s} {p:>8,.0f}  （无前值）")


if __name__ == "__main__":
    main()
