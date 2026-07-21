#!/usr/bin/env python3
"""SMM 上海有色日报自动抓取 + Obsidian 归档

运行：
    cd /Users/siqi/Desktop/AI/jinggong-commodity-monitor && /opt/homebrew/bin/python3 capture_smm_daily.py

功能：
1. 自动复用/登录 SMM 账号
2. 抓取 7 个品种：ADC12 / A380 / AlSi9Cu3 / A356 / 闻喜镁锭 / AM60B / AZ91D
3. 生成 Markdown 日报
4. 写入项目目录：上海有色日价格查询/YYYY-MM-DD_上海有色.md
5. 写入 Obsidian Vault：工作/大宗原材料监控/日报/YYYY-MM-DD-上海有色.md
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

# 将项目根加入路径，确保可导入 jinggong_monitor
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from jinggong_monitor.fetcher_smm import SmmFetcher  # noqa: E402

logger = logging.getLogger("capture_smm_daily")

# 输出路径
PROJECT_OUTPUT_DIR = PROJECT_ROOT / "上海有色日价格查询"
OBSIDIAN_VAULT_DIR = Path.home() / "Documents" / "Obsidian Vault" / "工作" / "大宗原材料监控" / "日报"

# 中文品种名映射
NAME_MAP = {
    "ADC12": "ADC12铝合金",
    "A380": "A380铝合金",
    "AlSi9Cu3": "AlSi9Cu3铝合金",
    "A356": "A356铝合金",
    "WenxiMG": "闻喜镁锭 99.9%min",
    "AM60B": "AM60B镁合金",
    "AZ91D": "AZ91D镁合金",
}

UNIT = "元/吨"


def generate_markdown(data: dict, today: str, generated_at: str) -> str:
    lines = []
    lines.append(f"# SMM 上海有色日价格查询 — {today}")
    lines.append("")
    lines.append(f"> 来源：SMM 上海有色网 | 生成时间：{generated_at}")
    lines.append("")
    lines.append("## 今日价格")
    lines.append("")
    lines.append("| 品种 | 均价 | 单位 |")
    lines.append("|------|------|------|")
    for key in NAME_MAP:
        name = NAME_MAP[key]
        price = data.get(key)
        if price is None:
            lines.append(f"| {name} | — | {UNIT} |")
        else:
            lines.append(f"| {name} | {price:,.0f} | {UNIT} |")
    lines.append("")
    lines.append("---")
    lines.append("*本文件由精工有色金属监控系统自动生成*")
    lines.append("")
    return "\n".join(lines)


def write_files(content: str, today: str) -> tuple[Path, Path]:
    project_path = PROJECT_OUTPUT_DIR / f"{today}_上海有色.md"
    obsidian_path = OBSIDIAN_VAULT_DIR / f"{today}-上海有色.md"

    PROJECT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OBSIDIAN_VAULT_DIR.mkdir(parents=True, exist_ok=True)

    project_path.write_text(content, encoding="utf-8")
    obsidian_path.write_text(content, encoding="utf-8")

    return project_path, obsidian_path


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
    )

    today = datetime.now().strftime("%Y-%m-%d")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logger.info("=== SMM 日报抓取开始：%s ===", today)

    try:
        fetcher = SmmFetcher()
        data = fetcher.fetch(target_date=today)
    except Exception as e:
        logger.error("SMM 抓取失败: %s", e)
        sys.exit(1)

    content = generate_markdown(data, today, generated_at)
    project_path, obsidian_path = write_files(content, today)

    logger.info("项目目录日报：%s", project_path)
    logger.info("Obsidian Vault日报：%s", obsidian_path)
    logger.info("=== SMM 日报抓取完成：%d/7 品种 ===", len(data))


if __name__ == "__main__":
    main()
