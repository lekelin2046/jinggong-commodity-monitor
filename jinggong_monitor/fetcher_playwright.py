"""Playwright 浏览器自动化抓取器 v2

经过实测（绕过代理后）：
- steel.sci99.com ✅ 673KB 铬铁/不锈钢行情页
- news.chinatungsten.com ✅ 50KB 钨系每日价格
- 51bxg.com ✅ 84KB 不锈钢首页（但material/子页面404）
- baojia.steelcn.cn ❌ 即使绕过代理也超时

代理绕过：GitHub 加速器等系统代理会阻断国内站点，
解决方法是对 *.sci99.com, *.chinatungsten.com, *.51bxg.com 等域名禁用代理。
"""

import asyncio
import logging
import re
import os
from typing import Optional

from jinggong_monitor.base import BaseFetcher, FetchError

logger = logging.getLogger("jinggong.fetcher.playwright")

# 绕过代理的国内大宗商品域名
_BYPASS_PROXY_DOMAINS = [
    "*.sci99.com", "*.chinatungsten.com", "*.51bxg.com",
    "*.steelcn.cn", "*.zgw.com", "*.ccmn.cn",
    "*.cnfeol.com", "*.ctia.com.cn", "*.smm.cn",
]

# 高碳铬铁参考价格（元/基吨，来源：内部快报）
_HCRFE_REFERENCE = 7403.0


class PlaywrightFetcher(BaseFetcher):
    """Playwright 浏览器自动化抓取（绕过代理连国内站点）"""

    source_name = "playwright"
    varieties = ["HCRFE", "SS409", "SS439", "SS441", "W"]

    def __init__(self):
        super().__init__()
        self._playwright = None
        self._browser = None

    async def _init_browser(self):
        from playwright.async_api import async_playwright
        if self._browser is None:
            self._playwright = await async_playwright().start()
            # 环境变量绕过代理（对 Playwright Chromium 最有效）
            env = os.environ.copy()
            env["NO_PROXY"] = ",".join(_BYPASS_PROXY_DOMAINS)
            env["no_proxy"] = env["NO_PROXY"]
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                env=env,
            )

    async def _close_browser(self):
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def _fetch_page(self, url: str, timeout: int = 15000) -> str:
        """获取页面可见文本（绕过代理）"""
        await self._init_browser()
        # 创建上下文时不设置proxy = 直连
        context = await self._browser.new_context(bypass_csp=True)
        page = await context.new_page()
        try:
            await page.set_extra_http_headers({
                "Accept-Language": "zh-CN,zh;q=0.9",
            })
            await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)
            return await page.inner_text("body")
        finally:
            await page.close()
            await context.close()

    # ================================================================
    # 卓创资讯 - 高碳铬铁涨跌提取
    # ================================================================

    async def _fetch_sci99_chrome(self) -> dict[str, float]:
        """从 steel.sci99.com 提取高碳铬铁涨跌

        页面结构：
          铬铁
          C1000高碳铬铁
          ***              ← 价格被付费墙屏蔽
          中国
          -50/-50          ← 涨跌可见！
        """
        try:
            text = await self._fetch_page(
                "https://steel.sci99.com/chain/nickel_and_stainless_steel",
                timeout=20000,
            )
        except Exception as e:
            logger.warning("sci99 Playwright: %s", e)
            return {}

        if not text or len(text) < 100:
            return {}

        # 找 "C1000高碳铬铁" 后的涨跌
        idx = text.find("C1000高碳铬铁")
        if idx < 0:
            idx = text.find("高碳铬铁")
        if idx < 0:
            return {}

        tail = text[idx:idx + 200]
        change_match = re.search(r"([+-]\d+)\s*/\s*([+-]\d+)", tail)
        if not change_match:
            change_match = re.search(r"([+-]\d+)", tail)

        if change_match:
            changes = [int(change_match.group(1))]
            if change_match.lastindex and change_match.lastindex >= 2:
                changes.append(int(change_match.group(2)))
            avg_change = sum(changes) / len(changes)
            estimated = _HCRFE_REFERENCE + avg_change
            logger.info(
                "sci99 高碳铬铁: 涨跌=%s → 估算=%.0f 元/基吨",
                change_match.group(0), estimated,
            )
            return {"HCRFE": round(estimated, 2)}

        return {}

    # ================================================================
    # 中钨在线 - 钨粉价格提取
    # ================================================================

    async def _fetch_tungsten(self) -> dict[str, float]:
        """从 news.chinatungsten.com 提取钨系价格

        页面：每日一文，HTML格式，纯文本正则提取
        """
        try:
            text = await self._fetch_page(
                "http://news.chinatungsten.com/",
                timeout=15000,
            )
        except Exception as e:
            logger.warning("chinatungsten Playwright: %s", e)
            return {}

        if not text or len(text) < 500:
            return {}

        results = {}

        # 钨粉价格模式（多种写法）
        patterns = [
            (r"钨粉\D*?(?:≥?99\.?7%?\s*)?[:：]?\s*([\d,]+)\s*元[／/]\s*千克", "W"),
            (r"钨粉\D*?([\d,]+)\s*元[／/]\s*千克", "W"),
            (r"碳化钨粉\D*?([\d,]+)\s*元[／/]\s*千克", "W"),
            # APT 作为参考
            (r"APT\D*?([\d,]+)\s*元[／/]\s*吨", "APT"),
        ]

        for pattern, label in patterns:
            m = re.search(pattern, text)
            if m:
                try:
                    price = self._parse_price(m.group(1))
                    if label == "W" and 100 < price < 5000:
                        results["W"] = round(price, 2)
                    elif label == "APT" and 100000 < price < 500000:
                        # APT 价格 / 1000 ≈ 钨粉价格（千克换算参考）
                        if "W" not in results:
                            results["W"] = round(price / 1000, 2)
                except ValueError:
                    continue

        if "W" in results:
            logger.info("中钨在线 钨粉 = %.2f 元/千克", results["W"])
        return results

    # ================================================================
    # 51bxg 不锈钢价格（首页新闻标题提取）
    # ================================================================

    async def _fetch_bxg(self) -> dict[str, float]:
        """从 51bxg 首页提取不锈钢价格"""
        results = {}
        try:
            text = await self._fetch_page("https://www.51bxg.com/", timeout=20000)
        except Exception:
            return results

        # 首页新闻标题如 "德龙冷轧锁价14700元/吨"
        price_refs = re.findall(r"(\d{4,5})\s*元[／/]\s*吨", text)
        if price_refs:
            prices_304 = [int(p) for p in price_refs if 10000 < int(p) < 25000]
            if prices_304:
                # 取中位数作为304参考价
                prices_304.sort()
                mid_304 = prices_304[len(prices_304) // 2]
                results["SS304_BXG"] = float(mid_304)
                logger.info("51bxg 304参考价(新闻): %d 元/吨", mid_304)

        return results

    # ================================================================
    # 统一接口
    # ================================================================

    def fetch(self, target_date: Optional[str] = None) -> dict[str, float]:
        """同步入口"""
        results = {}

        async def _run():
            nonlocal results
            try:
                # 并行抓取
                chrome_task = asyncio.create_task(self._fetch_sci99_chrome())
                tungsten_task = asyncio.create_task(self._fetch_tungsten())
                bxg_task = asyncio.create_task(self._fetch_bxg())

                chrome = await chrome_task
                tungsten = await tungsten_task
                bxg = await bxg_task

                results.update(chrome)
                results.update(tungsten)
                results.update(bxg)
            finally:
                await self._close_browser()

        asyncio.run(_run())
        self._after_fetch(len(results) > 0)
        return results

    def health_check(self) -> bool:
        try:
            async def _check():
                await self._init_browser()
                return self._browser is not None
            return asyncio.run(_check())
        except Exception:
            return False
