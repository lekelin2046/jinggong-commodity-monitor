"""亚洲金属网数据抓取器

通过 CDP 连接用户已登录的 Chrome，抓取新闻详情页中的镁锭价格。

数据来源: asianmetal.cn
目标品种: 闻喜镁锭（99.90%min）
"""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from jinggong_monitor.base import BaseFetcher, FetchError

logger = logging.getLogger("jinggong.fetcher.asianmetal")

# 6/29 主人拍板：保存抓取现场（供后期追溯）
_SHOT_DIR = Path("/Users/siqi/Desktop/AI/jinggong-commodity-monitor/screenshots") / datetime.now().strftime("%Y-%m-%d")
_SHOT_DIR.mkdir(parents=True, exist_ok=True)


class AsianmetalFetcher(BaseFetcher):
    """亚洲金属网 — 闻喜镁锭价格"""

    source_name = "asianmetal"
    varieties = ["Wenxi_MG"]

    # 镁锭新闻列表页
    NEWS_LIST_URL = "https://www.asianmetal.cn/product/data/mj/40/civilPrice/"
    BASE_URL = "https://www.asianmetal.cn"
    CDP_URL = "http://localhost:9223"

    async def _fetch_via_cdp(self) -> dict[str, float]:
        """CDP 连接用户 Chrome 抓取亚洲金属网镁锭价格"""
        from playwright.async_api import async_playwright

        results = {}
        async with async_playwright() as p:
            try:
                browser = await p.chromium.connect_over_cdp(self.CDP_URL)
            except Exception as e:
                self._raise(f"CDP 连接失败（端口 9223）: {e}")
                return results

            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()

            try:
                # Step 1: 打开镁锭新闻列表页
                logger.info("打开亚洲金属网镁锭新闻列表...")
                await page.goto(
                    self.NEWS_LIST_URL,
                    timeout=20000,
                    wait_until="domcontentloaded",
                )
                await page.wait_for_timeout(3000)

                # 检查是否需要登录（页面会跳转到登录提示）
                current_url = page.url
                page_text = await page.inner_text("body")

                if "返回登录" in page_text or "login" in current_url.lower():
                    # 📸 失败现场截图（未登录）
                    try:
                        await page.wait_for_timeout(800)
                        await page.screenshot(path=str(_SHOT_DIR / f"❌_asianmetal_未登录_{datetime.now().strftime('%H%M%S')}.png"), full_page=True)
                    except Exception:
                        pass
                    self._raise(
                        "亚洲金属网未登录。请在调试Chrome中手动登录：\n"
                        "  1. 打开 https://www.asianmetal.cn/\n"
                        "  2. 点击「登录」\n"
                        "  3. 输入账号密码\n"
                        "  登录后重新运行脚本"
                    )
                    return results

                # Step 2: 找到今日或最新的镁锭文章链接
                article_url = await self._find_magnesium_article(page)
                if not article_url:
                    self._raise("未找到镁锭价格文章")
                    return results

                # Step 3: 打开文章详情页，提取价格
                logger.info("打开文章: %s", article_url)
                await page.goto(article_url, timeout=20000, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)

                # 检查是否又是登录页
                title_text = await page.title()
                if "登录" in title_text or "返回登录" in title_text:
                    # 📸 失败现场截图
                    try:
                        await page.wait_for_timeout(800)
                        await page.screenshot(path=str(_SHOT_DIR / f"❌_asianmetal_登录页_{datetime.now().strftime('%H%M%S')}.png"), full_page=True)
                    except Exception:
                        pass
                    self._raise("文章详情页需要登录，请确认已登录亚洲金属网")
                    return results

                # 📸 6/29 主人拍板：抓取成功截文章页
                try:
                    await page.wait_for_timeout(800)
                    # 亚洲金属网是文章页（无 <table>），全页截图保留日期+正文+表格
                    await page.screenshot(
                        path=str(_SHOT_DIR / f"asianmetal_闻喜镁錠_{datetime.now().strftime('%H%M%S')}.png"),
                        full_page=True,
                    )
                    logger.info("📸 亚洲金属网文章页截图 OK")
                except Exception as e:
                    logger.warning(f"亚洲金属网截图失败: {e}")

                # Step 4: 从文章表格中提取闻喜镁锭价格（JS 按表格行提取）
                price = await self._extract_wenxi_from_table(page)
                if price:
                    results["Wenxi_MG"] = price
                    logger.info("亚洲金属网 闻喜镁锭: %.0f 元/吨", price)
                else:
                    # 备选：从全文文本中正则
                    article_text = await page.inner_text("body")
                    price = self._extract_wenxi_price(article_text)
                    if price:
                        results["Wenxi_MG"] = price
                        logger.info("亚洲金属网 闻喜镁锭（文本备选）: %.0f 元/吨", price)
                    else:
                        self._raise("未找到闻喜镁锭价格（表格+文本均失败）")

            finally:
                await page.close()

        return results

    async def _extract_wenxi_from_table(self, page) -> Optional[float]:
        """从文章表格中提取闻喜镁锭价格（取高低两价中位值）

        表格结构：地区|品名|规格|价格|增减|单位|方式
        闻喜行：闻喜|镁锭|99.9%min|16,050-16,150|-50|元/吨|出厂价

        口径：「价格」列两个数取中间值 (16,050+16,150)/2 = 16,100
        """
        # 查找包含「闻喜」+「镁锭」的表格，提取价格列
        data = await page.evaluate("""
        () => {
            const tables = document.querySelectorAll('table');
            for (const t of tables) {
                const text = t.innerText;
                if (text.includes('闻喜') && text.includes('镁锭') && text.includes('99.9%min')) {
                    const rows = text.split('\\n').map(r => r.split('\\t').map(c => c.trim()));
                    for (const row of rows) {
                        if (row[0] === '闻喜' && row[1] === '镁锭' && row[2] === '99.9%min') {
                            return {
                                region: row[0],
                                product: row[1],
                                spec: row[2],
                                price: row[3],
                                change: row[4],
                                unit: row[5],
                                way: row[6]
                            };
                        }
                    }
                }
            }
            return null;
        }
        """)
        if not data:
            return None

        price_str = data.get("price", "")
        if not price_str:
            return None

        # 使用 BaseFetcher 通用规则：区间取中位值
        parsed = self._parse_price_range(price_str)
        if parsed:
            logger.info("闻喜镁锭价格: %s → %.2f 元/吨", price_str, parsed)
        return parsed

    async def _find_magnesium_article(self, page) -> Optional[str]:
        """从新闻列表中找最新的镁锭（99.9%min）文章 URL

        跳过：镁合金、镁粉、镁锭99.95%min（不同品类）
        选中：第一篇含「镁锭」+「价格」的文章
        """
        links = await page.query_selector_all("a[href*='/news/']")

        for link in links:
            try:
                title = (await link.inner_text()).strip()
                href = await link.get_attribute("href")
                if not href or not title:
                    continue

                # 跳过 99.95%min（不同品类）
                if "99.95%min" in title:
                    continue

                # 跳过 镁合金 / 镁粉
                if "镁合金" in title or "镁粉" in title:
                    continue

                # 选中：镁锭 + 价格
                if "镁锭" in title and "价格" in title:
                    logger.info("选中镁锭文章: %s | %s", title[:40], href)
                    return self._normalize_url(href)

            except Exception:
                continue

        return None

    def _normalize_url(self, href: str) -> str:
        """补全相对路径"""
        if href.startswith("http"):
            return href
        return self.BASE_URL + href

    def _extract_wenxi_price(self, text: str) -> Optional[float]:
        """从文章文本中提取闻喜镁锭价格（取高低两个数的中间值）

        文章格式（表格）：
          闻喜	镁锭	99.9%min	16,050-16,150	-50	元/吨	出厂价

        要求：必须是「闻喜」+「镁锭」+「99.9%min」同行的价格区间，取中位值。
        """
        # 严格匹配：同一行包含 闻喜 + 镁锭 + 99.9%min + 价格区间
        # 表格列用 tab 或多个空格分隔
        wenxi_row = re.search(
            r'闻喜[\s\S]{0,30}?镁锭[\s\S]{0,30}?99[\.,]9%min[\s\S]{0,30}?'
            r'(\d[\d,\.]+)\s*[-–~]\s*(\d[\d,\.]+)',
            text,
        )
        if wenxi_row:
            low = self._parse_price_str(wenxi_row.group(1))
            high = self._parse_price_str(wenxi_row.group(2))
            if low and high and 10000 < low < 50000 and 10000 < high < 50000:
                mid = round((low + high) / 2, 2)
                logger.info(
                    "闻喜镁锭价格区间: %s-%s → 中位值 %.2f",
                    wenxi_row.group(1), wenxi_row.group(2), mid,
                )
                return mid

        # 备选：闻喜行带单值
        wenxi_single = re.search(
            r'闻喜[\s\S]{0,50}?(\d[\d,\.]+)',
            text,
        )
        if wenxi_single:
            price = self._parse_price_str(wenxi_single.group(1))
            if price and 10000 < price < 50000:
                return price

        return None

    def _parse_price_str(self, s: str) -> Optional[float]:
        """解析价格字符串（处理逗号/空格）"""
        try:
            cleaned = s.replace(",", "").replace("，", "").replace(" ", "")
            return float(cleaned)
        except (ValueError, TypeError):
            return None

    def fetch(self, target_date: Optional[str] = None) -> dict[str, float]:
        """同步入口"""

        async def _run():
            return await self._fetch_via_cdp()

        results = asyncio.run(_run())
        self._after_fetch(len(results) > 0)
        return results

    def health_check(self) -> bool:
        """检查 CDP 端口和亚洲金属网可达性"""
        import requests
        try:
            resp = requests.get(
                "http://localhost:9222/json/version",
                timeout=5,
            )
            return resp.status_code == 200
        except Exception:
            return False
