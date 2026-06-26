"""精工板块大宗原材料监控 - 主入口

用法:
    python -m jinggong_monitor.main fetch    # 仅拉取数据
    python -m jinggong_monitor.main report   # 仅生成日报
    python -m jinggong_monitor.main fill     # 仅填充Excel
    python -m jinggong_monitor.main all      # 全流程
    python -m jinggong_monitor.main health   # 健康检查
"""

import logging
import os
import sys
from datetime import datetime

# GitHub 加速器等系统代理会阻断国内大宗商品站点，全局禁用代理
_NO_PROXY_DOMAINS = (
    "51bxg.com,sci99.com,chinatungsten.com,steelcn.cn,zgw.com,"
    "ccmn.cn,cnfeol.com,ctia.com.cn,100ppi.com,mysteel.com,"
    "cls.cn,smm.cn,qqthj.com"
)
os.environ.setdefault("NO_PROXY", _NO_PROXY_DOMAINS)
os.environ.setdefault("no_proxy", _NO_PROXY_DOMAINS)

from jinggong_monitor import get_varieties
from jinggong_monitor.orchestrator import PriceCollector
from jinggong_monitor.validator import PriceValidator
from jinggong_monitor.fallback import save_snapshot, apply_fallback
from jinggong_monitor.calibrator import SpreadCalibrator
from jinggong_monitor.daily_report import write_report
from jinggong_monitor.excel_filler import fill_excel

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("jinggong.main")


def cmd_fetch(today: str) -> dict:
    """Step 1: 采集全部品种价格"""
    logger.info("=" * 60)
    logger.info("开始采集精工板块 16 品种价格...")
    logger.info("=" * 60)

    collector = PriceCollector()
    prices = collector.collect_all(today)

    # 应用降级策略
    all_ids = [v["id"] for v in get_varieties()]
    prices = apply_fallback(prices, all_ids)

    # 期现价差标定
    calibrator = SpreadCalibrator()
    for vid, price in list(prices.items()):
        if price < 0:
            continue
        # ADC12 特殊处理
        if vid == "ADC12":
            a00 = prices.get("A00_AL")
            if a00 and a00 > 0:
                prices[vid] = calibrator.predict(vid, a00, spot_price=price)
        # 其他品种用默认参数
        corrected = calibrator.predict(vid, price, spot_price=price)
        if corrected != price:
            logger.info("标定修正 %s: %.2f → %.2f", vid, price, corrected)
            prices[vid] = corrected

    # 保存快照
    save_snapshot({k: v for k, v in prices.items() if v > 0})

    # 打印结果
    varieties = {v["id"]: v for v in get_varieties()}
    logger.info("")
    logger.info("采集结果:")
    for vid, price in prices.items():
        vname = varieties.get(vid, {}).get("name", vid)
        unit = varieties.get(vid, {}).get("unit", "")
        status = "" if price > 0 else " ❌缺失"
        logger.info("  %s: %.2f %s%s", vname, price, unit, status)

    # 显示失败
    failures = collector.get_failures()
    if failures:
        logger.warning("失败数据源:")
        for src, err in failures:
            logger.warning("  %s: %s", src, err)

    return prices


def cmd_validate(prices: dict) -> list:
    """Step 2: 多源交叉验证"""
    return []  # 在 orchestrator 中已完成，这里是接口占位


def cmd_report(prices: dict, today: str):
    """Step 3: 生成日报"""
    logger.info("生成日报...")

    # 简易验证
    from jinggong_monitor.validator import ValidationResult, SINGLE_SRC
    varieties = {v["id"]: v for v in get_varieties()}
    validations = []
    for vid, price in prices.items():
        validations.append(ValidationResult(
            vid, varieties.get(vid, {}).get("name", vid),
            price if price > 0 else None,
            SINGLE_SRC,
            detail="自动化采集",
            sources_used=["auto"],
        ))

    path = write_report(prices, validations, today)
    logger.info("日报: %s", path)
    return path


def cmd_fill(prices: dict, today: str):
    """Step 4: 填充 Excel"""
    logger.info("填充共享 Excel...")
    path = fill_excel(prices, target_date=today)
    logger.info("Excel: %s" if path else "Excel 填充失败", path)
    return path


def cmd_health():
    """健康检查"""
    from jinggong_monitor import get_sources

    logger.info("=" * 60)
    logger.info("数据源健康检查")
    logger.info("=" * 60)

    sources_cfg = get_sources()
    for src_name, cfg in sources_cfg.items():
        health_url = cfg.get("health_url")
        if health_url:
            import requests
            try:
                resp = requests.get(health_url, timeout=10)
                status = "✅" if resp.status_code == 200 else "⚠️"
                logger.info("  %s %s (HTTP %d)", status, src_name, resp.status_code)
            except Exception as e:
                logger.warning("  ❌ %s: %s", src_name, e)
        else:
            logger.info("  ℹ️ %s (通过 Python 库，跳过 HTTP 检查)", src_name)


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"

    logger.info("精工板块大宗原材料监控系统 v1.0")
    logger.info("执行日期: %s | 命令: %s", today, cmd)

    prices = {}

    if cmd in ("fetch", "all"):
        prices = cmd_fetch(today)

    if cmd in ("report", "all"):
        if not prices:
            prices = cmd_fetch(today)
        cmd_report(prices, today)

    if cmd in ("fill", "all"):
        if not prices:
            prices = cmd_fetch(today)
        cmd_fill(prices, today)

    if cmd == "health":
        cmd_health()

    logger.info("完成.")


if __name__ == "__main__":
    main()
