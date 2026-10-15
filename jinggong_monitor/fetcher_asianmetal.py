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


async def _is_logged_in(page) -> bool:
    """判断当前是否已登录：已登录页头含"注销"入口，未登录为"登录"链接。

    2026-07-27 修正：不再依赖转瞬即逝的"成功登陆"提示文案（实测该文案常匹配不到），
    改用稳定出现的"注销"按钮作为已登录态判据。
    """
    try:
        body = await page.inner_text("body", timeout=2000)
    except Exception:
        return False
    return "注销" in body


async def _handle_already_online(page) -> bool:
    """处理"此账号在线中"：点击强制进入按钮 #outlinebutn（value=登 陆）。

    2026-07-02 实测：亚洲金属网在账号已在线时会弹此提示，必须点它才能进主站。
    """
    try:
        btn = page.locator("#outlinebutn")
        if await btn.count():
            await btn.click(timeout=5000)
            await asyncio.sleep(3)
            return True
    except Exception:
        pass
    return False


async def _login_in_popup(page) -> bool:
    """在当前页面触发登录弹窗并登录，返回是否真正登录成功。

    适用于文章页被重定向到首页并弹出登录框的场景。

    2026-07-27 修正（根因修复）：
    1. 用页面"注销"入口判断真实登录态，不再依赖"成功登陆"提示文案。
    2. 检测到"账号在线"时点击 #outlinebutn 强制进入，而非盲目 logout+重登
       （重登会打断正在建立的会话，是此前偶发失败的主因之一）。
    3. 登录成功后轮询等待会话生效，最长 60s，避免重访文章时抢跑
       （实测一次登录约需 26s 才真正生效，原代码仅 sleep(5) 必抢跑）。
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
        logger.info("已点击登录按钮，轮询等待会话生效...")

        # 轮询登录态，最长 60s（实测一次登录约 26s 才真正生效）
        for i in range(60):
            await asyncio.sleep(1)
            if await _is_logged_in(page):
                logger.info(f"登录成功（第 {i+1}s 检测到已登录态）")
                await asyncio.sleep(3)  # 等会话 cookie 完全生效后再交还调用方
                return True
            # 账号在线提示 → 强制进入（不盲目重登）
            try:
                body = await page.inner_text("body", timeout=2000)
                if "在线" in body or "此账号" in body:
                    logger.info("检测到账号在线提示，点击强制进入")
                    if await _handle_already_online(page):
                        await asyncio.sleep(3)
                        if await _is_logged_in(page):
                            logger.info("强制进入后登录成功")
                            return True
            except Exception:
                pass

        logger.warning("60s 内未检测到登录态，登录失败")
        return False
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


# =============================================================================
# 2026-10-15 蜂巢汽车板块新增：稀土三品种（镨钕 / 镝铁 / 铽）
# -----------------------------------------------------------------------------
# 蜂巢清单指定数据源为「亚洲金属网」。实测结论：
#   · 「价格走势」页为**结构化 HTML table**（品名/规格/单位/价格/美元价格/变化/更新时间），
#     **不是图片，无需 OCR**，直接解析 DOM 即可；
#   · 首次访问常显示「登录查看」，触发弹窗登录后即出数 —— 与闻喜镁锭同一登录机制、
#     同一账号，**不新增账号依赖**；
#   · 取数口径：只取**人民币价**（单位列须为「元/吨」或「元/公斤」），
#     取区间中值 (low+high)/2 —— 与闻禧镁锭既有取法保持一致。
#     **美元价列一律不取**，避免美元/人民币口径混入（同页两者并存且列序固定为
#     人民币在前、美元折算在后）。
#
# 本组品种为**独立入口**（fetch_rare_earth_sync），不并入 _fetch_asianmetal_raw，
# 以免精工/曼德主流程因多抓 3 个页面而变慢、或受稀土页异常牵连。
# =============================================================================

RARE_EARTH_TARGETS = {
    # code: (价格走势页 URL, 品名列原文, 规格关键词, 人民币单位, 中值合理区间)
    "PRND": ("https://www.asianmetal.cn/PraseodymiumPriceIndex",
             "镨钕混合金属", "中国出厂", "元/吨", (100_000.0, 5_000_000.0)),
    "DYFE": ("https://www.asianmetal.cn/DysprosiumPriceIndex",
             "镝铁", "中国出厂", "元/公斤", (500.0, 10_000.0)),
    "TB":   ("https://www.asianmetal.cn/TerbiumPriceIndex",
             "金属铽", "中国出厂", "元/公斤", (2_000.0, 30_000.0)),
}

# 价格区间形如「895000-900000」「1360-1380」（可能有全角/波浪号变体、千分位逗号）
_RANGE_RE = re.compile(r"(\d[\d,]*)\s*[-–~]\s*(\d[\d,]*)")

# 取表格全部行（每行 → 单元格文本数组），列位由调用方按名/单位/规格三重锚定，
# 不硬编码列号，页面增删列时不至于静默取错值。
_TABLE_ROWS_JS = """
() => {
    const out = [];
    for (const t of document.querySelectorAll('table')) {
        for (const row of t.querySelectorAll('tr')) {
            const cells = Array.from(row.querySelectorAll('td, th'))
                               .map(c => (c.innerText || '').trim());
            if (cells.length >= 5 && cells.some(x => x !== '')) out.push(cells);
        }
    }
    return out;
}
"""


async def _page_table_rows(page, url: str, wait_ms: int = 4000) -> list:
    """访问指定页面并返回全部表格行。"""
    await page.goto(url, timeout=60000, wait_until="domcontentloaded")
    await page.wait_for_timeout(wait_ms)
    rows = await page.evaluate(_TABLE_ROWS_JS)
    return rows or []


def _pick_rare_earth(code: str, rows: list) -> Optional[float]:
    """从表格行中挑出目标品种的人民币价（区间中值）。

    三重锚定（缺一不可），任一不满足即跳过该行：
      1. 品名列（前两列）命中目标品名原文；
      2. 该行存在单元格含规格关键词（「中国出厂」）；
      3. 该行存在单元格**精确等于**人民币单位（「元/吨」或「元/公斤」）
         —— 这一条同时排除了同品种的「中国离岸 美元/公斤」行。
    再取第一个落入品种合理区间的价格单元格（人民币价列），取中值返回。
    """
    _url, name, spec_kw, unit, (lo, hi) = RARE_EARTH_TARGETS[code]
    for cells in rows:
        head = " ".join(cells[:2])
        if name not in head:
            continue
        if not any(spec_kw in c for c in cells):
            continue
        if unit not in cells:
            continue
        for c in cells:
            m = _RANGE_RE.fullmatch(c.strip())
            if not m:
                continue
            low = float(m.group(1).replace(",", ""))
            high = float(m.group(2).replace(",", ""))
            if lo <= low <= high <= hi:
                mid = round((low + high) / 2, 2)
                logger.info(f"  ✅ {code}: {low:,.0f}-{high:,.0f} {unit} → 中值 {mid:,.2f}")
                return mid
        return None
    return None


async def _ensure_rare_earth_logged_in(page) -> bool:
    """预检稀土页登录态并按需登录。

    稀土「价格走势」页未登录时，价格列渲染为「登录查看」。逐页撞墙后再登录
    会白跑 3 个页面（约 15s），故先用**首页（镨）**探一次，只在确实存在
    登录墙时才触发 `_login_in_popup`（该函数自身会处理「账号在线」情形）。
    """
    try:
        await page.goto(RARE_EARTH_TARGETS["PRND"][0],
                        timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)
        body = await page.inner_text("body")
    except Exception as e:                                         # noqa: BLE001
        logger.warning(f"  登录态预检失败（仍继续尝试抓取）: {type(e).__name__}: {e}")
        return True
    if "登录查看" not in body:
        return True
    logger.info("  稀土页检测到「登录查看」登录墙，弹窗登录 ...")
    return await _login_in_popup(page)


async def _fetch_rare_earth(page, ctx) -> dict:
    """抓取稀土三品种（先保登录态，再逐页取数）。"""
    if not await _ensure_rare_earth_logged_in(page):
        logger.error("  登录失败，稀土三品种本轮留空（不沿用前值）")
        return {}

    out: dict = {}
    for code in RARE_EARTH_TARGETS:
        url = RARE_EARTH_TARGETS[code][0]
        try:
            rows = await _page_table_rows(page, url)
        except Exception as e:                                     # noqa: BLE001
            logger.warning(f"  {code} 页访问失败: {type(e).__name__}: {e}")
            continue
        v = _pick_rare_earth(code, rows)
        if v is not None:
            out[code] = v

    missing = [c for c in RARE_EARTH_TARGETS if c not in out]
    if missing:
        logger.warning(f"  未取到: {','.join(missing)}（留空）")
    return out


async def _fetch_rare_earth_raw() -> dict:
    """稀土三品种抓取主流程（独立浏览器会话）。"""
    async with async_playwright() as p:
        headless = os.environ.get("ASIANMETAL_HEADLESS", "1") != "0"
        launch_args = ["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        b = await p.chromium.launch(headless=headless, args=launch_args)
        try:
            ctx_kw = dict(viewport={"width": 1280, "height": 900}, bypass_csp=True)
            if headless:
                ctx_kw["user_agent"] = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                                        "Chrome/126.0.0.0 Safari/537.36")
            ctx = await b.new_context(**ctx_kw)
            await _load_cookies(ctx)
            page = await ctx.new_page()
            out = await _fetch_rare_earth(page, ctx)

            # 截图存证（项目惯例；失败不影响取数）
            _SHOT_DIR.mkdir(parents=True, exist_ok=True)
            try:
                await page.screenshot(
                    path=str(_SHOT_DIR / f"asianmetal_稀土_{datetime.now().strftime('%H%M%S')}.png"),
                    full_page=True, timeout=10000)
            except Exception as e:                                 # noqa: BLE001
                logger.debug(f"稀土页截图失败（不影响取数）: {e}")

            if out:
                await _save_cookies(ctx)
            return out
        finally:
            await b.close()


def fetch_rare_earth_sync() -> dict:
    """同步入口：稀土三品种（镨钕 PRND / 镝铁 DYFE / 铽 TB）。

    返回 {"PRND": 897500.0, "DYFE": 1370.0, "TB": 8200.0} 形式；
    单项抓不到即不含该键（由调用方按「留空不沿用前值」处理）。
    """
    try:
        return asyncio.run(_fetch_rare_earth_raw())
    except Exception as e:                                         # noqa: BLE001
        logger.warning(f"稀土抓取异常: {type(e).__name__}: {e}")
        return {}


async def _fetch_asianmetal_raw() -> dict:
    """抓取闻喜镁锭价格。"""
    async with async_playwright() as p:
        # 2026-09-03：亚洲金属网开始拦截无头 Chromium（headless 登录 60s 均失败），
        # 加 ASIANMETAL_HEADLESS=0 开关切有头模式；默认仍为无头，不影响定时任务。
        headless = os.environ.get("ASIANMETAL_HEADLESS", "1") != "0"
        launch_args = ["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        b = await p.chromium.launch(headless=headless, args=launch_args)
        try:
            ctx_kw = dict(viewport={"width": 1280, "height": 900}, bypass_csp=True)
            if headless:
                # 无头时用真实 Chrome UA，抹掉 HeadlessChrome 特征
                ctx_kw["user_agent"] = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                                        "Chrome/126.0.0.0 Safari/537.36")
            ctx = await b.new_context(**ctx_kw)
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
                    logger.error("登录失败，放弃抓取")
                    _SHOT_DIR.mkdir(parents=True, exist_ok=True)
                    try:
                        await page.screenshot(path=str(_SHOT_DIR / f"asianmetal_login_fail_{datetime.now().strftime('%H%M%S')}.png"), full_page=True)
                    except Exception:
                        pass
                    return {}
                logger.info(f"登录后 URL: {page.url}")
                # 轮询重访文章页，直到真正进入 /news/（最多 3 次，避免抢跑）
                reached = False
                for attempt in range(3):
                    url_path = page.url.replace(BASE_URL, "").split("?")[0]
                    if url_path.startswith("/news/"):
                        reached = True
                        break
                    await page.goto(article_url, timeout=30000, wait_until="domcontentloaded")
                    await page.wait_for_timeout(3000)
                    logger.info(f"重访文章(第{attempt+1}次) URL={page.url}")
                if not reached:
                    logger.error("登录后仍无法访问文章页")
                    _SHOT_DIR.mkdir(parents=True, exist_ok=True)
                    try:
                        await page.screenshot(path=str(_SHOT_DIR / f"asianmetal_no_article_{datetime.now().strftime('%H%M%S')}.png"), full_page=True)
                    except Exception:
                        pass
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
