"""优雅降级模块

当主数据源失败时，按优先级自动降级：
  优先级1: 专用现货源 (zgw/cnfeol/ccmn)
      ↓ 失败
  优先级2: 期货先导指标 + 代理映射 (akshare)
      ↓ 也失败
  优先级3: 上一次成功数据 + 标记"数据中断"
      ↓ 还失败
  优先级4: 硬编码参考值（高碳铬铁、钨粉等小众品种）
"""

import logging
import pickle
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from jinggong_monitor import get_project_root

logger = logging.getLogger("jinggong.fallback")

# 历史缓存路径
_CACHE_FILE = get_project_root() / "data" / "last_prices.pkl"

# 硬编码参考值（小众品种，来自内部2026年5月快报，实际使用时需定期人工更新）
_REFERENCE_PRICES = {
    "HCRFE": 7403.0,    # 高碳铬铁（内蒙）元/基吨
    "W":     1318.0,    # 钨粉 元/千克
}


def save_snapshot(prices: dict[str, float]):
    """保存当前价格快照"""
    snapshot = {
        "prices": {k: v for k, v in prices.items() if v > 0},
        "timestamp": datetime.now().isoformat(),
    }
    with open(_CACHE_FILE, "wb") as f:
        pickle.dump(snapshot, f)
    logger.debug("价格快照已保存: %d 品种", len(snapshot["prices"]))


def load_snapshot() -> Optional[dict[str, float]]:
    """加载上次价格快照"""
    if not _CACHE_FILE.exists():
        return None
    try:
        with open(_CACHE_FILE, "rb") as f:
            snapshot = pickle.load(f)
        ts = datetime.fromisoformat(snapshot["timestamp"])
        if (datetime.now() - ts).days > 3:
            logger.warning("价格快照已过期(%s)", snapshot["timestamp"])
            return None
        logger.info("降级快照: %s, %d品种", snapshot["timestamp"], len(snapshot["prices"]))
        return snapshot["prices"]
    except Exception as e:
        logger.error("读取快照失败: %s", e)
        return None


def apply_fallback(
    final_prices: dict[str, float],
    all_variety_ids: list[str],
) -> dict[str, float]:
    """对缺失品种优先用快照，其次用参考值补全

    Returns:
        补全后的价格（仍无法获取的标记为 -1）
    """
    missing = [vid for vid in all_variety_ids if vid not in final_prices or final_prices[vid] <= 0]
    if not missing:
        return final_prices

    filled = dict(final_prices)
    snapshot = load_snapshot()

    for vid in missing:
        # 优先级1: 快照
        if snapshot and vid in snapshot and snapshot[vid] > 0:
            filled[vid] = snapshot[vid]
            logger.info("快照补全 %s = %.2f", vid, snapshot[vid])
        # 优先级2: 硬编码参考值
        elif vid in _REFERENCE_PRICES:
            filled[vid] = _REFERENCE_PRICES[vid]
            logger.info("参考值补全 %s = %.2f (需人工更新)", vid, _REFERENCE_PRICES[vid])
        else:
            filled[vid] = -1.0

    return filled

