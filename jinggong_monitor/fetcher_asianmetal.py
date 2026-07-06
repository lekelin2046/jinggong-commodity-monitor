"""亚洲金属网数据抓取器（Cookies 复用 + 自动登录 + OCR 兜底）

定位：闻喜镁锭的**备份数据源**（主源是 SMM 的 WenxiMG 字段）
触发时机：仅当 SMM 闻喜镁抓取失败时才调用本 fetcher

数据来源: asianmetal.cn
目标品种: 闻喜镁锭（99.90%min）

技术路线：
1. 优先用已存 cookies 访问文章页
2. cookies 失效则自动登录（账号密码从 .env 读）
3. 价格表是图片渲染，需 OCR 提取
4. OCR 优先用 OCR.space（key 从 .env 读），无 key 则跳过

注意：本 fetcher 不再硬编码任何路径或密码。
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

from jinggong_monitor.base import BaseFetcher, FetchError
from jinggong_monitor.credentials import require_asianmetal

logger = logging.getLogger("jinggong.fetcher.asianmetal")

# 代理配置
os.environ.setdefault("NO_PROXY", "asianmetal.cn,www.asianmetal.cn,img.asianmetal.cn")
os.environ.setdefault("no_proxy", os.environ["NO_PROXY"])

COOKIE_FILE = Path(__file__).parent.parent / "data" / "asianmetal_cookies.json"
_SHOT_DIR = Path(__file__).parent.parent / "screenshots" / datetime.now().strftime("%Y-%m-%d")

# 镁锭价格历史页（文章列表）
NEWS_LIST_URL = "https://www.asianmetal.cn/MagnesiumPricesHistory"
BASE_URL = "https://www.asianmetal.cn"
LOGIN_URL = "https://www.asianmetal.cn/userlogin"


async def _login_and_save_cookies(ctx) -> bool:
    """登录亚洲金属网并存 cookies"""
    am_user, am_pass = require_asianmetal()
    page = await ctx.new_page()
    try:
        await page.goto(LOGIN_URL, timeout=20000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        # 试多种选择器
        filled_user = False
        for sel in ["input[name='username']", "input[name='userName']", "input[name='user']", "#username", "input[type='text']"]:
            try:
                el = page.locator(sel).first
                if await el.count():
                    await el.fill(am_user, timeout=3000)
                    filled_user = True
                    break
            except Exception:
                continue
        if not filled_user:
            logger.error("找不到用户名输入框")
            return False
        for sel in ["input[name='password']", "input[name='passwd']", "#password", "input[type='password']"]:
            try:
                el = page.locator(sel).first
                if await el.count():
                    await el.fill(am_pass, timeout=3000)
                    break
            except Exception:
                continue
        # 提交
        for sel in ["button[type='submit']", "input[type='submit']", ".login-btn", "#loginBtn", "button"]:
            try:
                el = page.locator(sel).first
                if await el.count():
                    await el.click(timeout=3000)
                    break
            except Exception:
                continue
        await asyncio.sleep(5)
        ok = "login" not in page.url.lower()
        if ok:
            cookies = await ctx.cookies()
            COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
            COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2))
            logger.info(f"亚洲金属网登录成功，cookies 已保存 ({len(cookies)} 个)")
        else:
            logger.error("亚洲金属网登录失败")
        return ok
    finally:
        await page.close()


async def _find_magnesium_article(page) -> Optional[str]:
    """从价格历史页找最新镁锭价格文章"""
    await page.goto(NEWS_LIST_URL, timeout=20000, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)
    links = await page.query_selector_all("a")
    for link in links:
        try:
            title = (await link.inner_text()).strip()
            href = await link.get_attribute("href")
            if not href or "/news/" not in href:
                continue
            # 排除 99.95%min、镁合金、镁粉
            if "99.95" in title or "镁合金" in title or "镁粉" in title:
                continue
            if "镁锭" in title and "价格" in title:
                logger.info(f"选中文章: {title[:40]}")
                return href if href.startswith("http") else BASE_URL + href
        except Exception:
            continue
    return None


def _ocr_image(image_bytes: bytes) -> Optional[float]:
    """用 OCR.space 识别图片中的闻喜镁锭价格

    无 API key 则跳过（返回 None），由调用方降级处理。
    """
    apikey = os.environ.get("OCR_SPACE_APIKEY", "")
    if not apikey:
        logger.warning("未配置 OCR_SPACE_APIKEY，跳过 OCR")
        return None
    import requests
    try:
        resp = requests.post(
            "https://api.ocr.space/parse/image",
            files={"filename": ("img.png", image_bytes, "image/png")},
            data={"language": "chs", "isOverlayRequired": "false"},
            headers={"apikey": apikey},
            timeout=60,
        )
        result = resp.json()
        text = result.get("ParsedResults", [{}])[0].get("ParsedText", "")
        logger.info(f"OCR 结果片段: {text[:200]}")
        # 找闻喜附近的价格
        m = re.search(r'闻喜[\s\S]{0,60}?(\d{2},?\d{3})\s*[-–~]\s*(\d{2},?\d{3})', text)
        if m:
            low = float(m.group(1).replace(",", ""))
            high = float(m.group(2).replace(",", ""))
            if 10000 < low < 50000 and 10000 < high < 50000:
                return round((low + high) / 2, 2)
        return None
    except Exception as e:
        logger.warning(f"OCR 失败: {e}")
        return None


async def _fetch_asianmetal_raw() -> dict:
    """抓取闻喜镁锭价格"""
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = await b.new_context(viewport={"width": 1280, "height": 900}, bypass_csp=True)
            # 加载 cookies
            if COOKIE_FILE.exists():
                cookies = json.loads(COOKIE_FILE.read_text())
                await ctx.add_cookies(cookies)
                logger.info(f"已加载 {len(cookies)} 个 cookies")

            page = await ctx.new_page()
            # 找文章
            article_url = await _find_magnesium_article(page)
            if not article_url:
                logger.warning("未找到镁锭价格文章，尝试重新登录")
                await _login_and_save_cookies(ctx)
                article_url = await _find_magnesium_article(page)
                if not article_url:
                    return {}

            # 打开文章
            logger.info(f"打开文章: {article_url}")
            await page.goto(article_url, timeout=20000, wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)

            # 截图存证（加 timeout 防止 fonts 加载卡死）
            _SHOT_DIR.mkdir(parents=True, exist_ok=True)
            shot_path = _SHOT_DIR / f"asianmetal_闻喜镁_{datetime.now().strftime('%H%M%S')}.png"
            try:
                await page.screenshot(path=str(shot_path), full_page=True, timeout=10000)
                logger.info(f"截图: {shot_path}")
            except Exception as e:
                logger.warning(f"截图失败（不影响价格提取）: {e}")

            # 方法1: HTML 表格提取（价格表是 HTML table 时）
            price = await _extract_from_html(page)
            if price:
                return {"Wenxi_MG": price}

            # 方法2: OCR 图片提取（价格表是图片时）
            logger.info("HTML 无价格，尝试 OCR")
            # 截价格表区域为图片
            price_img = await page.query_selector("img[src*='price'], img[src*='table'], .price-table img, table img")
            if price_img:
                img_bytes = await price_img.screenshot()
                price = _ocr_image(img_bytes)
                if price:
                    return {"Wenxi_MG": price}

            # 方法3: 整页 OCR
            try:
                full_bytes = await page.screenshot(type="png", timeout=10000)
                price = _ocr_image(full_bytes)
                if price:
                    return {"Wenxi_MG": price}
            except Exception as e:
                logger.warning(f"整页截图失败: {e}")

            return {}
        finally:
            await b.close()


async def _extract_from_html(page) -> Optional[float]:
    """从 HTML 表格提取闻喜镁锭价格"""
    data = await page.evaluate("""
    () => {
        const tables = document.querySelectorAll('table');
        for (const t of tables) {
            const rows = t.querySelectorAll('tr');
            for (const row of rows) {
                const cells = row.querySelectorAll('td, th');
                const texts = Array.from(cells).map(c => c.innerText.trim());
                if (texts[0] === '闻喜' && texts[1] === '镁锭' && texts[2] && texts[2].includes('99.9')) {
                    return { price: texts[3] };
                }
            }
        }
        return null;
    }
    """)
    if data and data.get("price"):
        m = re.search(r'(\d[\d,]*)\s*[-–~]\s*(\d[\d,]*)', data["price"])
        if m:
            low = float(m.group(1).replace(",", ""))
            high = float(m.group(2).replace(",", ""))
            if 10000 < low < 50000 and 10000 < high < 50000:
                logger.info(f"HTML 表格提取: {low}-{high}")
                return round((low + high) / 2, 2)
    # 全文正则兜底
    body = await page.inner_text("body")
    m = re.search(r'闻喜[\s\S]{0,40}?镁锭[\s\S]{0,40}?99[.,]9%min[\s\S]{0,40}?(\d[\d,.]+)\s*[-–~]\s*(\d[\d,.]+)', body)
    if m:
        low = float(m.group(1).replace(",", ""))
        high = float(m.group(2).replace(",", ""))
        if 10000 < low < 50000:
            return round((low + high) / 2, 2)
    return None


class AsianmetalFetcher(BaseFetcher):
    """亚洲金属网 — 闻喜镁锭（备份数据源）"""

    source_name = "asianmetal"
    varieties = ["Wenxi_MG"]

    def fetch(self, target_date: Optional[str] = None) -> dict:
        logger.info("=== 亚洲金属网抓取开始（备份源）===")
        try:
            results = asyncio.run(_fetch_asianmetal_raw())
        except Exception as e:
            logger.warning(f"亚洲金属网抓取异常: {e}")
            return {}
        if results:
            logger.info(f"=== 亚洲金属网抓取完成: {results} ===")
        else:
            logger.warning("=== 亚洲金属网抓取失败（闻喜镁锭未拿到）===")
        return results

    def health_check(self) -> bool:
        return True  # 总是可用（会自动登录）


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    fetcher = AsianmetalFetcher()
    data = fetcher.fetch()
    print(f"\n=== 结果: {data} ===")
