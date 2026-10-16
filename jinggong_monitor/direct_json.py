"""
「直接写 JSON」通道 —— 影子比对层（2026-10-16 引入，只读、不写生产文件）

背景
----
精工当前数据流是「抓取 → Excel → export_excel_to_json.py → docs/data.json」，
**Excel 是唯一真源，data.json 只是它的投影**。该设计带来两项长期成本：

1. 品种以「Excel 物理列号」为主键 —— 新增一个品种要在 5 处手工同步
   （daily_update_all.COL_MAP / export_excel_to_json.COLUMN_MAP /
    sync_from_web.COLUMN_MAP / docs/index.html / docs/editor.html），
   其中前端两处漏改**不报错、不提示**，表现为「数据抓到了但页面不显示」。
2. 在线编辑（editor.html 直接 PUT docs/data.json）的改动必须经
   sync_from_web.py 回写 Excel，否则下一次全量导出即被覆盖。

若抓取结果能**不经 Excel 直接写进 data.json**，上述两条同时消失。
本模块的作用是：在真正切换之前，先**证明**「直接写」与「现有导出」逐日逐品种等价。

本模块只做证明，绝不写 docs/ 下任何文件
----------------------------------------
- build_day_record()      把「品种代码 → 数值」转成 data.json 的日期行形态
- load_production_day()   只读生产 docs/data.json 中某一天的行
- diff_records()          逐品种比对，产出差异清单（含差异类型）
- shadow_compare()        一次完整比对 + 追加一行 JSONL 报告
- append_report()         追加式写报告（daily 累积，便于观察趋势）

所有异常必须由调用方 try/except 兜住，**不得影响抓取主流程**。
"""

from __future__ import annotations

import json
from pathlib import Path


def codes_of(col_map) -> list:
    """从列映射里取出品种代码清单。

    兼容两种写法：
      - daily_update_all.COL_MAP       : {列号: (code, 数据源)}
      - export_excel_to_json.COLUMN_MAP: {列号: code}
    """
    out = []
    for v in col_map.values():
        out.append(v[0] if isinstance(v, (tuple, list)) else v)
    return out


def build_day_record(prices: dict, codes) -> dict:
    """把「品种代码 → 数值」转成 data.json 日期行的形态。

    与 export_excel_to_json.py 的口径保持一致：
      - 值为 None / 缺失 → 该品种**不出现**在行里（而非写 null）
      - 数值统一转 float
    """
    rec = {}
    for code in codes:
        v = prices.get(code)
        if v is None:
            continue
        try:
            rec[code] = float(v)
        except (TypeError, ValueError):
            continue
    return rec


def load_production_day(prod_path, date_str):
    """只读生产 data.json，返回 date_str 那一天的行；文件或该日不存在返回 None。"""
    try:
        doc = json.loads(Path(prod_path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  文件缺失/损坏一律视为「无法比对」
        return None
    return (doc.get("data") or {}).get(date_str)


def diff_records(direct: dict, prod: dict, codes) -> list:
    """逐品种比对「直接写」与「生产导出」的行，返回差异清单。

    差异类型：
      loss       仅直接写有值  → 现有导出链路把它丢了（导出漏洞）
      manual     仅生产有值    → 该值不来自本次抓取（人工补录 / Excel 残留 / 在线编辑）
      mismatch   两边都有但不等 → 人工改动或 Excel 公式参与
    """
    diffs = []
    for code in codes:
        d = direct.get(code)
        p = (prod or {}).get(code)
        if d is None and p is None:
            continue
        if d == p:
            continue
        if d is not None and p is None:
            kind = "loss"
        elif d is None and p is not None:
            kind = "manual"
        else:
            kind = "mismatch"
        diffs.append({"code": code, "direct": d, "prod": p, "kind": kind})
    return diffs


def append_report(report_path, entry: dict) -> None:
    """追加一行 JSONL。追加式写入，天然按日累积，便于观察长期趋势。"""
    p = Path(report_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def shadow_compare(prices: dict, date_str: str, col_map, prod_path,
                   report_path, label: str = "抓取") -> dict:
    """一次完整的影子比对：抓取结果 vs 生产 data.json 的当日行。

    只读生产文件；报告追加一行。返回 entry（便于测试断言）。
    """
    codes = codes_of(col_map)
    direct = build_day_record(prices, codes)
    prod = load_production_day(prod_path, date_str)

    entry = {
        "date": date_str,
        "label": label,
        "direct_count": len(direct),
        "prod_count": len(prod) if prod else 0,
        "prod_day_missing": prod is None,
        "diff_count": 0,
        "diffs": [],
    }

    if prod is None:
        entry["note"] = "生产 data.json 中无该日期行（导出尚未完成或该日未出数）"
        append_report(report_path, entry)
        print(f"  ⚠️ 影子比对：生产 data.json 无 {date_str} 行（直接写 {len(direct)} 项待观察）")
        return entry

    diffs = diff_records(direct, prod, codes)
    entry["diff_count"] = len(diffs)
    entry["diffs"] = diffs
    append_report(report_path, entry)

    if not diffs:
        print(f"  ✓ 影子比对一致（{len(direct)} 项；直接写 ≡ 现有导出）")
    else:
        print(f"  ⚠️ 影子比对存在 {len(diffs)} 项差异（直接写 {len(direct)} / 生产 {len(prod)}）：")
        for d in diffs[:6]:
            print(f"       {d['code']}: 直接写={d['direct']} 生产={d['prod']}（{d['kind']}）")
        if len(diffs) > 6:
            print(f"       …另 {len(diffs) - 6} 项，详见 {report_path}")
    return entry
