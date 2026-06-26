"""CDP 数据源抓取器集合

使用 Chrome DevTools Protocol 抓取需要 JS 渲染的页面。

数据源：
- sci99: 卓创资讯（钢板、不锈钢、铁合金备源）
- bxg: 51bxg 不锈钢（409/439/441 主源）
- smm: SMM 上海有色网（ADC12 主源，A00铝备源）

设计：优先尝试隐藏 JSON API，降级到 CDP。
"""

import json
import logging
import re
from typing import Optional

import requests

from jinggong_monitor.base import BaseFetcher, FetchError

logger = logging.getLogger("jinggong.fetcher.cdp")


class Sci99Fetcher(BaseFetcher):
    """卓创资讯——钢板/不锈钢/铁合金备源"""

    source_name = "sci99"
    varieties = ["AXB", "DXB", "LZB", "SS304", "SS409", "SS439", "SS441", "NPI", "HCRFE"]

    def __init__(self):
        super().__init__()
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        })

    def fetch(self, target_date: Optional[str] = None) -> dict[str, float]:
        """尝试从卓创资讯公开页抓取价格

        卓创是付费平台，公开页数据有限。优先尝试找隐藏 API。
        """
        results = {}

        # 策略1: 尝试找 JSON 价格接口
        api_urls = [
            "https://steel.sci99.com/api/product/galvanized_steel_strip/price",
            "https://scj.sci99.com/api/price/list",
        ]
        for api_url in api_urls:
            try:
                resp = self._session.get(api_url, timeout=10)
                if resp.status_code == 200:
                    data = resp.json() if "json" in resp.headers.get("content-type", "") else {}
                    # 尝试解析 JSON
                    self._parse_json_response(data, results)
                    if results:
                        break
            except Exception:
                continue

        # 策略2: HTML 兜底，尝试从页面文本提取
        if not results:
            try:
                resp = self._session.get(
                    "https://steel.sci99.com/",
                    timeout=15,
                )
                resp.encoding = "utf-8"
                text = resp.text
                # 简单正则匹配价格
                price_patterns = [
                    (r"冷轧板\D*?([\d,]+)\s*元[／/]\s*吨", "LZB"),
                    (r"镀锌板\D*?([\d,]+)\s*元[／/]\s*吨", "DXB"),
                    (r"酸洗板\D*?([\d,]+)\s*元[／/]\s*吨", "AXB"),
                    (r"304\D*?不锈钢\D*?([\d,]+)\s*元[／/]\s*吨", "SS304"),
                    (r"镍[生铁]\D*?([\d,]+)\s*元[／/]\s*镍点", "NPI"),
                ]
                for pattern, vid in price_patterns:
                    m = re.search(pattern, text)
                    if m:
                        try:
                            price = self._parse_price(m.group(1))
                            if price > 0:
                                results[vid] = round(price, 2)
                        except ValueError:
                            continue
            except Exception as e:
                logger.warning("sci99 HTML 解析失败: %s", e)

        self._after_fetch(len(results) > 0)
        if not results:
            self._raise("卓创资讯数据获取失败（需CDP备选方案）")
        return results

    def _parse_json_response(self, data, results: dict):
        """尝试从 JSON 响应中提取价格"""
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    name = item.get("name", item.get("product", ""))
                    price = item.get("price", item.get("close", 0))
                    if name and price:
                        # 品种映射
                        for alias, vid in {
                            "冷轧": "LZB", "镀锌": "DXB", "酸洗": "AXB",
                            "304": "SS304", "409": "SS409", "439": "SS439",
                            "441": "SS441", "镍铁": "NPI", "铬铁": "HCRFE",
                        }.items():
                            if alias in str(name) and float(price) > 0:
                                results[vid] = round(float(price), 2)

    def health_check(self) -> bool:
        try:
            resp = self._session.get("https://steel.sci99.com/", timeout=10)
            return resp.status_code == 200
        except Exception:
            return False


class BxgFetcher(BaseFetcher):
    """51bxg 不锈钢价格抓取"""

    source_name = "bxg"
    varieties = ["SS304", "SS409", "SS439", "SS441"]

    def __init__(self):
        super().__init__()
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        })

    def fetch(self, target_date: Optional[str] = None) -> dict[str, float]:
        """从51bxg抓取不锈钢价格"""
        results = {}

        # 尝试公开价格页面
        try_urls = [
            "https://www.51bxg.com/news/material/",
            "https://www.51bxg.com/quote/",
        ]
        for url in try_urls:
            try:
                resp = self._session.get(url, timeout=15)
                resp.encoding = "utf-8"
                text = resp.text

                patterns = [
                    (r"304/2B\D*?([\d,]+)\s*元[／/]\s*吨", "SS304"),
                    (r"409L\D*?([\d,]+)\s*元[／/]\s*吨", "SS409"),
                    (r"439\D*?([\d,]+)\s*元[／/]\s*吨", "SS439"),
                    (r"441\D*?([\d,]+)\s*元[／/]\s*吨", "SS441"),
                    (r"304\D*?不锈钢\D*?([\d,]+)\s*元[／/]\s*吨", "SS304"),
                ]
                for pattern, vid in patterns:
                    if vid not in results:
                        m = re.search(pattern, text)
                        if m:
                            try:
                                price = self._parse_price(m.group(1))
                                if 5000 < price < 50000:
                                    results[vid] = round(price, 2)
                            except ValueError:
                                continue

                if len(results) >= 2:
                    break
            except Exception as e:
                logger.warning("bxg %s 失败: %s", url, e)

        self._after_fetch(len(results) > 0)
        if not results:
            self._raise("51bxg 数据获取失败（需CDP备选方案）")
        return results

    def health_check(self) -> bool:
        try:
            resp = self._session.get("https://www.51bxg.com/", timeout=10)
            return resp.status_code == 200
        except Exception:
            return False


class SmmFetcher(BaseFetcher):
    """SMM 上海有色网价格抓取"""

    source_name = "smm"
    varieties = ["ADC12", "A00_AL"]

    def __init__(self):
        super().__init__()
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        })

    def fetch(self, target_date: Optional[str] = None) -> dict[str, float]:
        """从SMM公开行情抓取有色价格"""
        results = {}

        try:
            resp = self._session.get(
                "https://hq.smm.cn/aluminum/category/201102250311",
                timeout=15,
            )
            resp.encoding = "utf-8"
            text = resp.text

            # ADC12 铝合金
            for pattern in [
                r"ADC12\D*?([\d,]+)\s*元[／/]\s*吨",
                r"ADC12\s*铝合金\D*?([\d,]+)\s*元[／/]\s*吨",
            ]:
                m = re.search(pattern, text)
                if m:
                    try:
                        price = self._parse_price(m.group(1))
                        if 15000 < price < 30000:
                            results["ADC12"] = round(price, 2)
                            break
                    except ValueError:
                        continue

            # A00 铝
            for pattern in [
                r"A00\D*?([\d,]+)\s*元[／/]\s*吨",
                r"铝\s*[Aa]00\D*?([\d,]+)\s*元[／/]\s*吨",
            ]:
                m = re.search(pattern, text)
                if m:
                    try:
                        price = self._parse_price(m.group(1))
                        if 15000 < price < 30000:
                            results["A00_AL"] = round(price, 2)
                            break
                    except ValueError:
                        continue

        except Exception as e:
            logger.warning("smm HTTP 请求失败: %s", e)

        self._after_fetch(len(results) > 0)
        if not results:
            self._raise("SMM 数据获取失败（需CDP备选方案）")
        return results

    def health_check(self) -> bool:
        try:
            resp = self._session.get("https://hq.smm.cn/", timeout=10)
            return resp.status_code == 200
        except Exception:
            return False
