"""中钨在线数据抓取器

实测结果：
- news.chinatungsten.com（中文每日一文）→ 不可达（CONN_REFUSED）
- www.chinatungsten.com（英文门户）→ 可达但无中文价格
- www.ctia.com.cn（中国钨业协会）→ 可达但价格在图表中
- 结论：钨系数据暂无法通过免费HTML提取，使用参考值兜底
"""

import logging
import re
from typing import Optional

import requests

from jinggong_monitor.base import BaseFetcher, FetchError

logger = logging.getLogger("jinggong.fetcher.chinatungsten")

# 钨品种价格正则模式
_PRICE_PATTERNS = {
    "W": [
        # 6/26 主人拍板：取「钨粉价格 X 元/千克」这个表达（不是表里的「钨粉 X」）
        re.compile(r"钨粉价格\s*[:：]?\s*(\d+)\s*元[／/]\s*千克"),
        re.compile(r"钨粉价格\s*(\d+)\s*元[／/]\s*千克"),
        # 兑底：表里只写「钨粉」也行
        re.compile(r"钨粉[^\d]{0,30}?([\d,]+)\s*元[／/]\s*千克"),
        re.compile(r"钨粉\s*(?:≥?99\.?7%)?\s*[:：]?\s*([\d,]+)\s*元[／/]\s*千克"),
        re.compile(r"(?:黑钨|钨)\s*精矿.*?([\d,]+)\s*元[／/]\s*(?:吨|千克)"),
        re.compile(r"APT\s*[:：]?\s*([\d,]+)\s*元[／/]\s*吨"),
    ],
}

# 中钨在线每日文章 URL（一般是当日）
_BASE_URL = "http://news.chinatungsten.com/"
_SECTION_URL = "http://news.chinatungsten.com/cn/tungsten-product-news.html"


class ChinatungstenFetcher(BaseFetcher):
    """中钨在线价格抓取"""

    source_name = "chinatungsten"
    varieties = ["W"]  # 钨粉

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

    def _find_daily_article_url(self) -> Optional[str]:
        """从栏目页找到最新钨价文章 URL

        6/26 主人拍板：入口为 /cn/tungsten-product-news.html 栏目页，
        取第一条 tungsten-product-news/xxx.html 链接（隔日补抓：可能拿到昨日文章）
        """
        try:
            resp = self._session.get(_SECTION_URL, timeout=15)
            resp.encoding = "utf-8"
            html = resp.text

            # 找栏目页第一条 tungsten-product-news/xxx.html 文章
            pattern = re.compile(r'href="(/cn/tungsten-product-news/[^"]+\.html)"')
            matches = pattern.findall(html)
            if matches:
                return "http://news.chinatungsten.com" + matches[0]
        except Exception as e:
            logger.warning("获取中钨在线栏目页失败: %s", e)
        return None

    def _find_candidate_article_urls(self, limit: int = 5) -> list[str]:
        """6/29 主人拍板：题目含「钨」的都要试。取栏目页前 limit 篇。
        有些文章是铟/铂/钼等，不是钨系。遍历到含「钨粉价格」为止。
        """
        try:
            resp = self._session.get(_SECTION_URL, timeout=15)
            resp.encoding = "utf-8"
            html = resp.text
            pattern = re.compile(r'href="(/cn/tungsten-product-news/[^"]+\.html)"')
            matches = pattern.findall(html)[:limit]
            return ["http://news.chinatungsten.com" + m for m in matches]
        except Exception as e:
            logger.warning("获取中钨在线栏目页失败: %s", e)
            return []

    def fetch(self, target_date: Optional[str] = None) -> dict[str, float]:
        """抓取钨系价格。

        6/29 主人拍板：题目含「钨」的都要试，钨粉价格在文章正文里才计入。
        遍历栏目页前 5 篇文章，哪篇含「钨粉价格 X 元/千克」就用哪篇。
        """
        results: dict[str, float] = {}

        # 1. 从栏目页拿多篇含「钨」的文章 URL
        candidate_urls = self._find_candidate_article_urls(limit=5)
        if not candidate_urls:
            # fallback：硬编码最近文章
            from datetime import date
            today = date.today()
            date_strs = [
                today.strftime("%Y%m%d"),
                f"{today.year}-{today.month}-{today.day}",
                f"{today.year}年{today.month}月{today.day}日",
            ]
            for ds in date_strs:
                test_url = f"http://news.chinatungsten.com/cn/tungsten-product-news/175170-tpn-15286.html"
                try:
                    r = self._session.get(test_url, timeout=10)
                    if r.status_code == 200 and "钨" in r.text:
                        candidate_urls = [test_url]
                        break
                except Exception:
                    continue


        if not candidate_urls:
            self._raise("找不到当日中钨在线文章")
            return {}

        # 2. 遍历候选文章，钨粉价格取到就停
        for article_url in candidate_urls:
            try:
                resp = self._session.get(article_url, timeout=15)
                resp.encoding = "utf-8"
                text = resp.text
            except Exception as e:
                logger.warning("获取文章 %s 失败: %s", article_url, e)
                continue

            for variety_id, patterns in _PRICE_PATTERNS.items():
                for pattern in patterns:
                    m = pattern.search(text)
                    if m:
                        try:
                            price = self._parse_price(m.group(1))
                            # 如果是精矿价格按吨计，转成千克
                            if "精矿" in m.group(0) and "吨" in m.group(0) and "千克" not in m.group(0):
                                price = price / 1000
                            results[variety_id] = round(price, 2)
                            logger.info("中钨在线 %s: %.2f (匹配: %s)", variety_id, price, m.group(0)[:80])
                            break
                        except ValueError:
                            continue

            # 钨粉拿到就跳出（这是主要需求）
            if "W" in results:
                self._last_article_url = article_url
                break

        self._after_fetch(len(results) > 0)
        if not results:
            self._raise("未能从文章中提取钨粉价格")
        return results

    def health_check(self) -> bool:
        """快速健康检查"""
        try:
            url = self._find_daily_article_url()
            if url:
                resp = self._session.get(url, timeout=10)
                return resp.status_code == 200 and "钨" in resp.text
        except Exception:
            pass
        # 降级：检查首页可访问
        try:
            resp = self._session.get(_BASE_URL, timeout=10)
            return resp.status_code == 200
        except Exception:
            return False
