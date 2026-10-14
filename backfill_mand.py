#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从精工历史存档 + 客户走势工作簿回填曼德（mand）看板历史数据。

## 为什么走这条路
曼德 7 项里，`1#白银`/`磷铜合金` 的历史需要 ccmn **会员登录**
（`POST /metalquote/query` 返回 `{"isLogin": false}`），`SMM A00铝`/`AlSi12(Fe)`
的历史需 SMM 会员态 cookie。而精工看板已连续运行多月，其 `docs/data.json`
本身就存有与曼德**同源同口径**的品种序列，可直接复用 —— 无需任何登录。

## 第一路：精工 docs/data.json（同源映射，已用 09-17 当日值交叉验证）
    CU       ← 精工 CU        同一 ccmn 长江现货「1#铜」
    AL_A380  ← 精工 A380      同一 SMM 页
    AL_ADC12 ← 精工 ADC12     同一 SMM 页

⚠️ 精工 `A00_AL` 是**长江有色** A00铝，曼德 `AL_A00` 要的是 **SMM** A00铝，
   口径不同，**不得回填**（同日同为 24180 属两个市场联动，非同一口径）。
   实测佐证：精工 A00_AL ↔ 曼德 AL_A00 在 14 天重叠里一致率仅 85.7%。

## 第二路：客户走势工作簿 B 列（2026-10-14 新增，回填 AL_A00）
源文件 `sources/橡胶/诺博橡胶大宗物料价格走势-2026.xlsx` 工作表「铝 -日」B 列，
覆盖 2020-04-07 ~ 2026-08-18（1495 天）。该列**不是**长江口径，而是 SMM 口径，
判定依据（三重独立交叉验证，2026-10-14 实测）：

  ① 与**精工主表** `2026年有色金属市场价格.xlsx` 工作表「上海有色A00铝」
     （独立来源，表名即明示上海有色口径）在 102 天重叠里一致 **99 天（97.1%）**；
  ② 与 `docs/plastic/data.json` 的 `AL_A00`（塑料看板，源标注 SMM 上海有色）
     在 1492 天重叠里一致 **1492 天（100%）**；
  ③ 与精工 `A00_AL`（长江）在 143 天重叠里一致仅 **127 天（88.8%）**、
     差值为 ±10~20 —— 正是 SMM 与长江两个相近但不同源的正常关系。
     反证：若工作簿 B 列是长江口径，则 ② 应表现为部分不一致、① 应接近 100%，
     实测恰好相反。

**运行时闸门**：回填前强制校验 ①（或退化用 ②）的匹配率 ≥ `MIN_AGREEMENT`，
不达标即**拒绝执行**并退出非零码 —— 防止未来工作簿被替换 / 列被改动后
静默写入口径不符的历史。

## 铁律
- 只回填上表品种，其余项一律不写入该日行（宁可缺，不编造）。
- **只补空缺，绝不覆盖**：与 mand 已有值冲突时保留原值，仅打印告警待人工核对。
- **不新增日期列**：只写 mand 日期底盘内已存在的日期（保持各品种列对齐）。
- 只写交易日（周末 / 法定节假日跳过）。
- 离群点（与相邻 ±10 点中位数偏离 >50%）判为录入错误，跳过并报告。

用法：
    python3 backfill_mand.py --dry-run   # 预演（含口径闸门），不落盘
    python3 backfill_mand.py             # 实际回填（自动备份）
"""

import argparse
import json
import shutil
import statistics
import sys
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

from jinggong_monitor.trading_calendar import is_trading_day

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "docs" / "data.json"           # 精工历史（源 1）
DST = ROOT / "docs" / "mand" / "data.json"  # 曼德看板（目标）

# ---- 第一路：精工键 → 曼德键；只有同源同口径才可映射
BACKFILL_MAP = {
    "CU":    "CU",        # ccmn 长江现货 1#铜
    "A380":  "AL_A380",   # SMM A380铝合金
    "ADC12": "AL_ADC12",  # SMM铝合金ADC12
}

# ---- 第二路：客户走势工作簿（SMM A00 口径，见模块 docstring 的三重验证）
XLSX_PATH = ROOT / "sources" / "橡胶" / "诺博橡胶大宗物料价格走势-2026.xlsx"
XLSX_SHEET, XLSX_COL, XLSX_CODE = "铝 -日", "B", "AL_A00"
XLSX_MIN_ROW = 23                     # 表头在第 22 行

# 口径闸门基准：精工主表 sheet（独立来源）优先，退化用塑料看板（同源但可查篡改）
GATE_SHEET_XLSX = ROOT / "2026年有色金属市场价格.xlsx"
GATE_SHEET_NAME, GATE_SHEET_COL = "上海有色A00铝", "B"
GATE_BOARD = ROOT / "docs" / "plastic" / "data.json"
GATE_BOARD_CODE = "AL_A00"
MIN_AGREEMENT = 0.95                  # 闸门：重叠区一致率下限
OUTLIER_RATIO, NEIGHBOURS = 0.50, 10  # 离群点：与相邻 ±10 点中位数偏离上限


def load_xlsx_col(path: Path, sheet: str, col: str,
                  min_row: int = 1) -> dict:
    """读取工作簿某列 → {iso_date: float}，非数值 / 汇总行自动跳过。"""
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb[sheet]
    ci = ord(col) - ord("A")
    out: dict = {}
    for row in ws.iter_rows(min_row=min_row, max_col=ci + 1, values_only=True):
        raw_d = row[0] if len(row) > 0 else None
        if raw_d is None:
            continue
        key = str(raw_d)[:10]
        if len(key) != 10 or key[4] != "-":
            continue
        v = row[ci] if ci < len(row) else None
        if v is None or isinstance(v, bool):
            continue
        try:
            f = float(str(v).replace(",", ""))
        except ValueError:
            continue
        if f > 0:
            out[key] = f
    return out


def gate_check(series: dict) -> bool:
    """口径闸门：工作簿列必须与独立基准高一致，否则拒绝回填。"""
    print("  口径闸门（工作簿 B 列 = SMM A00 铝？）")

    ref_label, ref = None, {}
    if GATE_SHEET_XLSX.exists():
        try:
            ref = load_xlsx_col(GATE_SHEET_XLSX, GATE_SHEET_NAME, GATE_SHEET_COL)
            ref_label = f"精工主表「{GATE_SHEET_NAME}」（独立来源）"
        except Exception as e:
            print(f"    · 主表基准不可用（{type(e).__name__}），退化用塑料看板")
    if not ref and GATE_BOARD.exists():
        ref = {k: v for k, v in
               ((d, (r or {}).get(GATE_BOARD_CODE))
                for d, r in json.loads(
                    GATE_BOARD.read_text(encoding="utf-8")).get("data", {}).items())
               if isinstance(v, (int, float))}
        ref_label = "塑料看板 AL_A00（同源，可查篡改）"

    if not ref:
        print("    ✗ 无可用基准 → 拒绝执行（宁可缺，不冒险）")
        return False

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
        print(f"    ✗ 与基准 {ref_label} 无重叠 → 拒绝执行")
        return False

    rate = same / ov
    ok = rate >= MIN_AGREEMENT
    print(f"    · 基准 {ref_label}：重叠 {ov} 天，一致 {same}（{rate*100:.1f}%）")
    for d in diffs[:5]:
        print(f"        异 {d[0]}  工作簿={d[1]}  基准={d[2]}")
    print(f"    {'✓ 通过' if ok else '✗ 不达标'}（阈值 {MIN_AGREEMENT*100:.0f}%）")
    return ok


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只预演打印，不写入")
    ap.add_argument("--from", dest="start", default=None, help="起始日期 YYYY-MM-DD（可选）")
    ap.add_argument("--no-xlsx", action="store_true", help="跳过工作簿回填（只走精工三键）")
    args = ap.parse_args()

    for p, why in ((SRC, "精工历史"), (DST, "曼德数据（请先跑 mand_update.py）")):
        if not p.exists():
            print(f"[FATAL] {why}不存在: {p}")
            return 1

    src = json.loads(SRC.read_text(encoding="utf-8")).get("data", {})
    doc = json.loads(DST.read_text(encoding="utf-8"))
    dst = doc.setdefault("data", {})
    board_dates = set(dst)

    src_dates = sorted(d for d in src if not args.start or d >= args.start)
    print("=== 曼德历史回填 ===")
    print(f"  第一路 源 : 精工 docs/data.json（{src_dates[0]} ~ {src_dates[-1]}，{len(src_dates)} 天）")
    print(f"  映射品种  : {{{', '.join(f'{k}→{v}' for k, v in BACKFILL_MAP.items())}}}")
    print(f"  目标已有  : {len(dst)} 天\n")

    added = {v: 0 for v in BACKFILL_MAP.values()}
    skipped = 0
    conflicts = []

    for d in src_dates:
        picked = {}
        for k_src, k_dst in BACKFILL_MAP.items():
            v = src.get(d, {}).get(k_src)
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
        if not row_dst:
            dst.pop(d, None)

    print("  第一路回填明细：")
    for code, n in added.items():
        print(f"    + {code:<10} 新增 {n:>3} 天")
    print(f"    = 已存在且一致      {skipped:>3} 条（跳过）")
    if conflicts:
        print(f"\n  ⚠️ 冲突 {len(conflicts)} 条（**保留曼德原值，未覆盖**，请人工核对）：")
        for d, code, cur, val in conflicts[:20]:
            print(f"      {d}  {code}: 曼德={cur}  精工={val}")

    # ---------------- 第二路：工作簿 B 列 → AL_A00 ----------------
    x_added = x_offcal = x_outlier = x_notinboard = x_skip = 0
    x_first = x_last = None
    x_outliers: list = []
    if not args.no_xlsx:
        print(f"\n  第二路 源 : {XLSX_PATH.name}「{XLSX_SHEET}」{XLSX_COL} 列 → {XLSX_CODE}")
        if not XLSX_PATH.exists():
            print("    ✗ 源文件不存在 → 跳过")
        else:
            series = load_xlsx_col(XLSX_PATH, XLSX_SHEET, XLSX_COL, XLSX_MIN_ROW)
            series = {k: v for k, v in series.items()
                      if (not args.start or k >= args.start) and k <= max(board_dates)}
            print(f"    候选点 {len(series)} 天（截取至曼德最新日 {max(board_dates)}）")

            if not gate_check(series):
                print("\n  ✗ 口径闸门未通过 → 拒绝回填工作簿源（整体退出）")
                return 2

            x_outliers = find_outliers(series)
            out_keys = {k for k, _, _ in x_outliers}
            fill = []
            for k, v in sorted(series.items()):
                if k in out_keys:
                    x_outlier += 1
                    continue
                if k not in board_dates:          # 不新增日期列
                    x_notinboard += 1
                    continue
                if not is_trading_day(date.fromisoformat(k)):
                    x_offcal += 1
                    continue
                row = dst.setdefault(k, {})
                cur = row.get(XLSX_CODE)
                if cur is None:
                    row[XLSX_CODE] = v
                    x_added += 1
                    fill.append(k)
                else:
                    x_skip += 1
            if fill:
                x_first, x_last = min(fill), max(fill)

            print("    回填明细：")
            print(f"      + {XLSX_CODE:<10} 新增 {x_added:>3} 天"
                  + (f"（{x_first} ~ {x_last}）" if x_first else ""))
            print(f"      = 已有值跳过      {x_skip:>3} 条")
            print(f"      · 非交易日跳过    {x_offcal:>3} 条 | 离群跳过 {x_outlier} 条"
                  f" | 底盘外跳过 {x_notinboard} 条")
            if x_outliers:
                for k, v, m in x_outliers[:10]:
                    print(f"      ⚠️ 离群 {k} 值={v:,.0f} 邻域中位数={m:,.0f}")

    dates = sorted(dst.keys())
    doc["total_days"] = len(dates)
    doc["last_updated"] = dates[-1] if dates else doc.get("last_updated")

    n_a00 = sum(1 for r in dst.values() if r.get("AL_A00") is not None)
    doc["backfill_note"] = (
        "历史（2026-01-05 起）回填来源："
        "CU / AL_A380 / AL_ADC12 三项 ← 精工同源存档（ccmn 长江铜 / SMM A380 / SMM ADC12）；"
        f"AL_A00（SMM A00铝，{n_a00} 天）← 客户物料价格走势工作簿「铝 -日」B 列，"
        "该列经精工主表「上海有色A00铝」sheet 与塑料看板 SMM 序列双重交叉验证为 SMM 口径"
        "（一致率 97.1% / 100%），非长江口径；"
        "AG、PCU（ccmn 历史需会员）、AL_ALSI12FE、AL_A360（SMM 历史需会员）"
        "无历史，按日留空；卓创 5 项自接入日起积累。"
    )

    print(f"\n  结果：{len(dates)} 天（{dates[0]} ~ {dates[-1]}）")
    for code in doc.get("varieties", []):
        n = sum(1 for r in dst.values() if r.get(code) is not None)
        print(f"    {code:<14} {n:>4} 天")
    empty = [c for c in doc.get("varieties", []) if not any(r.get(c) is not None for r in dst.values())]
    if empty:
        print(f"  仍全空品种（{len(empty)}）：{', '.join(empty)}")

    if args.dry_run:
        print("\n  （--dry-run，未落盘）")
        return 0

    bak_dir = ROOT / "backups" / "曼德"
    bak_dir.mkdir(parents=True, exist_ok=True)
    backup = bak_dir / f"data.json.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(DST, backup)
    DST.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"\n  → 已写入 {DST.relative_to(ROOT)}")
    print(f"  → 备份   {backup.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
