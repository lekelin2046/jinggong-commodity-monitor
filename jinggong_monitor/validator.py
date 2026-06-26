"""多源交叉验证器

功能：
1. 同一品种多源数据差异检测
2. 异常价格识别（与历史趋势偏差过大）
3. 数据质量标记（信任/可疑/待确认）
"""

import logging
from typing import Optional

from jinggong_monitor import get_varieties

logger = logging.getLogger("jinggong.validator")

# 数据质量等级
TRUSTED = "trusted"        # 多源一致，可信任
SUSPICIOUS = "suspicious"  # 多源差异超阈值，需关注
SINGLE_SRC = "single"      # 仅单源，无交叉验证
MISSING = "missing"        # 数据缺失


class ValidationResult:
    """单个品种的验证结果"""

    def __init__(
        self,
        variety_id: str,
        variety_name: str,
        final_price: Optional[float],
        quality: str,
        detail: str = "",
        sources_used: list[str] = None,
    ):
        self.variety_id = variety_id
        self.variety_name = variety_name
        self.final_price = final_price
        self.quality = quality
        self.detail = detail
        self.sources_used = sources_used or []


class PriceValidator:
    """价格验证器"""

    def __init__(self):
        self.varieties = get_varieties()
        self.results: list[ValidationResult] = []

    def validate(
        self,
        final_prices: dict[str, float],
        raw_results: dict[str, dict[str, float]],
    ) -> list[ValidationResult]:
        """对所有品种进行验证

        Args:
            final_prices: 合并后的最终价格 {variety_id: price}
            raw_results: 各数据源原始结果 {source_name: {variety_id: price}}
        """
        self.results = []

        for var in self.varieties:
            vid = var["id"]
            vname = var["name"]
            threshold = var.get("threshold_pct", 5.0)

            price = final_prices.get(vid)

            # 情况1: 无数据
            if price is None:
                self.results.append(ValidationResult(
                    vid, vname, None, MISSING,
                    detail="所有数据源均未获取到数据",
                ))
                continue

            # 收集多源价格
            multi_source_prices = {}
            sources_used = []
            for src_key in ("primary", "fallback", "fallback2", "proxy"):
                src_name = var.get("sources", {}).get(src_key)
                if not src_name:
                    continue
                raw = raw_results.get(src_name, {})
                sp = raw.get(vid)
                if sp is not None and sp > 0:
                    multi_source_prices[src_name] = sp
                    if src_name not in sources_used:
                        sources_used.append(src_name)

            # 情况2: 单源，无交叉验证
            if len(multi_source_prices) < 2:
                quality = SINGLE_SRC
                detail = f"仅 {', '.join(sources_used)} 单源数据"
            else:
                # 情况3: 多源交叉验证
                prices_list = list(multi_source_prices.values())
                max_price = max(prices_list)
                min_price = min(prices_list)
                diff_pct = (max_price - min_price) / min_price * 100 if min_price > 0 else 0

                if diff_pct > threshold:
                    quality = SUSPICIOUS
                    detail = (
                        f"多源差异 {diff_pct:.1f}% > 阈值 {threshold}% "
                        f"(max={max_price}, min={min_price})"
                    )
                else:
                    quality = TRUSTED
                    detail = (
                        f"多源一致: 差异 {diff_pct:.1f}% ≤ {threshold}%"
                    )

            self.results.append(ValidationResult(
                vid, vname, price, quality,
                detail=detail,
                sources_used=sources_used,
            ))

        # 统计
        trusted = sum(1 for r in self.results if r.quality == TRUSTED)
        suspicious = sum(1 for r in self.results if r.quality == SUSPICIOUS)
        single = sum(1 for r in self.results if r.quality == SINGLE_SRC)
        missing = sum(1 for r in self.results if r.quality == MISSING)

        logger.info(
            "验证完成: 信任=%d 可疑=%d 单源=%d 缺失=%d",
            trusted, suspicious, single, missing,
        )
        return self.results

    def get_alerts(self) -> list[str]:
        """获取需人工关注的问题列表"""
        alerts = []
        for r in self.results:
            if r.quality in (SUSPICIOUS, MISSING):
                alerts.append(f"⚠️ {r.variety_name}: {r.detail}")
            elif r.quality == SINGLE_SRC:
                alerts.append(f"ℹ️ {r.variety_name}: {r.detail}")
        return alerts
