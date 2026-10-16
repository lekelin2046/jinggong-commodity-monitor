#!/usr/bin/env python3
"""
只读探针：验证「抓取结果直接写 data.json」与现有「Excel → 导出」是否等价

做法
----
把 Excel「日均价（2026年市场）」**每一行**的值，当作「假如当初抓取结果直接落库」
会得到的东西（两者本来就是同一批数字：抓取 → 写 Excel 行 → 导出），
再用 jinggong_monitor.direct_json 构造日期行，与生产 docs/data.json 逐日逐品种比对。

为什么要现在跑
--------------
每天等 15:00 抓取后做影子比对，只能一天验一天；本探针一次性覆盖**全部历史**，
立即回答「废弃 Excel 中转后，看板数据会不会变」这个问题。

同时它会暴露两类隐患：
  1. 同一日期出现多行（export_excel_to_json.py 有「保留填充最多行」的去重逻辑，
     源于 2026-09-08 事故）—— 本探针不做去重，差异会显形；
  2. Excel 行里存在、但生产 data.json 里没有的值 —— 即「导出链路丢了数」。

口径
----
与 export_excel_to_json.py 保持一致：`data_only=True`（读公式计算结果，非公式文本）、
空值/占位符（空串、——、-、—）视为无值、数值统一 float。

只读。不写 docs/ 下任何文件；报告落 output/（gitignore）。
用法: python3 tools/probe_direct_json.py
"""

import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import openpyxl  # noqa: E402

from daily_update_all import COL_MAP, EXCEL_PATH, SHEET_NAME  # noqa: E402
from jinggong_monitor.trading_calendar import (  # noqa: E402
    is_trading_day, skip_reason,
)
from jinggong_monitor.direct_json import (  # noqa: E402
    build_day_record, codes_of, diff_records, append_report,
)

PROD_PATH = ROOT / "docs" / "data.json"
REPORT_PATH = ROOT / "output" / "direct_json_history_compare.jsonl"
PLACEHOLDERS = ("", "——", "-", "—")


def _norm_cell(v):
    """单元格 → float 或 None（与 export_excel_to_json.parse_value 同口径）。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if s in PLACEHOLDERS:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _norm_date(v):
    """A 列 → 'YYYY-MM-DD' 或 None（仅接受 2026 年，与导出脚本一致）。"""
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%d") if v.year == 2026 else None
    if isinstance(v, str):
        s = v.strip()
        if not s or s.startswith("备注"):
            return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
            try:
                d = datetime.datetime.strptime(s, fmt)
                return d.strftime("%Y-%m-%d") if d.year == 2026 else None
            except ValueError:
                continue
    return None


def read_excel_rows():
    """→ [(日期, 行记录, Excel 行号)]，按 Excel 物理顺序（可能含重复日期）。"""
    wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)
    ws = wb[SHEET_NAME]
    codes = codes_of(COL_MAP)
    out = []
    for r in range(2, ws.max_row + 1):
        ds = _norm_date(ws.cell(r, 1).value)
        if ds is None:
            continue
        prices = {}
        for col, spec in COL_MAP.items():
            code = spec[0] if isinstance(spec, (tuple, list)) else spec
            val = _norm_cell(ws.cell(r, col).value)
            if val is not None:
                prices[code] = val
        out.append((ds, build_day_record(prices, codes), r))
    return out


def main():
    prod = json.loads(PROD_PATH.read_text(encoding="utf-8"))
    prod_data = prod.get("data") or {}
    codes = codes_of(COL_MAP)
    rows = read_excel_rows()

    print("=" * 62)
    print("  「直接写 JSON」等价性探针（只读）")
    print("=" * 62)
    print(f"  Excel 日期行 : {len(rows)} 行")
    print(f"  生产 data.json: {len(prod_data)} 天 × {len(codes)} 品种")
    print()

    # ① 重复日期检测
    by_date = {}
    dups = []
    for ds, rec, r in rows:
        if ds in by_date:
            dups.append((ds, by_date[ds][1], r))
            if len(rec) > len(by_date[ds][0]):
                by_date[ds] = (rec, r)
        else:
            by_date[ds] = (rec, r)
    print(f"① Excel 重复日期行: {len(dups)} 组")
    for ds, r1, r2 in dups[:10]:
        print(f"     {ds}: 行 {r1} 与行 {r2}")
    if len(dups) > 10:
        print(f"     …另 {len(dups) - 10} 组")
    print()

    # ② 逐日比对（取填充最多的一行，模拟导出去重口径）
    only_in_prod, only_in_excel, mismatch, matched = [], [], [], []
    for ds, (rec, _r) in sorted(by_date.items()):
        prod_row = prod_data.get(ds)
        if prod_row is None:
            only_in_excel.append((ds, len(rec)))
            continue
        diffs = diff_records(rec, prod_row, codes)
        if not diffs:
            matched.append(ds)
        else:
            for d in diffs:
                if d["kind"] == "loss":
                    only_in_excel.append(f"{ds}:{d['code']}")
                elif d["kind"] == "manual":
                    only_in_prod.append(f"{ds}:{d['code']}={d['prod']}")
                else:
                    mismatch.append(f"{ds}:{d['code']} excel={d['direct']} json={d['prod']}")

    prod_only_dates = sorted(set(prod_data) - set(by_date))

    print(f"② 逐日比对结果（按日取填充最多行）")
    print(f"     完全一致      : {len(matched)} 天")
    print(f"     Excel 有/JSON 无 : {len(only_in_excel)} 处")
    print(f"     JSON 有/Excel 无 : {len(only_in_prod)} 处")
    print(f"     值不同        : {len(mismatch)} 处")
    print(f"     JSON 独有的日期 : {len(prod_only_dates)} 天")
    print()

    if only_in_excel:
        _today = datetime.date.today()
        print(f"③ Excel 有日期行、但未进 JSON: {len(only_in_excel)} 天")
        print("   （导出脚本仅在该行「至少有一个值」时才写入，故空行/预置行不入 JSON）")
        for ds, n in sorted(only_in_excel):
            d = datetime.date.fromisoformat(ds)
            tags = []
            if n == 0:
                tags.append("整行无值")
            if d > _today:
                tags.append("未来日期")
            elif not is_trading_day(d):
                tags.append(f"非交易日·{skip_reason(d)}")
            if d == _today:
                tags.append("今日")
            print(f"     {ds}  填充 {n:2d} 项   {' / '.join(tags) or '—'}")
        print()

    for title, items in (("JSON 有值但 Excel 无（人工补录/在线编辑）", only_in_prod),
                         ("两边值不同", mismatch),
                         ("JSON 独有日期", prod_only_dates)):
        if items:
            print(f"③ {title}: {len(items)} 项")
            for x in items[:12]:
                print(f"     {x}")
            if len(items) > 12:
                print(f"     …另 {len(items) - 12} 项")
            print()

    entry = {
        "date": datetime.date.today().isoformat(),
        "excel_rows": len(rows),
        "prod_days": len(prod_data),
        "dup_date_groups": len(dups),
        "matched_days": len(matched),
        "excel_only": only_in_excel[:200],
        "json_only": only_in_prod[:200],
        "mismatch": mismatch[:200],
        "json_only_dates": prod_only_dates,
    }
    append_report(REPORT_PATH, entry)

    # 判定：只有「有值的行」才算实质差异。今天/未来日期/节假日等空行本就不会进
    # JSON（导出脚本要求该行至少有一个值），不计入。
    nonempty_gap = [(ds, n) for ds, n in only_in_excel if n > 0]
    verdict = (not nonempty_gap and not only_in_prod and not mismatch)
    print("=" * 62)
    if verdict:
        print(f"  结论: ✅ 两条链路等价（{len(matched)} 天逐品种完全一致）")
        print(f"        空行差异 {len(only_in_excel)} 天（今日/未来/节假日），非丢数")
        print("        → 「抓取结果直接写 JSON」可安全推进")
    else:
        print("  结论: ⚠️ 存在实质差异，需逐项确认后再推进")
        print(f"        有值却未进 JSON: {len(nonempty_gap)} 天")
        print(f"        JSON 独有值     : {len(only_in_prod)} 处")
        print(f"        值不同          : {len(mismatch)} 处")
    print(f"  报告: {REPORT_PATH}")
    print("=" * 62)


if __name__ == "__main__":
    main()
