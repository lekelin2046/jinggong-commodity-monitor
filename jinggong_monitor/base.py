"""Fetcher 抽象基类

所有数据源抓取器必须实现此接口。
设计目标：新增数据源只需实现 fetch() 和 health_check() 两个方法。
"""

import logging
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger("jinggong.fetcher")


class FetchError(Exception):
    """数据抓取异常"""

    def __init__(self, source: str, detail: str, recoverable: bool = True):
        self.source = source
        self.detail = detail
        self.recoverable = recoverable  # True=可降级, False=致命
        super().__init__(f"[{source}] {detail}")


class BaseFetcher(ABC):
    """数据源抽象基类

    每个 Fetcher 对应一个数据源（如 中钢网、铁合金在线），
    可以覆盖多个品种。
    """

    source_name: str = "base"
    varieties: list[str] = []  # 该数据源覆盖的品种 ID 列表

    def __init__(self):
        self._last_fetch_time: Optional[datetime] = None
        self._last_success: bool = False

    @abstractmethod
    def fetch(self, target_date: Optional[str] = None) -> dict[str, float]:
        """从数据源拉取价格数据

        Args:
            target_date: 目标日期 YYYY-MM-DD，None 为最新

        Returns:
            {品种标准ID: 价格}  eg. {"AXB": 4900.0, "DXB": 6857.0}

        Raises:
            FetchError: 数据源不可用
        """
        ...

    def health_check(self) -> bool:
        """数据源健康检查（默认用上一次 fetch 结果）"""
        return self._last_success

    def _after_fetch(self, success: bool):
        """记录抓取时间戳和状态"""
        self._last_fetch_time = datetime.now()
        self._last_success = success

    def _raise(self, detail: str, recoverable: bool = True):
        raise FetchError(self.source_name, detail, recoverable)

    @staticmethod
    def _parse_price(raw: str) -> float:
        """从字符串中提取价格数字"""
        import re
        raw = raw.strip().replace(",", "").replace("，", "")
        m = re.search(r"[\d.]+", raw)
        if not m:
            raise ValueError(f"无法解析价格: {raw!r}")
        return float(m.group())

    @staticmethod
    def _parse_price_range(raw: str) -> Optional[float]:
        """从价格区间字符串提取中位值

        规则（精工品种通用价格提取口径）：
        - 「16,050-16,150」 / 「16,050–16,150」 / 「16,050~16,150」 → 取中位值 (low+high)/2
        - 「16,050」 单值 → 原样返回
        - 过滤：去除逗号/空格/中文逗号
        - 验证：价格须在 100~1,000,000 之间（避免误匹配小数字）

        Args:
            raw: 价格字符串，例 "16,050-16,150" 或 "16,050"

        Returns:
            中位值 / 单值；解析失败返回 None
        """
        import re
        if not raw:
            return None

        cleaned = raw.strip().replace(",", "").replace("，", "").replace(" ", "")

        # 区间格式：低-高 / 低–高 / 低~高
        range_match = re.match(r"^(\d+(?:\.\d+)?)[-–~](\d+(?:\.\d+)?)$", cleaned)
        if range_match:
            low = float(range_match.group(1))
            high = float(range_match.group(2))
            if low > high:
                low, high = high, low
            if not (100 <= low <= 1_000_000 and 100 <= high <= 1_000_000):
                return None
            return round((low + high) / 2, 2)

        # 单值格式
        single_match = re.match(r"^(\d+(?:\.\d+)?)$", cleaned)
        if single_match:
            value = float(single_match.group(1))
            if 100 <= value <= 1_000_000:
                return value

        return None
