#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回填蜂巢（finest）看板历史数据 —— 多源聚合。

背景
------------------------------------------------------------------
蜂巢看板 2026-10-15 首日上线，`docs/finest/data.json` 仅 1 天数据，
页面「月均环比」「年度对比」「下月预测」初期无值。
可行性实测见 `sources/蜂巢/蜂巢大宗-历史回填可行性.md`。
主人 2026-10-15 指令：**有多少先补多少**。

⚠️ 与 `backfill_mand.py` 的关键差异
------------------------------------------------------------------
曼德回填坚持「不新增日期列」（底盘已有 186 天，只在底盘内补）。
蜂巢底盘只有 **1 天**，照搬则什么都补不进去 —— 故本脚本**必须扩底盘**。
底盘定义：**回填各源实际出现过的日期的并集**（源本身只给交易日，
天然保真；不凭空铺满日历日，也不自行判定历史年份的节假日 ——
`trading_calendar.py` 目前仅收录 2026 年，对 2020~2025 会把春节等
误判为交易日，故不用于历史年份过滤）。

五条来源
------------------------------------------------------------------
1. **塑料看板** `docs/plastic/data.json` → AL_A00 / AL_A380 / AL_ALSI9CU3
   源标注「SMM 上海有色」，与蜂巢 SPEC 同源同口径；覆盖
   2020-04-07 ~ 最新（1500+ 天），且比客户工作簿更新（工作簿止于 2026-08-18）。
2. **精工** `docs/data.json` → CU（ccmn 长江 1#铜）/ ADC12 → AL_ADC12
3. **曼德** `docs/mand/data.json` → CU（与精工互校取并集）/ AG（1#白银，仅 14 天）
4. **客户工作簿** `sources/橡胶/诺博橡胶大宗物料价格走势-2026.xlsx`「铝 -日」
   B 列 —— 仅作 AL_A00 的独立基准。
5. **亚洲金属网曲线接口** → PRND / DYFE / TB（近 12 个月日度序列）

口径闸门（不达标一律拒绝落盘）
------------------------------------------------------------------
- AL_A380 / AL_ALSI9CU3：塑料看板 ↔ **精工同源序列**（独立抓取链路，
  实测各 186 天 **100%**）。
- AL_A00：塑料看板 ↔ 客户工作簿 B 列（外部独立文件，实测 1492 天 **100%**）。
  ⚠️ **不得**用精工 `A00_AL` 作基准 —— 那是**长江**口径，与 SMM 的 AL_A00
  不同源（实测一致率仅 88.5%，属预期差异；若误用会得出「不达标」的错误结论）。
- CU / AL_ADC12：精工 ↔ 曼德（两条独立链路）重叠一致率须 ≥ `MIN_AGREEMENT`。
- 稀土：曲线接口**末点**须等于蜂巢已发布当日值（口径连续性硬校验）。

🔴 工作簿 C / E 列不可作基准（2026-10-15 三方交叉实测）
------------------------------------------------------------------
工作簿「铝 -日」B 列（A00）完全可靠，但 **C 列(A380) / E 列(ALSI9Cu3) 与
塑料看板、精工三方对照存在系统性偏差**：

    AL_A380     : 工作簿↔塑料 99.60%（6 天差，工作簿略低）
    AL_ALSI9CU3 : 工作簿↔塑料 96.85%（47 天差，工作簿**系统性偏高** +250~+500）

第三方裁判（精工，独立抓取链路）：
    精工 A380      ↔ 塑料 AL_A380     186 天 100.0%   ← 塑料正确
    精工 A380      ↔ 工作簿 C 列      145 天  95.9%
    精工 AlSi9Cu3  ↔ 塑料 AL_ALSI9CU3 186 天 100.0%   ← 塑料正确
    精工 AlSi9Cu3  ↔ 工作簿 E 列      145 天 **67.6%** ← 工作簿该列有问题

逐日样例（2026-01-05 AlSi9Cu3）：塑料 23,900 = 精工 23,900 ≠ 工作簿 24,500。
→ 铝三项一律以**塑料看板**为数据源，工作簿仅用于 A00 一列做闸门。

铁律
------------------------------------------------------------------
- **只补空缺，绝不覆盖**：与蜂巢已有值冲突时保留原值，打印告警待人工核对。
- 抓不到就留空，绝不编造 / 估算 / 沿用前值。
- **稀土曲线按 PDate 截断至「回填日」**（接口名 Expectation，尾部含
  7/14/28 天**预测值**，实测止于未来日期 2026-10-22）。
- 离群点（与相邻 ±10 点中位数偏离 >50%）判为录入错误，跳过并报告。
- 不写未来日期；不写晚于看板最新日的日期。
- 落盘前自动备份到 `backups/蜂巢/`。

用法
------------------------------------------------------------------
    python3 backfill_finest.py --dry-run     # 预演（含闸门），不落盘
    python3 backfill_finest.py               # 实际回填（自动备份）
    python3 backfill_finest.py --no-am       # 跳过亚洲金属网曲线（免开浏览器）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import statistics
import sys
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent
DST = ROOT / "docs" / "finest" / "data.json"

SRC_PLASTIC = ROOT / "docs" / "plastic" / "data.json"
SRC_JINGGONG = ROOT / "docs" / "data.json"
SRC_MAND = ROOT / "docs" / "mand" / "data.json"

# 客户工作簿（仅作独立基准，见 docstring）
XLSX = ROOT / "sources" / "橡胶" / "诺博橡胶大宗物料价格走势-2026.xlsx"
XLSX_SHEET, XLSX_MIN_ROW = "铝 -日", 23
XLSX_COLS = {"B": "AL_A00", "C": "AL_A380", "E": "AL_ALSI9CU3"}

# 源 → 目标映射（只有同源同口径才可映射）
MAP_PLASTIC = {"AL_A00": "AL_A00", "AL_A380": "AL_A380", "AL_ALSI9CU3": "AL_ALSI9CU3"}
MAP_JINGGONG = {"CU": "CU", "ADC12": "AL_ADC12"}
MAP_MAND = {"CU": "CU", "AG": "AG"}

# 亚洲金属网曲线接口（详见 tools/probes/probe_am_chart_history.py）
AM_COOKIE = ROOT / "data" / "asianmetal_cookies.json"
AM_ENTRY = "https://www.asianmetal.cn/PraseodymiumPriceIndex"
AM_PPIDS = {"PRND": 526, "DYFE": 504, "TB": 532}   # 口径：中国出厂 + 人民币

MIN_AGREEMENT = 0.95                  # 闸门：重叠区一致率下限
OUTLIER_RATIO, NEIGHBOURS = 0.50, 10  # 离群点：与相邻 ±10 点中位数偏离上限

_AM_JS = r"""
async (ppids) => {
  const out = {};
  for (const id of ppids) {
    const r = await fetch('/price/priceChartExpectation.am', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest'},
      body: 'ppId=' + id + '&chartDate=4'          // 4 = 12 个月
    });
    const txt = await r.text();
    let arr = null;
    try { arr = eval(txt); } catch (e) { arr = null; }
    out[id] = Array.isArray(arr)
      ? arr.map(x => ({d: x.PDate, lo: x.PLNum, hi: x.PHNum, mid: x.PNum}))
      : null;
  }
  return out;
}
"""


# ==================== 基础工具 ====================

def norm_date(s) -> str | None:
    """把 datetime / '2021-3-29' / '2021/03/29' 统一成 ISO 日期串。"""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.date().isoformat()
    if isinstance(s, date):
        return s.isoformat()
    m = re.match(r"\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})", str(s))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except (ValueError, TypeError):
        return None


def load_board(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")).get("data", {})


def col_series(board: dict, code: str) -> dict:
    """从看板 data 抽出某品种 → {iso_date: float}。"""
    out = {}
    for d, row in board.items():
        v = (row or {}).get(code)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[d] = float(v)
    return out


def find_outliers(d: dict) -> list:
    """孤立离群点：与相邻 ±NEIGHBOURS 点中位数偏离 >OUTLIER_RATIO 者。"""
    keys = sorted(d)
    out = []
    for i, k in enumerate(keys):
        lo, hi = max(0, i - NEIGHBOURS), min(len(keys), i + NEIGHBOURS + 1)
        nb = [d[keys[j]] for j in range(lo, hi) if j != i]
        if len(nb) < 5:
            continue
        med = statistics.median(nb)
        if med > 0 and abs(d[k] - med) / med > OUTLIER_RATIO:
            out.append((k, d[k], med))
    return out


def gate(label: str, series: dict, ref: dict, ref_label: str) -> bool:
    """口径闸门：series 与独立基准 ref 的重叠一致率须 ≥ MIN_AGREEMENT。"""
    ov = same = 0
    diffs = []
    for k, v in series.items():
        r = ref.get(k)
        if r is None:
            continue
        ov += 1
        if abs(float(v) - float(r)) < 1e-6:
            same += 1
        else:
            diffs.append((k, v, r))
    if not ov:
        print(f"    ✗ {label}: 与基准「{ref_label}」无重叠 → 拒绝")
        return False
    rate = same / ov
    ok = rate >= MIN_AGREEMENT
    print(f"    {'✓' if ok else '✗'} {label:<14} ↔ {ref_label}："
          f"重叠 {ov:>4} 天，一致 {same:>4}（{rate*100:.1f}%）"
          f"{'' if ok else f'  ← 低于 {MIN_AGREEMENT*100:.0f}% 阈值'}")
    for d, x, y in diffs[:3]:
        print(f"        异 {d}  源={x:,.0f}  基准={y:,.0f}")
    return ok


def load_xlsx_cols(path: Path) -> dict:
    """读工作簿「铝 -日」B/C/E 列 → {code: {iso_date: float}}。"""
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb[XLSX_SHEET]
    out: dict = {code: {} for code in XLSX_COLS.values()}
    max_ci = max(ord(c) - 65 for c in XLSX_COLS)
    for row in ws.iter_rows(min_row=XLSX_MIN_ROW, max_col=max_ci + 1, values_only=True):
        d = norm_date(row[0] if row else None)
        if not d:
            continue
        for col, code in XLSX_COLS.items():
            ci = ord(col) - 65
            v = row[ci] if ci < len(row) else None
            if v is None or isinstance(v, bool):
                continue
            try:
                f = float(str(v).replace(",", ""))
            except (ValueError, TypeError):
                continue
            if f > 0:
                out[code][d] = f
    return out


# ==================== 亚洲金属网曲线 ====================

async def fetch_am_curves(cutoff: str) -> dict:
    """取稀土三品种 12 个月日度曲线，按 cutoff 截断预测值。

    返回值 {code: {iso_date: float}}；失败品种直接缺席（不编造）。
    """
    from playwright.async_api import async_playwright

    if not AM_COOKIE.exists():
        print(f"    ✗ 缺少 cookie：{AM_COOKIE} → 跳过稀土")
        return {}
    cks = json.loads(AM_COOKIE.read_text(encoding="utf-8"))
    out: dict = {}

    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await b.new_context(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"))
        await ctx.add_cookies(cks)
        pg = await ctx.new_page()
        await pg.goto(AM_ENTRY, wait_until="domcontentloaded", timeout=45000)
        await pg.wait_for_timeout(6000)

        raw = await pg.evaluate(_AM_JS, list(AM_PPIDS.values()))
        for code, ppid in AM_PPIDS.items():
            arr = raw.get(str(ppid))
            if not arr:
                print(f"    ✗ {code}(ppId={ppid}) 无返回")
                continue
            ser, n_future, n_null = {}, 0, 0
            for it in arr:
                d = norm_date(it.get("d"))
                if not d:
                    continue
                if d > cutoff:                     # 预测值：截断
                    n_future += 1
                    continue
                mid = it.get("mid")
                if mid in (None, "", 0):
                    lo, hi = it.get("lo"), it.get("hi")
                    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                        mid = (lo + hi) / 2
                if mid in (None, "", 0):
                    n_null += 1
                    continue
                ser[d] = float(mid)
            out[code] = ser
            print(f"    · {code:<8} ppId={ppid}  实得 {len(ser):>3} 点"
                  f"（截掉预测 {n_future} 点、空值 {n_null} 点）"
                  f"  {min(ser) if ser else '—'} ~ {max(ser) if ser else '—'}")
        await b.close()
    return out


# ==================== 主流程 ====================

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只预演打印，不写入")
    ap.add_argument("--from", dest="start", default=None, help="起始日期 YYYY-MM-DD（可选）")
    ap.add_argument("--no-am", action="store_true", help="跳过亚洲金属网稀土曲线")
    ap.add_argument("--allow-gate-fail", action="store_true",
                    help="闸门不达标时仍继续（默认拒绝，勿轻易使用）")
    args = ap.parse_args()

    if not DST.exists():
        print(f"[FATAL] 蜂巢数据不存在（请先跑 finest_update.py）：{DST}")
        return 1

    doc = json.loads(DST.read_text(encoding="utf-8"))
    data: dict = doc.setdefault("data", {})
    today = datetime.now().strftime("%Y-%m-%d")
    latest = max(data) if data else today
    cutoff = min(today, latest)          # 不写未来；不晚于看板最新日

    print("=== 蜂巢汽车历史回填 ===")
    print(f"  目标 {DST.relative_to(ROOT)}  现有 {len(data)} 天"
          f"（{min(data) if data else '—'} ~ {latest}）")
    print(f"  截止日 {cutoff}（不写未来、不晚于看板最新日）\n")

    sources: dict = {}          # code -> {date: value}
    gate_fail: list = []

    # 精工序列（既是数据源，也是铝三项的独立基准）
    jg = load_board(SRC_JINGGONG) if SRC_JINGGONG.exists() else {}
    # 客户工作簿（AL_A00 的独立基准；C/E 列不作为基准，见 docstring）
    try:
        wb_cols = load_xlsx_cols(XLSX)
        wb_label = f"{XLSX.name}「{XLSX_SHEET}」"
    except Exception as e:                                         # noqa: BLE001
        wb_cols, wb_label = {}, f"工作簿不可读({type(e).__name__})"
        print(f"  ! 基准工作簿不可用：{e}")

    # ---------- 源 1：塑料看板（SMM 铝三项）----------
    print("  ① 塑料看板 (SMM 上海有色) → 铝三项")
    # 基准选择：A380/AlSi9Cu3 → 精工（独立链路）；A00 → 工作簿 B 列
    BASE_JG = {"AL_A380": "A380", "AL_ALSI9CU3": "AlSi9Cu3"}
    WB_COL = {"AL_A00": "B", "AL_A380": "C", "AL_ALSI9CU3": "E"}
    if not SRC_PLASTIC.exists():
        print("    ✗ 塑料看板不存在 → 跳过铝三项")
    else:
        pl = load_board(SRC_PLASTIC)
        for code in MAP_PLASTIC.values():
            ser = {k: v for k, v in col_series(pl, code).items() if k <= cutoff}
            if not ser:
                print(f"    ✗ {code}: 塑料看板无该列 → 跳过")
                continue
            jk = BASE_JG.get(code)
            jref = col_series(jg, jk) if jk else {}
            if jref:
                ref, ref_label = jref, f"精工 {jk}（独立抓取链路）"
            elif wb_cols.get(code):
                ref = wb_cols[code]
                ref_label = f"{wb_label} {WB_COL.get(code, '?')} 列（外部独立文件）"
            else:
                ref, ref_label = {}, ""
            if ref:
                if not gate(code, ser, ref, ref_label):
                    gate_fail.append(code)
            else:
                print(f"    · {code:<14} 无可用独立基准 → 仅记录，不校验")
            sources[code] = ser
            print(f"      → {code:<14} 候选 {len(ser):>4} 天"
                  f"  {min(ser)} ~ {max(ser)}")

    # ---------- 源 2：精工（CU / AL_ADC12）----------
    print("\n  ② 精工 docs/data.json → CU / AL_ADC12")
    jg_ser = {}
    for k_s, k_d in MAP_JINGGONG.items():
        ser = {k: v for k, v in col_series(jg, k_s).items() if k <= cutoff}
        jg_ser[k_d] = ser
        if ser:
            print(f"    · {k_s:<8}→ {k_d:<10} 候选 {len(ser):>4} 天  {min(ser)} ~ {max(ser)}")

    # ---------- 源 3：曼德 ----------
    print("\n  ③ 曼德 docs/mand/data.json → CU（互校）/ AG")
    md = load_board(SRC_MAND) if SRC_MAND.exists() else {}
    md_ser = {k_d: {k: v for k, v in col_series(md, k_s).items() if k <= cutoff}
              for k_s, k_d in MAP_MAND.items()}

    # CU：两路互校后取并集
    if gate("CU", jg_ser.get("CU", {}), md_ser.get("CU", {}), "曼德同源序列"):
        merged = dict(md_ser.get("CU", {}))
        merged.update(jg_ser.get("CU", {}))       # 精工优先（更新到当日）
        sources["CU"] = merged
        print(f"      → CU 并集 {len(merged):>4} 天  {min(merged)} ~ {max(merged)}")
    else:
        gate_fail.append("CU")
        print("      ! CU 互校不达标 → 仍取并集，但已记入告警")
        merged = dict(md_ser.get("CU", {}))
        merged.update(jg_ser.get("CU", {}))
        sources["CU"] = merged

    # AL_ADC12：精工为源，曼德互校
    if jg_ser.get("AL_ADC12") and md_ser.get("CU") is not None:
        md_adc = col_series(md, "AL_ADC12")
        if md_adc:
            if not gate("AL_ADC12", jg_ser["AL_ADC12"], md_adc, "曼德同源序列"):
                gate_fail.append("AL_ADC12")
    if jg_ser.get("AL_ADC12"):
        sources["AL_ADC12"] = jg_ser["AL_ADC12"]
        s = jg_ser["AL_ADC12"]
        print(f"      → AL_ADC12  {len(s):>4} 天  {min(s)} ~ {max(s)}")

    # AG：仅曼德一路，无独立基准
    if md_ser.get("AG"):
        sources["AG"] = md_ser["AG"]
        s = md_ser["AG"]
        print(f"      → AG（无独立基准，仅此一路）  {len(s)} 天  {min(s)} ~ {max(s)}")

    # ---------- 源 4：亚洲金属网曲线（稀土）----------
    if args.no_am:
        print("\n  ④ 亚洲金属网稀土曲线 —— 已按 --no-am 跳过")
    else:
        print("\n  ④ 亚洲金属网 priceChartExpectation.am → 稀土三项")
        try:
            am = asyncio.run(fetch_am_curves(cutoff))
        except Exception as e:                                     # noqa: BLE001
            print(f"    ✗ 失败：{type(e).__name__}: {e}")
            am = {}
        # 口径连续性硬校验：曲线末点应等于蜂巢已发布当日值
        pub = data.get(cutoff, {}) or data.get(latest, {}) or {}
        for code, ser in am.items():
            if not ser:
                continue
            last_d = max(ser)
            pv = pub.get(code)
            if pv is not None:
                dm = float(pv) - ser[last_d]
                flag = "✓" if abs(dm) < 1e-6 else f"⚠️ 差 {dm:+,.0f}"
                print(f"    · {code:<6} 曲线末点 {last_d}={ser[last_d]:,.0f}"
                      f"  vs 已发布 {cutoff}={float(pv):,.0f}  {flag}")
                if abs(dm) > 1e-6:
                    gate_fail.append(f"{code}(末点≠发布值)")
            sources[code] = ser

    # ---------- 汇总写入 ----------
    print("\n  ───────── 汇总 ─────────")
    added = {c: 0 for c in sources}
    skipped = 0
    conflicts = []
    outlier_report = []

    for code, ser in sources.items():
        outliers = find_outliers(ser)
        out_keys = {k for k, _, _ in outliers}
        if outliers:
            outlier_report.append((code, outliers))
        for d in sorted(ser):
            if args.start and d < args.start:
                continue
            if d in out_keys:
                continue
            row = data.setdefault(d, {})
            cur = row.get(code)
            if cur is None:
                row[code] = ser[d]
                added[code] += 1
            elif abs(float(cur) - float(ser[d])) > 1e-9:
                conflicts.append((d, code, cur, ser[d]))
            else:
                skipped += 1

    # 清掉回填过程中产生的空行（保留原有行）
    for d in [k for k, v in data.items() if not v]:
        data.pop(d, None)

    for code in sorted(added):
        n = sum(1 for r in data.values() if r.get(code) is not None)
        print(f"    + {code:<14} 新增 {added[code]:>5} 天   合计 {n:>5} 天")
    print(f"    = 已存在且一致            {skipped:>5} 条（跳过）")

    if conflicts:
        print(f"\n  ⚠️ 冲突 {len(conflicts)} 条（**保留蜂巢原值，未覆盖**）：")
        for d, code, cur, val in conflicts[:15]:
            print(f"      {d}  {code}: 蜂巢={cur:,.0f}  回填源={val:,.0f}")
    for code, outs in outlier_report:
        print(f"\n  ⚠️ {code} 离群点 {len(outs)} 个（已跳过）：")
        for k, v, m in outs[:8]:
            print(f"      {k}  值={v:,.0f}  邻域中位数={m:,.0f}")

    if gate_fail:
        print(f"\n  🔴 闸门告警：{', '.join(gate_fail)}")
        if not args.allow_gate_fail:
            print("  → 默认拒绝落盘（如确认无误可加 --allow-gate-fail）")
            return 2

    dates = sorted(data)
    doc["total_days"] = len(dates)
    doc["last_updated"] = max(latest, today) if data else latest

    n = {c: sum(1 for r in data.values() if r.get(c) is not None)
         for c in doc.get("varieties", [])}
    doc["backfill_note"] = (
        f"历史回填（2026-10-15 执行，主人指令「有多少先补多少」）："
        f"AL_A00/AL_A380/AL_ALSI9CU3（SMM 上海有色，{n.get('AL_A00')}/"
        f"{n.get('AL_A380')}/{n.get('AL_ALSI9CU3')} 天，2020-04-07 起）← 塑料看板同源序列；"
        f"闸门：AL_A00 ↔ 客户工作簿「铝 -日」B 列（1492 天 100%），"
        f"AL_A380 / AL_ALSI9CU3 ↔ 精工同源序列（各 186 天 100%）。"
        f"⚠️ 工作簿 C/E 列经三方交叉实测与塑料/精工存在系统性偏差（ALSI9Cu3 仅 67.6%），"
        f"故仅 B 列可作基准，铝数据一律取自塑料看板。"
        f"PRND/DYFE/TB（{n.get('PRND')} 天，近 12 个月）← 亚洲金属网 "
        f"priceChartExpectation.am 曲线接口（已按 PDate 截断尾部 7 天预测值；"
        f"末点与当日现抓值逐项相符）。"
        f"CU（{n.get('CU')} 天）← 精工/曼德同源序列互校取并集（184 天 100%）；"
        f"AL_ADC12（{n.get('AL_ADC12')} 天）← 精工同源（186 天 100%）；"
        f"AG（{n.get('AG')} 天）← 曼德同源（仅此一路，无独立基准）。"
        f"无历史（自 2026-10-15 起积累）：CU_CATH1（SMM 历史属付费专站 price.smm.cn）、"
        f"PA6/PA66（卓创历史接口 isLogin:0，需登录态）、BASF_PA66（无账号）。"
        f"另有 AL_A00 在 2026-08-19 ~ 2026-09-16 共 25 天及 02-09、06-22~26 共 27 天"
        f"（塑料看板该列断供）无任何源可补，按铁律如实留空。"
    )

    print(f"\n  结果：{len(dates)} 天（{dates[0]} ~ {dates[-1]}）")
    for code in doc.get("varieties", []):
        print(f"    {code:<14} {n.get(code, 0):>5} 天")

    if args.dry_run:
        print("\n  （--dry-run，未落盘）")
        return 0

    bak_dir = ROOT / "backups" / "蜂巢"
    bak_dir.mkdir(parents=True, exist_ok=True)
    bak = bak_dir / f"data.json.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(DST, bak)
    DST.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
                   encoding="utf-8")
    size_kb = DST.stat().st_size / 1024
    print(f"\n  → 已写入 {DST.relative_to(ROOT)}（{size_kb:.1f} KB）")
    print(f"  → 备份   {bak.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
