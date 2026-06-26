"""中钢网数据抓取器（钢板类主源）

数据源: baojia.steelcn.cn / zgw.com
方式: requests + BeautifulSoup

覆盖品种：酸洗板、镀锌板、冷轧板、热卷
"""

import logging
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

from jinggong_monitor.base import BaseFetcher

logger = logging.getLogger("jinggong.fetcher.zgw")

# 品种名 → 标准 ID
_NAME_ALIASES = {
    "酸洗板": "AXB",
    "酸洗": "AXB",
    "镀锌板": "DXB",
    "镀锌": "DXB",
    "冷轧板": "LZB",
    "冷轧": "LZB",
    "热轧板": "HC",
    "热卷": "HC",
}

# 城市优先级（找全国均价/重点城市）
_CITY_PRIORITY = ["全国", "上海", "天津", "广州", "乐从", "邯郸", "北京"]

_BASE_URL = "https://baojia.steelcn.cn/"


class ZgwFetcher(BaseFetcher):
    """中钢网价格抓取——钢板类主数据源"""

    source_name = "zgw"
    varieties = ["AXB", "DXB", "LZB"]

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
        """从中钢网抓取钢板价格

        策略：
        1. 主站报价页
        2. 品种详情页
        3. 搜索页面
        """
        results = {}

        # 策略1: 报价首页
        try:
            resp = self._session.get(_BASE_URL, timeout=15)
            resp.encoding = "utf-8"
            results.update(self._parse_page(resp.text, source="首页"))
        except Exception as e:
            logger.warning("zgw 首页失败: %s", e)

        # 策略2: 逐个品种详情页
        detail_pages = {
            "AXB": "https://www.zgw.com/hq/sx/",          # 酸洗板
            "DXB": "https://www.zgw.com/hq/dx/",          # 镀锌板
            "LZB": "https://www.zgw.com/hq/lz/",          # 冷轧板
        }
        for variety_id, url in detail_pages.items():
            if variety_id in results:
                continue  # 已从首页获取
            try:
                resp = self._session.get(url, timeout=15)
                resp.encoding = "utf-8"
                sub = self._parse_page(resp.text, source="详情页")
                if variety_id in sub:
                    results[variety_id] = sub[variety_id]
            except Exception as e:
                logger.warning("zgw %s 详情页失败: %s", variety_id, e)

        self._after_fetch(len(results) > 0)
        if not results:
            self._raise("中钢网数据获取失败")
        return results

    def _parse_page(self, html: str, source: str = "") -> dict[str, float]:
        """解析 HTML 页面中的价格数据"""
        results = {}
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text()

        for alias, variety_id in _NAME_ALIASES.items():
            if variety_id in results:
                continue

            # 方法1: 找表格行
            for row in soup.find_all("tr"):
                row_text = row.get_text(strip=True)
                if alias in row_text:
                    cells = row.find_all(["td", "th"])
                    for cell in cells:
                        cell_text = cell.get_text(strip=True)
                        # 检查是否包含价格（¥ 或 数字+城市）
                        if re.search(r"[¥￥]", cell_text) or re.search(r"^\d{3,5}$", cell_text):
                            try:
                                price = self._parse_price(cell_text)
                                if 3000 < price < 20000:  # 钢板合理价格区间
                                    results[variety_id] = round(price, 2)
                                    logger.info(
                                        "zgw %s = %.2f (from %s)", variety_id, price, source
                                    )
                                    break
                            except ValueError:
                                continue

            # 方法2: 正则兜底
            if variety_id not in results:
                # 匹配 "酸洗板 4900" 这样的模式
                pattern = re.compile(
                    rf"{re.escape(alias)}[^\d]*?([\d,]+)\s*(?:元[／/]\s*吨)?"
                )
                m = pattern.search(text)
                if m:
                    try:
                        price = self._parse_price(m.group(1))
                        if 3000 < price < 20000:
                            results[variety_id] = round(price, 2)
                    except ValueError:
                        pass

        return results

    def health_check(self) -> bool:
        """快速健康检查"""
        try:
            resp = self._session.get(_BASE_URL, timeout=10)
            return resp.status_code == 200
        except Exception:
            return False
