#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 docs/mand/index.html 生成 docs/finest/index.html（蜂巢汽车看板）

蜂巢汽车看板与曼德热系统看板共用同一套前端骨架（趋势图 / 波动率 / 预测 /
日价格明细表 / 导出），差异只在【标题】【品种常量】【来源 badge】三处。
本脚本负责同步这三块，避免手改 1100+ 行 HTML 时漏改硬编码常量
（前端**不读** data.json 的元数据，品种名/单位/来源全部硬编码在页内）。

曼德页若升级骨架，重跑本脚本即可把升级同步到蜂巢页。

🔴 模板漂移守卫 FORBIDDEN_IN_FINEST：曼德页含若干蜂巢**没有**的品种
   （PCU 磷铜合金 / AL_ALSI12FE / AL_A360 / PP_T30S / PP_EP548R）。
   若这些代码在生成结果中残留，说明常量替换未覆盖到位，本脚本 fail loud 拒绝出页。

用法：python3 gen_finest_board.py
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "docs" / "mand" / "index.html"
DST = ROOT / "docs" / "finest" / "index.html"

# ⚠️ 模板页标题必须与 docs/mand/index.html 的 <title>/<h1> 完全一致。
#    曼德页改名后此常量未同步会导致本脚本第一步即 [FATAL] 退出。
OLD_TITLE = "曼德热系统大宗原材料价格看板"
NEW_TITLE = "蜂巢汽车大宗原材料价格看板"
DEFAULT_UNIT = "元/吨"

# (code, 显示名, 数据源, 单位) —— 必须与 finest_update.py 的 SPEC 保持一致
VARIETIES = [
    ("CU",          "铜（上海地区现货）",   "长江有色网",       "元/吨"),
    ("AG",          "1#白银",               "长江有色网",       "元/千克"),
    ("AL_A00",      "SMM A00铝",            "SMM 上海有色",     "元/吨"),
    ("AL_A380",     "A380铝合金",           "SMM 上海有色",     "元/吨"),
    ("AL_ADC12",    "SMM铝合金ADC12",       "SMM 上海有色",     "元/吨"),
    ("AL_ALSI9CU3", "AlSi9Cu3铝合金",       "SMM 上海有色",     "元/吨"),
    ("CU_CATH1",    "CU-CATH-1（1#电解铜）", "SMM 上海有色",     "元/吨"),
    ("PA6",         "PA6",                  "卓创资讯",         "元/吨"),
    ("PA66",        "PA66",                 "卓创资讯",         "元/吨"),
    ("PRND",        "镨钕混合金属",         "亚洲金属网",       "元/吨"),
    ("DYFE",        "镝铁 80%",             "亚洲金属网",       "元/公斤"),
    ("TB",          "金属铽 99.9%",         "亚洲金属网",       "元/公斤"),
    ("BASF_PA66",   "巴斯夫 PA66",          "PCI (ChemOrbis)",  "—"),
]
# 注：BASF_PA66 为挂起占位（PCI 付费订阅、我方无账号），看板显示挂起、无历史数值。

CATEGORIES = [
    ("铜及贵金属", ["CU", "CU_CATH1", "AG"]),
    ("铝及铝合金", ["AL_A00", "AL_A380", "AL_ADC12", "AL_ALSI9CU3"]),
    ("稀土金属",   ["PRND", "DYFE", "TB"]),
    ("工程塑料",   ["PA6", "PA66", "BASF_PA66"]),
]

# KPI 关键品种卡：只列已接入且在跑的代表品种，避免出现全空卡片。
# ⚠️ 卡片单位按 VARIETY_UNITS 动态取值（曼德页已改造），故可安全纳入 AG（元/千克）。
KPI_CODES = ["CU", "CU_CATH1", "AL_A00", "AL_ADC12", "AL_A380"]

# 市场/口径标签：长江现货与 SMM 现货均在上海，与数据源列重复，故不显示；
# 卓创 / 亚洲金属网 / PCI 品种须标注口径，否则无法复盘取的是哪一行。
MARKETS = {
    "PA6":       "BL3280H · 华南",
    "PA66":      "EPR27 · 神马塑料",
    "PRND":      "Pr 25%/Nd 75% · 中国出厂",
    "DYFE":      "80% · 中国出厂",
    "TB":        "99.9% · 中国出厂",
    "BASF_PA66": "PCI 订阅制 · 待接入",
}

BADGE_TEXT_OLD = "13 品种 · 13 项已接入（长江有色 3 / SMM 5 / 卓创 5）"
BADGE_TEXT_NEW = "13 品种 · 12 项已接入（长江有色 2 / SMM 5 / 卓创 2 / 亚洲金属网 3）"

# 曼德页独有、蜂巢页不得残留的品种代码（模板漂移守卫）
FORBIDDEN_IN_FINEST = ["PCU", "AL_ALSI12FE", "AL_A360", "PP_T30S", "PP_EP548R"]


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

    # 2) 来源 badge 文案替换
    html = replace_once(html, BADGE_TEXT_OLD, BADGE_TEXT_NEW, "来源 badge 文案")

    # 3) 品种常量（前端硬编码，必须与 finest_update.py 的 SPEC 保持一致）
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

    # 4) 模板漂移守卫：曼德独有品种代码不得残留
    drift = [bad for bad in FORBIDDEN_IN_FINEST if f'"{bad}"' in html]
    if drift:
        raise SystemExit(
            "[FATAL] 生成结果中残留曼德页独有品种代码：" + "、".join(drift) + "\n"
            "  说明品种常量替换未覆盖到位（或曼德页新增了未纳入守卫的品种），已拒绝出页。"
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
