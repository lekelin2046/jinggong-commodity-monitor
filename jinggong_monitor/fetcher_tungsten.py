"""中钨在线数据抓取器

实测结果（2026-07-08 复核）：
- www.chinatungsten.com（英文门户 HTTPS）→ TLS/证书已损坏，SSLError: record layer failure，不可用
- news.chinatungsten.com（中文每日价栏目 HTTP）→ 可达，可解析「钨粉价格 X 元/千克」
- 结论：钨粉价格走 http://news.chinatungsten.com/cn/tungsten-product-news.html 栏目页，
  取最新含「钨」的文章正文解析即可（早期注释称 CONN_REFUSED 已过期，现已恢复）。
"""

import logging
import re
from typing import Optional

import requests

from jinggong_monitor.base import BaseFetcher, FetchError

logger = logging.getLogger("jinggong.fetcher.chinatungsten")

# 钨品种价格正则模式
# ⚠️ 只保留「钨粉」本体写法。钨精矿/APT 是另一品种、计价单位「万元/吨」，
# 绝不能拿来当钨粉价（2026-08-04 事故：兜底正则误抓黑钨精矿 → 落 26.0 离谱值）。
_PRICE_PATTERNS = {
    "W": [
        # 6/26 主人拍板：取「钨粉价格 X 元/千克」这个表达（不是表里的「钨粉 X」）
        re.compile(r"钨粉价格\s*[:：]?\s*([\d,]+)\s*元[／/]\s*千克"),
        # 兑底：表里只写「钨粉」也行
        re.compile(r"钨粉[^\d]{0,30}?([\d,]+)\s*元[／/]\s*千克"),
        re.compile(r"钨粉\s*(?:≥?99\.?7%)?\s*[:：]?\s*([\d,]+)\s*元[／/]\s*千克"),
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

    def _get(self, url: str, timeout: int = 15, _retry: bool = True):
        """带代理容错的 GET。

        环境里设了 HTTP_PROXY/HTTPS_PROXY=127.0.0.1:7890（本机代理）。
        若代理临时不可用（连不上/超时），自动改用直连重试，避免「钨粉」因
        代理抖动而整列缺失（2026-07-28 即因此超时失败）。
        """
        try:
            return self._session.get(url, timeout=timeout)
        except requests.exceptions.RequestException as e:
            if not _retry:
                raise
            logger.warning("代理请求失败(%s)，改用直连重试: %s", type(e).__name__, e)
            try:
                return self._session.get(
                    url, timeout=timeout, proxies={"http": None, "https": None}
                )
            except requests.exceptions.RequestException as e2:
                logger.warning("直连也失败: %s", e2)
                raise

    def _find_daily_article_url(self) -> Optional[str]:
        """从栏目页找到最新钨价文章 URL

        6/26 主人拍板：入口为 /cn/tungsten-product-news.html 栏目页，
        取第一条 tungsten-product-news/xxx.html 链接（隔日补抓：可能拿到昨日文章）
        """
        try:
            resp = self._get(_SECTION_URL, timeout=15)
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

    def _find_candidate_article_urls(self, limit: int = 8) -> list[str]:
        """6/29 主人拍板：题目含「钨」的都要试。取栏目页前 limit 篇。
        有些文章是铟/铂/钼等，不是钨系。遍历到含「钨粉价格」为止。

        ⚠️ 必须去重：栏目页同一链接会在「列表区」和「翻页/相关区」各出现一次，
        findall 会把重复 URL 各算一条，白白吃掉 limit 预算，把真正含「钨粉价格」
        的文章挤出前 N 条（2026-08-04 事故根因）。
        """
        try:
            resp = self._get(_SECTION_URL, timeout=15)
            resp.encoding = "utf-8"
            html = resp.text
            pattern = re.compile(r'href="(/cn/tungsten-product-news/[^"]+\.html)"')
            seen: set[str] = set()
            unique: list[str] = []
            for m in pattern.findall(html):
                if m in seen:
                    continue
                seen.add(m)
                unique.append("http://news.chinatungsten.com" + m)
                if len(unique) >= limit:
                    break
            return unique
        except Exception as e:
            logger.warning("获取中钨在线栏目页失败: %s", e)
            return []

    def fetch(self, target_date: Optional[str] = None) -> dict[str, float]:
        """抓取钨系价格。

        6/29 主人拍板：题目含「钨」的都要试，钨粉价格在文章正文里才计入。
        遍历栏目页前 5 篇文章，哪篇含「钨粉价格 X 元/千克」就用哪篇。
        """
        results: dict[str, float] = {}

        # 0. 先探栏目页健康度，区分「网站故障」与「无文章」
        #    2026-09-04 实测：网站数据库挂掉时栏目页返回
        #    "Database connection error (2): Could not connect to MySQL"，
        #    此时应明确报源站故障、引导走微信专辑页人工兜底，
        #    而非含糊的「找不到当日文章」（曾导致人工误判为 fetcher bug）。
        try:
            probe = self._get(_SECTION_URL, timeout=15)
            probe.encoding = "utf-8"
            if "Database connection error" in probe.text or "Could not connect" in probe.text:
                self._raise(
                    "中钨在线网站数据库故障（MySQL error），钨粉源暂不可用；"
                    "请走微信专辑页人工兜底（取当日「中颗粒钨粉」万元/吨 ÷1000 回填）"
                )
                return {}
        except Exception:
            pass  # 网络异常交给后续正常流程处理

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
                    r = self._get(test_url, timeout=10)
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
                resp = self._get(article_url, timeout=15)
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
                resp = self._get(url, timeout=10)
                return resp.status_code == 200 and "钨" in resp.text
        except Exception:
            pass
        # 降级：检查首页可访问
        try:
            resp = self._get(_BASE_URL, timeout=10)
            return resp.status_code == 200
        except Exception:
            return False
