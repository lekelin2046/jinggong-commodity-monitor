#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 docs/plastic/index.html 生成 docs/mand/index.html

曼德看板与诺博塑料看板共用同一套前端骨架（趋势图 / 波动率 / 预测 / 日价格明细表 /
导出），差异只在【标题】与【品种常量】。本脚本负责同步这两块，
避免手改 1100 行 HTML 时漏改硬编码常量（前端不读 data.json 的元数据）。

塑料看板若升级骨架，重跑本脚本即可把升级同步到曼德看板。

用法：python3 gen_mand_board.py
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "docs" / "plastic" / "index.html"
DST = ROOT / "docs" / "mand" / "index.html"

OLD_TITLE = "诺博大宗原材料价格看板"
NEW_TITLE = "曼德热系统大宗原材料价格看板"
DEFAULT_UNIT = "元/吨"

# (code, 显示名, 数据源, 单位)
VARIETIES = [
    ("CU",          "铜（上海地区现货）", "长江有色网",   "元/吨"),
    ("AG",          "1#白银",             "长江有色网",   "元/千克"),
    ("PCU",         "磷铜合金",           "长江有色网",   "元/吨"),
    ("AL_A00",      "SMM A00铝",          "SMM 上海有色", "元/吨"),
    ("AL_A380",     "A380铝合金",         "SMM 上海有色", "元/吨"),
    ("AL_ADC12",    "SMM铝合金ADC12",     "SMM 上海有色", "元/吨"),
    ("AL_ALSI12FE", "AlSi12(Fe)铝合金",   "SMM 上海有色", "元/吨"),
    ("PRND",        "镨钕金属",           "亚洲金属网",   "元/吨"),
    ("PA6",         "PA6",                "卓创资讯",     "元/吨"),
    ("PA66",        "PA66",               "卓创资讯",     "元/吨"),
    ("PA66_BASF",   "巴斯夫PA66",         "PCI",          "元/吨"),
    ("PP_TD20",     "PP-TD20",            "卓创资讯",     "元/吨"),
    ("PP_TD40",     "PP-TD40",            "卓创资讯",     "元/吨"),
]

CATEGORIES = [
    ("铜及贵金属", ["CU", "AG", "PCU"]),
    ("铝及铝合金", ["AL_A00", "AL_A380", "AL_ADC12", "AL_ALSI12FE"]),
    ("稀土金属",   ["PRND"]),
    ("工程塑料",   ["PA6", "PA66", "PA66_BASF"]),
    ("改性塑料",   ["PP_TD20", "PP_TD40"]),
]

# KPI 关键品种卡：只列已接入且在跑的代表品种，避免出现全空卡片。
# ⚠️ 卡片单位原本硬编码「元/吨」，本脚本已改为按 VARIETY_UNITS 动态取值，
#    因此可安全纳入 AG（元/千克）。
KPI_CODES = ["CU", "AG", "AL_A00", "AL_ADC12", "AL_ALSI12FE"]

# 市场标签：曼德各品种的「市场」信息与数据源高度重合（长江现货 / SMM 现货均在上海），
# 显示标签会造成与数据源列重复，故置空不显示。
MARKETS = {}

BADGE = ('  <span style="font-size:12px;color:#475569;background:#e2e8f0;'
         'padding:3px 9px;border-radius:6px;white-space:nowrap">'
         '13 品种 · 7 项已接入（长江有色 3 / SMM 4）</span>')


def js(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def replace_once(html: str, old: str, new: str, label: str) -> str:
    """精确替换，命中数必须为 1，否则终止（防止模板漂移后静默漏改）"""
    n = html.count(old)
    if n != 1:
        raise SystemExit(f"[FATAL] {label} 命中 {n} 处，期望 1 处")
    return html.replace(old, new, 1)


def replace_js_const(html: str, name: str, value) -> str:
    """替换单行 JS 常量『const NAME = {...};』或『const NAME = [...];』，命中数必须为 1"""
    pat = re.compile(r"const " + name + r" = [\[{][^\n]*[\]}];")
    hits = pat.findall(html)
    if len(hits) != 1:
        raise SystemExit(f"[FATAL] const {name} 命中 {len(hits)} 处，期望 1 处")
    return pat.sub(lambda m: f"const {name} = {js(value)};", html, count=1)


def main() -> int:
    if not SRC.exists():
        raise SystemExit(f"[FATAL] 模板不存在: {SRC}")

    html = SRC.read_text(encoding="utf-8")
    orig_len = len(html)

    # 1) 标题（title + h1，共 2 处）
    n_title = html.count(OLD_TITLE)
    if n_title != 2:
        raise SystemExit(f"[FATAL] 标题『{OLD_TITLE}』命中 {n_title} 处，期望 2 处")
    html = html.replace(OLD_TITLE, NEW_TITLE)

    # 2) header 加来源 badge（h1 文案为「📊 <标题>」，emoji 必须计入锚点）
    anchor = f"📊 {NEW_TITLE}</h1>"
    html = replace_once(html, anchor, anchor + "\n" + BADGE, "h1 锚点")

    # 3) KPI 卡片单位硬编码「元/吨」→ 按品种单位动态取值
    html = replace_once(
        html,
        ': "—"}<span class="unit">元/吨</span>${fmtChg(cur, prev)}',
        ': "—"}<span class="unit">${VARIETY_UNITS[code] || DEFAULT_UNIT}</span>${fmtChg(cur, prev)}',
        "KPI 卡片单位",
    )

    # 4) 品种常量（前端硬编码，必须与 mand_update.py 的 SPEC 保持一致）
    names = {c: n for c, n, s, u in VARIETIES}
    sources = {c: s for c, n, s, u in VARIETIES}
    units = {c: u for c, n, s, u in VARIETIES if u != DEFAULT_UNIT}
    markets = {c: MARKETS[c] for c, *_ in VARIETIES if c in MARKETS}

    html = replace_js_const(html, "VARIETY_NAMES", names)
    html = replace_js_const(html, "VARIETY_UNITS", units)
    html = replace_js_const(html, "VARIETY_SOURCES", sources)
    html = replace_js_const(html, "VARIETY_MARKETS", markets)
    html = replace_js_const(html, "KPI_KEY_CODES", KPI_CODES)
    html = replace_js_const(
        html, "CATEGORIES",
        [{"name": n, "codes": c} for n, c in CATEGORIES],
    )

    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text(html, encoding="utf-8")

    print(f"  模板 {SRC.relative_to(ROOT)}  ({orig_len:,} B)")
    print(f"  →  {DST.relative_to(ROOT)}  ({len(html):,} B)")
    print(f"  品种 {len(VARIETIES)} 个 / 分组 {len(CATEGORIES)} 个")
    print(f"  KPI 卡片: {', '.join(KPI_CODES)}")
    print(f"  非默认单位: {units if units else '无（全部 ' + DEFAULT_UNIT + '）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
