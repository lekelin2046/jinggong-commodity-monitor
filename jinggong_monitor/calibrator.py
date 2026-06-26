"""期现价差标定模块

内部快报价格是现货细分牌号价，免费数据源多为期货主力合约价。
此模块用历史内部数据做线性回归标定，自动修正期货价→近似现货价。

使用方式：
    calibrator = SpreadCalibrator()
    calibrator.fit(historical_data)        # 用 3 个月快报数据训练
    spot_estimate = calibrator.predict("W", futures_price=1318)
"""

import json
import logging
from pathlib import Path
from typing import Optional

from jinggong_monitor import get_project_root

logger = logging.getLogger("jinggong.calibrator")

_CALIB_FILE = get_project_root() / "data" / "spread_calibration.json"

# 品种错配参数（默认值，随着历史数据累积自动更新）
DEFAULT_SPREADS = {
    # variety_id: (a, b)  现货估算 = a × 期货 + b
    "AXB":  (1.05, -200),    # 酸洗板 ≈ 1.05 × HC 热卷 - 200
    "DXB":  (1.08, -150),    # 镀锌板 ≈ 1.08 × HC 热卷 - 150
    "LZB":  (1.03, -100),    # 冷轧板 ≈ 1.03 × HC 热卷 - 100
    "A00_AL": (1.02, 50),    # A00现货 ≈ 1.02 × AO 氧化铝期货 + 50
    "ADC12": (1.0, 1500),    # ADC12 ≈ A00铝 + 1500 加工费
    "WTI":   (1.0, 0),       # WTI 直接用
    "NPI":   (0.018, 0),     # 镍生铁 ≈ 0.018 × NI 沪镍（比例换算）
}


class SpreadCalibrator:
    """期现价差标定器"""

    def __init__(self):
        self._params: dict[str, tuple[float, float]] = {}
        self._load()

    def _load(self):
        """加载已保存的标定参数"""
        if _CALIB_FILE.exists():
            try:
                with open(_CALIB_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                for k, v in data.items():
                    self._params[k] = tuple(v)
                logger.info("加载标定参数: %d 品种", len(self._params))
            except Exception as e:
                logger.warning("标定参数加载失败: %s，使用默认值", e)
                self._params = {}
        else:
            logger.info("无历史标定参数，使用默认值")

    def _save(self):
        """保存标定参数"""
        data = {k: list(v) for k, v in self._params.items()}
        with open(_CALIB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_params(self, variety_id: str) -> tuple[float, float]:
        """获取品种的标定参数

        Returns:
            (a, b): 现货估算 = a × 期货价 + b
        """
        if variety_id in self._params:
            return self._params[variety_id]
        if variety_id in DEFAULT_SPREADS:
            return DEFAULT_SPREADS[variety_id]
        return (1.0, 0.0)  # 默认不做修正

    def predict(
        self,
        variety_id: str,
        futures_price: float,
        spot_price: Optional[float] = None,
    ) -> float:
        """用期货价估算现货价

        Args:
            variety_id: 品种ID
            futures_price: 期货主力合约价
            spot_price: 如果也有现货直接数据，优先使用

        Returns:
            估算的现货细分牌号价
        """
        if spot_price is not None and spot_price > 0:
            return spot_price

        a, b = self.get_params(variety_id)
        return round(a * futures_price + b, 2)

    def fit(
        self,
        variety_id: str,
        futures_prices: list[float],
        spot_prices: list[float],
    ):
        """用历史数据拟合标定参数

        Args:
            variety_id: 品种ID
            futures_prices: 期货历史价格列表
            spot_prices: 现货历史价格列表（来自内部快报）

        简单线性回归：spot = a × futures + b
        """
        if len(futures_prices) != len(spot_prices) or len(futures_prices) < 3:
            logger.warning("%s 数据不足，无法拟合（至少需要3个月度数据）", variety_id)
            return

        n = len(futures_prices)
        sum_x = sum(futures_prices)
        sum_y = sum(spot_prices)
        sum_xy = sum(x * y for x, y in zip(futures_prices, spot_prices))
        sum_x2 = sum(x * x for x in futures_prices)

        denom = n * sum_x2 - sum_x * sum_x
        if abs(denom) < 1e-10:
            # 数据过于平坦，不更新
            return

        a = (n * sum_xy - sum_x * sum_y) / denom
        b = (sum_y - a * sum_x) / n

        self._params[variety_id] = (round(a, 4), round(b, 2))
        self._save()
        logger.info(
            "%s 标定完成: 现货 = %.4f × 期货 + %.2f (R² 近似)", variety_id, a, b
        )
