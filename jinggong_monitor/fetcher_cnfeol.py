"""中国铁合金在线数据抓取器（高碳铬铁主源）

数据源: cnfeol.com（中国铁合金在线）
方式: requests + BeautifulSoup

覆盖品种：高碳铬铁（内蒙）、低碳铬铁、微碳铬铁
"""

import logging
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

from jinggong_monitor.base import BaseFetcher

logger = logging.getLogger("jinggong.fetcher.cnfeol")

# 品种名 → 标准 ID
_NAME_ALIASES = {
    "高碳铬铁": "HCRFE",
    "高铬": "HCRFE",
    "铬铁": "HCRFE",
    "低碳铬铁": "LCRFE",
    "微碳铬铁": "MCRFE",
}

# 地区关键词
_REGION_KEYWORDS = ["内蒙", "内蒙古", "全国"]

_URLS = [
    "https://www.cnfeol.com/",
    "https://www.cnfeol.com/hangqing/",
    "https://www.cnfeol.com/ge/",  # 铬系频道
]


class CnfeolFetcher(BaseFetcher):
    """中国铁合金在线价格抓取——高碳铬铁主数据源"""

    source_name = "cnfeol"
    varieties = ["HCRFE"]

    def __init__(self):
        super().__init__()
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    def fetch(self, target_date: Optional[str] = None) -> dict[str, float]:
        """从铁合金在线抓取高碳铬铁价格"""
        results = {}

        for url in _URLS:
            try:
                resp = self._session.get(url, timeout=15)
                resp.encoding = "gb2312" if "gb" in str(resp.apparent_encoding).lower() else "utf-8"
                page_results = self._parse_page(resp.text)
                results.update(page_results)
                if "HCRFE" in results:
                    break
            except Exception as e:
                logger.warning("cnfeol %s 失败: %s", url, e)

        self._after_fetch("HCRFE" in results)
        if "HCRFE" not in results:
            self._raise("铁合金在线高碳铬铁数据获取失败")
        return results

    def _parse_page(self, html: str) -> dict[str, float]:
        """解析 HTML 中的铬铁价格"""
        results = {}
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text()

        # 方法1: 表格行解析
        for row in soup.find_all("tr"):
            row_text = row.get_text(strip=True)
            # 检查是否包含铬铁相关关键词
            if not any(kw in row_text for kw in ["铬铁", "铬"]):
                continue

            # 检查是否包含地区
            has_region = any(r in row_text for r in _REGION_KEYWORDS)
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]

            for i, cell in enumerate(cells):
                # 品种匹配
                matched_id = None
                for alias, vid in _NAME_ALIASES.items():
                    if alias in cell and vid not in results:
                        matched_id = vid
                        break
                if not matched_id:
                    continue

                # 找价格（同行后续单元格或当前格）
                search_cells = cells[i:] if i < len(cells) - 1 else [cell]
                for sc in search_cells:
                    try:
                        price = self._parse_price(sc)
                        if 5000 < price < 50000:  # 铬铁合理区间 元/基吨
                            # 优先选取含地区的结果
                            if matched_id not in results or has_region:
                                results[matched_id] = round(price, 2)
                                logger.info(
                                    "cnfeol %s = %.2f (region=%s)",
                                    matched_id, price, has_region
                                )
                            break
                    except ValueError:
                        continue

        # 方法2: 纯文本正则兜底
        if "HCRFE" not in results:
            patterns = [
                r"高碳铬铁[^\d]*?(?:内蒙[^\d]*?)?([\d,]+)\s*元[／/]\s*(?:基吨|吨)",
                r"高铬[^\d]*?([\d,]+)\s*元[／/]\s*(?:基吨|吨)",
                r"(?:内蒙|内蒙古)[^\d]*?铬铁[^\d]*?([\d,]+)\s*元[／/]\s*(?:基吨|吨)",
            ]
            for pattern in patterns:
                m = re.search(pattern, text)
                if m:
                    try:
                        price = self._parse_price(m.group(1))
                        if 5000 < price < 50000:
                            results["HCRFE"] = round(price, 2)
                            break
                    except ValueError:
                        continue

        return results

    def health_check(self) -> bool:
        """快速健康检查"""
        try:
            resp = self._session.get("https://www.cnfeol.com/", timeout=10)
            return resp.status_code == 200
        except Exception:
            return False
