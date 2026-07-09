"""亚洲金属网数据抓取器（Cookies 复用 + 弹窗自动登录 + HTML 表格提取）

数据来源: asianmetal.cn
目标品种: 闻喜镁锭（99.90%min）

技术路线：
1. 访问镁锭历史价格页，找到最新的"中国镁锭价格分区域"文章。
2. 用已存 cookies 访问文章页；cookies 失效时在当前页面弹窗登录。
3. 登录后价格表为 HTML table，直接解析闻喜行，无需 OCR。
4. 仅当 HTML 表格解析失败且本地已安装 PaddleOCR 时，才做本地 OCR 兜底。

注意：
- 本 fetcher 不再硬编码任何路径或密码。
- 不再依赖 OCR.space 等外部免费 OCR API。
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

from jinggong_monitor.base import BaseFetcher
from jinggong_monitor.credentials import require_asianmetal

logger = logging.getLogger("jinggong.fetcher.asianmetal")

# 代理配置（防止代理拦截国内站点）
os.environ.setdefault("NO_PROXY", "asianmetal.cn,www.asianmetal.cn,img.asianmetal.cn")
os.environ.setdefault("no_proxy", os.environ["NO_PROXY"])

COOKIE_FILE = Path(__file__).parent.parent / "data" / "asianmetal_cookies.json"
_SHOT_DIR = Path(__file__).parent.parent / "screenshots" / datetime.now().strftime("%Y-%m-%d")

# 镁锭历史价格页（文章列表，无需登录即可访问）
NEWS_LIST_URL = "https://www.asianmetal.cn/MagnesiumIngotPricesHistory"
BASE_URL = "https://www.asianmetal.cn"

# 登录弹窗选择器
_LOGIN_POPUP = "#loginWin"
_LOGIN_USER = "#cnopenloginname"
_LOGIN_PWD = "#cnopenloginpwd"
_LOGIN_BTN = "#openloginbutn"
_LOGIN_TOP_LINK = "#loginbox a, #loginbox span"

# 弹窗中的成功提示
_LOGIN_SUCCESS_TEXT = "您已经成功登陆"


async def _save_cookies(ctx) -> None:
    """将当前 context 的 cookies 保存到文件。"""
    try:
        cookies = await ctx.cookies()
        COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2))
        logger.info(f"cookies 已保存 ({len(cookies)} 个)")
    except Exception as e:
        logger.warning(f"保存 cookies 失败: {e}")


async def _load_cookies(ctx) -> None:
    """加载已存 cookies 到当前 context。"""
    if not COOKIE_FILE.exists():
        return
    try:
        cookies = json.loads(COOKIE_FILE.read_text())
        await ctx.add_cookies(cookies)
        logger.info(f"已加载 {len(cookies)} 个 cookies")
    except Exception as e:
        logger.warning(f"加载 cookies 失败: {e}")


async def _login_in_popup(page) -> bool:
    """在当前页面触发登录弹窗并登录。

    适用于文章页被重定向到首页并弹出登录框的场景。
    登录成功后页面会自动刷新，当前 page 对象即代表登录后的页面。
    """
    am_user, am_pass = require_asianmetal()
    try:
        # 先登出，避免"此用户已在线"(-50)
        try:
            await page.goto("https://www.asianmetal.cn/login/logout.am", timeout=15000, wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)
        except Exception as e:
            logger.debug(f"登出请求失败（可忽略）: {e}")

        # 打开首页触发弹窗
        await page.goto(BASE_URL, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # 如果弹窗还没出现，点击顶部登录链接触发
        try:
            popup = page.locator(_LOGIN_POPUP)
            if await popup.count() == 0 or not await popup.is_visible():
                await page.locator(_LOGIN_TOP_LINK).first.click(timeout=5000)
        except Exception as e:
            logger.debug(f"点击顶部登录链接失败（弹窗可能已存在）: {e}")

        await page.wait_for_selector(_LOGIN_POPUP, state="visible", timeout=10000)
        await page.locator(_LOGIN_USER).fill(am_user, timeout=5000)
        await page.locator(_LOGIN_PWD).fill(am_pass, timeout=5000)

        await page.locator(_LOGIN_BTN).click(timeout=5000)
        await asyncio.sleep(1)

        # 等待登录成功提示出现，最多 20 秒
        for i in range(20):
            await asyncio.sleep(1)
            try:
                body = await page.inner_text("body", timeout=2000)
                if _LOGIN_SUCCESS_TEXT in body:
                    logger.info("登录成功提示出现")
                    break
            except Exception:
                continue
        else:
            logger.warning("未看到登录成功提示，继续等待页面刷新")

        # 登录成功后 cookies 已设置，无需点击确定按钮。
        # 直接返回，由调用方重新访问文章页。
        await asyncio.sleep(5)
        return True
    except Exception as e:
        logger.error(f"弹窗登录失败: {e}")
        return False


async def _find_magnesium_article(page) -> Optional[str]:
    """从镁锭历史价格页找最新的镁锭分区域价格文章。"""
    await page.goto(NEWS_LIST_URL, timeout=30000, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)
    links = await page.query_selector_all("a")
    for link in links:
        try:
            title = (await link.inner_text()).strip()
            href = await link.get_attribute("href")
            if not href or "/news/" not in href:
                continue
            # 排除 99.95%min、镁合金、镁粉、镁阳极等
            if "99.95" in title or "镁合金" in title or "镁粉" in title or "镁阳极" in title:
                continue
            if "镁锭" in title and "价格" in title and "分区域" in title:
                logger.info(f"选中文章: {title[:60]}")
                return href if href.startswith("http") else BASE_URL + href
        except Exception:
            continue
    return None


async def _extract_from_html(page) -> Optional[float]:
    """从 HTML 表格提取闻喜镁锭价格（99.9%min）。"""
    data = await page.evaluate("""
    () => {
        const tables = document.querySelectorAll('table');
        for (const t of tables) {
            const rows = t.querySelectorAll('tr');
            for (const row of rows) {
                const cells = row.querySelectorAll('td, th');
                const texts = Array.from(cells).map(c => c.innerText.trim());
                if (texts.length < 4) continue;
                const region = texts[0];
                const product = texts[1];
                const spec = texts[2];
                const price = texts[3];
                if (region === '闻喜' && product && product.includes('镁') && spec && spec.includes('99.9')) {
                    return { price: price, row: texts };
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
    patterns = [
        r'闻喜[\s\S]{0,30}?镁[\s\S]{0,30}?99[.,]9%min[\s\S]{0,60}?(\d[\d,.]+)\s*[-–~]\s*(\d[\d,.]+)',
        r'闻喜[\s\S]{0,40}?(\d[\d,.]+)\s*[-–~]\s*(\d[\d,.]+)',
    ]
    for pat in patterns:
        m = re.search(pat, body)
        if m:
            low = float(m.group(1).replace(",", ""))
            high = float(m.group(2).replace(",", ""))
            if 10000 < low < 50000 and 10000 < high < 50000:
                logger.info(f"HTML 正则提取: {low}-{high}")
                return round((low + high) / 2, 2)
    return None


def _ocr_local(image_bytes: bytes) -> Optional[float]:
    """本地 OCR 兜底（PaddleOCR），仅在已安装时使用。

    不依赖外部免费 OCR API，符合项目安全约束。
    """
    try:
        from paddleocr import PaddleOCR
    except Exception:
        logger.debug("未安装 PaddleOCR，跳过本地 OCR 兜底")
        return None

    try:
        import tempfile
        ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(image_bytes)
            tmp_path = f.name
        try:
            result = ocr.ocr(tmp_path, cls=True)
            texts = []
            if result and result[0]:
                for line in result[0]:
                    if line:
                        texts.append(line[1][0])
            text = "\n".join(texts)
            logger.info(f"本地 OCR 结果片段: {text[:200]}")
            m = re.search(r'闻喜[\s\S]{0,60}?(\d[\d,.]+)\s*[-–~]\s*(\d[\d,.]+)', text)
            if m:
                low = float(m.group(1).replace(",", ""))
                high = float(m.group(2).replace(",", ""))
                if 10000 < low < 50000 and 10000 < high < 50000:
                    return round((low + high) / 2, 2)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"本地 OCR 失败: {e}")
    return None


async def fetch_async(target_date: Optional[str] = None) -> dict:
    """异步抓取闻喜镁锭价格（供已有事件循环调用）。"""
    return await _fetch_asianmetal_raw()


async def _fetch_asianmetal_raw() -> dict:
    """抓取闻喜镁锭价格。"""
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = await b.new_context(viewport={"width": 1280, "height": 900}, bypass_csp=True)
            await _load_cookies(ctx)

            page = await ctx.new_page()

            # 找最新文章
            article_url = await _find_magnesium_article(page)
            if not article_url:
                logger.warning("未找到镁锭价格文章")
                return {}

            # 打开文章页
            logger.info(f"打开文章: {article_url}")
            await page.goto(article_url, timeout=60000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            logger.info(f"当前 URL: {page.url}")

            # 如果需要登录，在当前页面弹窗登录
            if "index.shtml" in page.url or "login" in page.url.lower():
                logger.info("需要登录，尝试弹窗登录...")
                ok = await _login_in_popup(page)
                if not ok:
                    return {}
                logger.info(f"登录后 URL: {page.url}")
                # 如果登录后不在文章页，重新访问（注意 r=/news/xxx 参数会误匹配，所以用路径判断）
                url_path = page.url.replace(BASE_URL, "").split("?")[0]
                if not url_path.startswith("/news/"):
                    await page.goto(article_url, timeout=30000, wait_until="domcontentloaded")
                    await page.wait_for_timeout(3000)
                    logger.info(f"重新访问后 URL: {page.url}")
                    url_path2 = page.url.replace(BASE_URL, "").split("?")[0]
                    if not url_path2.startswith("/news/"):
                        logger.error("登录后仍无法访问文章页")
                        return {}

            # 保存 cookies（无论是否刚登录，都更新一次）
            await _save_cookies(ctx)

            # 截图存证
            _SHOT_DIR.mkdir(parents=True, exist_ok=True)
            shot_path = _SHOT_DIR / f"asianmetal_闻喜镁_{datetime.now().strftime('%H%M%S')}.png"
            try:
                await page.screenshot(path=str(shot_path), full_page=True, timeout=10000)
                logger.info(f"截图: {shot_path}")
            except Exception as e:
                logger.warning(f"截图失败（不影响价格提取）: {e}")

            # 方法1: HTML 表格提取
            price = await _extract_from_html(page)
            if price:
                return {"Wenxi_MG": price}

            # 方法2: 本地 OCR 兜底
            logger.info("HTML 未提取到价格，尝试本地 OCR 兜底")
            try:
                full_bytes = await page.screenshot(type="png", timeout=10000)
                price = _ocr_local(full_bytes)
                if price:
                    return {"Wenxi_MG": price}
            except Exception as e:
                logger.warning(f"本地 OCR 截图失败: {e}")

            return {}
        finally:
            await b.close()


class AsianmetalFetcher(BaseFetcher):
    """亚洲金属网 — 闻喜镁锭（主数据源）。"""

    source_name = "asianmetal"
    varieties = ["Wenxi_MG"]

    def fetch(self, target_date: Optional[str] = None) -> dict:
        logger.info("=== 亚洲金属网抓取开始 ===")
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
        return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    fetcher = AsianmetalFetcher()
    data = fetcher.fetch()
    print(f"\n=== 结果: {data} ===")
