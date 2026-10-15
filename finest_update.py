#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""蜂巢汽车板块 大宗原材料价格采集 → docs/finest/data.json

品种（共 13 项：12 项已接入 + 1 项挂起占位）：
  长江有色网 2 项 + SMM 上海有色 5 项 + 卓创资讯 2 项 + 亚洲金属网 3 项 + PCI 1 项（挂起）

需求来源：客户提供的 `sources/finest/蜂巢大宗.xlsx`（18 行清单，去重后 12 个唯一品种）。
可行性分析见 `sources/finest/蜂巢大宗-品种抓取可行性分析.md`（2026-10-15 全链路实测）。

2026-10-15 主人拍板的四条口径：
  1. **单位按实际抓取口径**，不做隐式换算（见 SPEC 第 4 列；这是最易错点——
     若误按原表 F 列统一成 KG 换算，全部数值会错 1000 倍）；
  2. **巴斯夫 PA66（PCI）先空着** → status="paused" 占位行，看板显示挂起、不参与抓取；
  3. **频次统一每天**（原表 PA6/PA66 的「每天 vs 每季度」冲突、稀土「每季度」，
     均为亚洲金属网/卓创日更口径，取每天才有连续序列）；
  4. **数据源名称归一化**（「长江有色网」=「长江有色金属网」、「上海有色网」=
     「上海有色金属网」），看板统一显示简称。

口径复用说明（避免同名不同值）：
  · CU / AG 与曼德热系统看板**同源同口径**（长江有色网）；
  · PA6 / PA66 复用曼德已核定的**卓创品种编号**（43234 / 16980），跨看板数值可比；
  · PRND（镨钕）**与曼德不同源**——曼德走卓创编号 34618，本看板按蜂巢清单走
    亚洲金属网「镨钕混合金属 Pr 25%, Nd 75% 中国出厂」。两者口径与数值不同，
    跨看板引用时勿混用（已记入项目 MEMORY 的「同名不同源」陷阱表）。

铁律：抓不到一律留空，绝不编造 / 估算 / 沿用前值。
      当日未抓到的品种不会写入该日行，前端按缺失渲染。
      **日期不伪标**：卓创行的报价日期随行返回，非当日者按其真实日期归位
      （历史补位且不覆盖已发布值），避免把上一交易日的价写成当日价。

用法：
    python3 finest_update.py            # 采集当日并写入
    python3 finest_update.py --dry-run  # 只抓取并打印，不落盘
    python3 finest_update.py --push     # 采集写入后提交推送 GitHub Pages
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
OUT_PATH = SCRIPT_DIR / "docs" / "finest" / "data.json"

# 与精工/塑料/曼德共用同一交易日历（周末/法定节假日休市）
sys.path.insert(0, str(SCRIPT_DIR / "jinggong_monitor"))
from trading_calendar import is_trading_day, skip_reason  # noqa: E402
# 落盘安全层（2026-10-15 引入）：原子写 + 写前备份
from safe_io import atomic_write_json  # noqa: E402

# (code, 显示名, 数据源, 单位, 接入状态)
#  status: live=已接入 / paused=挂起占位 / pending=待接入 / blocked=无公开源
SPEC = [
    # ---- 长江有色金属网（与曼德同源同口径；替代蜂巢表里的「中国金属资讯网」——
    #      该站为安泰科运营的 JS 单页应用，仅公开价格指数、绝对价在会员栏目）----
    ("CU",          "铜（上海地区现货）", "长江有色网",     "元/吨",   "live"),
    ("AG",          "1#白银",             "长江有色网",     "元/千克", "live"),
    # ---- 上海有色网 SMM（AL_ 前缀沿用曼德命名，避免与精工主看板裸名 CU/ADC12 冲突）----
    ("AL_ADC12",    "SMM铝合金ADC12",     "SMM 上海有色",   "元/吨",   "live"),
    ("AL_A00",      "SMM A00铝",          "SMM 上海有色",   "元/吨",   "live"),
    ("AL_A380",     "A380铝合金",         "SMM 上海有色",   "元/吨",   "live"),
    ("AL_ALSI9CU3", "AlSi9Cu3铝合金",     "SMM 上海有色",   "元/吨",   "live"),
    ("CU_CATH1",    "CU-CATH-1（1#电解铜）", "SMM 上海有色", "元/吨",   "live"),
    # ---- 卓创资讯（复用曼德已核定编号：PA6 43234 / PA66 16980）----
    ("PA6",         "PA6",                "卓创资讯",       "元/吨",   "live"),
    ("PA66",        "PA66",               "卓创资讯",       "元/吨",   "live"),
    # ---- 亚洲金属网（蜂巢指定源；结构化 HTML 表格，非图片、无需 OCR）----
    ("PRND",        "镨钕混合金属",       "亚洲金属网",     "元/吨",   "live"),
    ("DYFE",        "镝铁 80%",           "亚洲金属网",     "元/公斤", "live"),
    ("TB",          "金属铽 99.9%",       "亚洲金属网",     "元/公斤", "live"),
    # ---- 挂起占位（2026-10-15 主人决定「先空着」）----
    ("BASF_PA66",   "巴斯夫 PA66",        "PCI (ChemOrbis)", "—",      "paused"),
]
# 注：「巴斯夫 PA66（PCI）」为 ChemOrbis 付费订阅数据，我方无账号；
#     卓创亦不收录巴斯夫 PA66（Ultramid）牌号（实测仅 PS/LDPE 等扬子巴斯夫产品），
#     故无法等价替代。此处保留挂起占位行以便后续接入，**不参与抓取、不显示数值**。
#     另：蜂巢表行 17（1#电解铜/中国金属资讯网）未单列——该源绝对价在会员栏目，
#     已由 ccmn 的 CU 与 SMM 的 CU_CATH1 双重覆盖，无需重复接入。

# 各源实际抓取的品种白名单
LIVE_CCMN = ("CU", "AG")
LIVE_SCI99 = ("PA6", "PA66")
LIVE_AM = ("PRND", "DYFE", "TB")

# SMM fetcher 内部命名的映射（精工主流程按自身 COL_MAP 取值，多余 key 自动忽略）
SMM_KEY_MAP = {
    "AL_A00":      "AL_A00",
    "ADC12":       "AL_ADC12",
    "A380":        "AL_A380",
    "AlSi9Cu3":    "AL_ALSI9CU3",
    "CU_CATH1":    "CU_CATH1",
}

# 卓创品种编号（2026-10-14 曼德已逐项核定，此处复用，不另立编号）
SCI99_TARGETS = (
    ("PA6",  43234, "PA6 · BL3280H · 华南 · 市场价", 1),
    ("PA66", 16980, "PA66 · EPR27 · 神马工程塑料 · 企业报价(出厂价)", 1),
)


def fetch_ccmn() -> dict:
    """长江有色网：铜 / 1#白银"""
    print("  [长江有色] 抓取 ...", end=" ", flush=True)
    try:
        from jinggong_monitor.fetcher_ccmn import CcmnFetcher
        raw = CcmnFetcher().fetch()
    except Exception as e:                                         # noqa: BLE001
        print(f"失败：{e}")
        return {}
    out = {c: raw[c] for c in LIVE_CCMN if raw.get(c) is not None}
    missing = [c for c in LIVE_CCMN if c not in out]
    print(f"{len(out)}/{len(LIVE_CCMN)}" + (f"  缺 {','.join(missing)}" if missing else ""))
    return out


async def fetch_smm() -> dict:
    """SMM 上海有色：A00铝 / ADC12 / A380 / AlSi9Cu3 / 1#电解铜"""
    print("  [SMM] 抓取 ...", end=" ", flush=True)
    try:
        from jinggong_monitor.fetcher_smm import _fetch_smm_raw
        # 4 个页面（aluminum / magnesium / alloy_chart / copper），超时给足 210s
        raw = await asyncio.wait_for(_fetch_smm_raw(), timeout=210)
    except asyncio.TimeoutError:
        print("超时（210s）")
        return {}
    except Exception as e:                                         # noqa: BLE001
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
    """卓创资讯：PA6 / PA66（按品种编号精确定位单行；返回值自带源报价日期）"""
    print("  [卓创] 抓取（2 个编号，登录态 Playwright）...")
    try:
        from jinggong_monitor.fetcher_sci99 import fetch_sci99_mand_sync
        raw = fetch_sci99_mand_sync(targets=SCI99_TARGETS)
    except Exception as e:                                         # noqa: BLE001
        print(f"     失败：{type(e).__name__}: {e}")
        return {}
    out = {c: v for c, v in raw.items() if c in LIVE_SCI99 and (v or {}).get("value")}
    missing = [c for c in LIVE_SCI99 if c not in out]
    print(f"     {len(out)}/{len(LIVE_SCI99)}"
          + (f"  缺 {','.join(missing)}" if missing else ""))
    return out


def fetch_asianmetal() -> dict:
    """亚洲金属网：镨钕混合金属 / 镝铁 / 金属铽（稀土价格走势页，HTML 表格）"""
    print("  [亚洲金属网] 抓取稀土 3 品种 ...", end=" ", flush=True)
    try:
        from jinggong_monitor.fetcher_asianmetal import fetch_rare_earth_sync
        raw = fetch_rare_earth_sync()
    except Exception as e:                                         # noqa: BLE001
        print(f"失败：{type(e).__name__}: {e}")
        return {}
    out = {c: v for c, v in raw.items() if c in LIVE_AM and v is not None}
    missing = [c for c in LIVE_AM if c not in out]
    print(f"{len(out)}/{len(LIVE_AM)}" + (f"  缺 {','.join(missing)}" if missing else ""))
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

    doc["source"] = "长江有色网 · SMM 上海有色 · 卓创资讯 · 亚洲金属网"
    doc["unit"] = "元/吨（1#白银 元/千克；镝铁、金属铽 元/公斤）"
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
    atomic_write_json(OUT_PATH, doc, indent=1, sort_keys=True,
                      backup=True, backup_dir=SCRIPT_DIR / "backups" / "蜂巢")
    return doc


def publish(success: bool) -> bool:
    """提交并推送 docs/finest/ 变更，触发 GitHub Pages 部署。"""
    if not success:
        print("\n  ⚠️  本次无有效数据，跳过推送（不推送空变更）")
        return False
    try:
        from git_helper import publish_to_github
    except Exception as e:                                         # noqa: BLE001
        print(f"\n  ❌ 加载 git_helper 失败：{e}")
        return False
    msg = f"finest: {datetime.now().strftime('%Y-%m-%d')} 蜂巢汽车大宗原材料价格更新"
    ok = publish_to_github(["docs/finest/data.json"], msg)
    print("  ✅ 已推送" if ok else "  ❌ 推送失败")
    return bool(ok)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只抓取打印，不写 data.json")
    ap.add_argument("--push", action="store_true", help="写入后提交推送 GitHub Pages")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    # ===== 周末及法定节假日跳过 =====
    today_d = dt.date.today()
    if not is_trading_day(today_d):
        print(f"⏸️  今日为{skip_reason(today_d)}（{today_d.isoformat()}），现货市场休市，跳过抓取。")
        return 0

    print("=== 蜂巢汽车大宗原材料采集 ===")

    prices: dict = {}
    prices.update(fetch_ccmn())
    prices.update(asyncio.run(fetch_smm()))
    prices.update(fetch_sci99())
    prices.update(fetch_asianmetal())

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
    print(f"\n  日期 {today}：抓到 {n_ok}/{n_live} 项")
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
        print(f"    [{mark}] {name:<20} {shown}{tail}")
    if not args.dry_run:
        print(f"\n  → {OUT_PATH.relative_to(SCRIPT_DIR)}")

    if args.push and not args.dry_run:
        publish(n_ok > 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
