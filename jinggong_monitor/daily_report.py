"""日报生成器

生成精工板块 16 品种 Markdown 日报。
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from jinggong_monitor import get_varieties, get_project_root
from jinggong_monitor.validator import ValidationResult, TRUSTED, SUSPICIOUS, SINGLE_SRC, MISSING

logger = logging.getLogger("jinggong.reporter")

# 中国市场惯例：涨=红，跌=绿
UP = "🔴"
DOWN = "🟢"
FLAT = "⚪"


def _classify_group(variety_name: str) -> str:
    """将品种名归类到板块"""
    mapping = {
        "钢板": ["酸洗", "镀锌", "冷轧"],
        "黑色金属": ["焦炭", "铁矿石"],
        "有色金属": ["A00铝", "ADC12", "铜"],
        "不锈钢": ["304", "409", "439", "441"],
        "铁合金": ["镍生铁", "高碳铬铁"],
        "小金属": ["钨粉"],
        "能源": ["WTI", "原油"],
    }
    for group, keywords in mapping.items():
        for kw in keywords:
            if kw in variety_name:
                return group
    return "其他"


def generate_report(
    prices: dict[str, float],
    validations: list[ValidationResult],
    target_date: Optional[str] = None,
) -> str:
    """生成 Markdown 日报"""
    today = target_date or datetime.now().strftime("%Y-%m-%d")
    varieties = {v["id"]: v for v in get_varieties()}

    lines = []

    # ============ 标题 ============
    lines.append(f"# 📊 精工板块大宗原材料日报 — {today}")
    lines.append("")
    lines.append(f"> 自动采集 | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # ============ 质量摘要 ============
    trusted = sum(1 for v in validations if v.quality == TRUSTED)
    suspicious = sum(1 for v in validations if v.quality == SUSPICIOUS)
    single = sum(1 for v in validations if v.quality == SINGLE_SRC)
    missing_count = sum(1 for v in validations if v.quality == MISSING)

    quality_emoji = "✅" if suspicious == 0 and missing_count == 0 else "⚠️"
    lines.append(f"## 数据质量 {quality_emoji}")
    lines.append("")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 采集品种 | {len(prices)}/16 |")
    lines.append(f"| 多源验证通过 | {trusted} |")
    lines.append(f"| 多源差异需关注 | {suspicious} |")
    lines.append(f"| 单源无交叉验证 | {single} |")
    lines.append(f"| 数据缺失 | {missing_count} |")
    lines.append("")

    # ============ 价格总表 ============
    lines.append("## 一、今日价格总览")
    lines.append("")

    # 按板块分组
    grouped: dict[str, list] = {}
    for vid, price in prices.items():
        vname = varieties.get(vid, {}).get("name", vid)
        unit = varieties.get(vid, {}).get("unit", "")
        group = _classify_group(vname)
        val = next((v for v in validations if v.variety_id == vid), None)
        quality = val.quality if val else MISSING
        grouped.setdefault(group, []).append((vname, price, unit, quality))

    group_order = ["钢板", "黑色金属", "有色金属", "不锈钢", "铁合金", "小金属", "能源"]
    for group in group_order:
        if group not in grouped:
            continue
        items = grouped[group]
        lines.append(f"### {group}")
        lines.append("")
        lines.append("| 品种 | 价格 | 单位 | 数据质量 |")
        lines.append("|------|------|------|:------:|")
        for vname, price, unit, quality in items:
            q_icon = {"trusted": "✅", "suspicious": "⚠️", "single": "ℹ️", "missing": "❌"}.get(quality, "❓")
            price_str = f"{price:,.0f}" if price > 0 else "—"
            lines.append(f"| {vname} | {price_str} | {unit} | {q_icon} |")
        lines.append("")

    # ============ 数据质量详情 ============
    alert_items = [v for v in validations if v.quality in (SUSPICIOUS, MISSING)]
    if alert_items:
        lines.append("## 二、需关注项")
        lines.append("")
        for v in alert_items:
            icon = "⚠️" if v.quality == SUSPICIOUS else "❌"
            lines.append(f"- {icon} **{v.variety_name}**: {v.detail}")
            if v.sources_used:
                lines.append(f"  - 数据来源: {', '.join(v.sources_used)}")
        lines.append("")

    # ============ 数据来源 ============
    lines.append("## 三、数据来源")
    lines.append("")
    lines.append("| 数据源 | 覆盖品种 | 抓取方式 |")
    lines.append("|--------|---------|:------:|")
    lines.append("| akshare 期货 | 焦炭/铁矿石/铜/304不锈钢/WTI | API |")
    lines.append("| 中钢网 zgw.com | 酸洗板/镀锌板/冷轧板 | HTML |")
    lines.append("| 铁合金在线 cnfeol.com | 高碳铬铁 | HTML |")
    lines.append("| 中钨在线 | 钨粉 | HTML |")
    lines.append("| 长江有色 ccmn.cn | A00铝/铜 | HTML |")
    lines.append("| 卓创资讯 sci99.com | 备源 | CDP |")
    lines.append("| 51bxg | 409/439/441不锈钢 | CDP |")
    lines.append("| SMM | ADC12/A00铝 | CDP |")
    lines.append("")

    lines.append("---")
    lines.append(f"*本报告由精工大宗监控系统自动生成*")
    lines.append("")

    return "\n".join(lines)


def write_report(
    prices: dict[str, float],
    validations: list[ValidationResult],
    target_date: Optional[str] = None,
) -> str:
    """写入日报文件，返回路径"""
    today = target_date or datetime.now().strftime("%Y-%m-%d")
    content = generate_report(prices, validations, target_date)

    report_dir = get_project_root() / "data" / "output" / "日报"
    report_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{today}-精工大宗日报.md"
    filepath = report_dir / filename
    filepath.write_text(content, encoding="utf-8")

    logger.info("日报已生成: %s", filepath)
    return str(filepath)
