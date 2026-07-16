"""SMM 钢铁频道抓取模块（铁矿石、冶金焦）

数据源：
  - 进口铁矿石 · 卡粉 65% 京唐港（河北）：https://steel.smm.cn/steel/090?city=1195
  - 一级冶金焦 · MT<7 全国均价：        https://steel.smm.cn/steel/106

关键结论（2026-07-16 验证）：
  1. 页面价格公开，**无需登录** SMM 账号（无登录 vs 登录结果完全一致）。
  2. 数据靠 JS 动态渲染，urllib/requests 静态抓取拿不到，必须用 Playwright 渲染后取 inner_text。
  3. page.screenshot(full_page=True) 在 steel.smm.cn 会卡「等待字体加载」超时，
     故截图存证改用 CDP Page.captureScreenshot 直接截取渲染表面绕过。

接口：
  fetch() -> dict  同步入口，返回 {"IRON_ORE": 855, "COKE": 1840}；失败时返回 {}。

品种代码（与 daily_update_all / export_excel_to_json / index.html 对齐）：
  IRON_ORE : 进口铁矿石 卡粉65% 京唐港（元/湿吨）
  COKE     : 一级冶金焦 MT<7 全国均价（元/吨）
"""

import asyncio
import base64
import re
import sys
from datetime import date
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

IRON_URL = "https://steel.smm.cn/steel/090?city=1195"
COKE_URL = "https://steel.smm.cn/steel/106"

IRON_CODE = "IRON_ORE"
COKE_CODE = "COKE"

SHOT_DIR = PROJECT_DIR / "screenshots" / date.today().isoformat()


# ============================================================
# 解析
# ============================================================
def _parse_iron(text: str):
    """进口铁矿石 · 卡粉 65% 京唐港（河北）"""
    m = re.search(r"卡粉\s*65%[\s\S]{0,80}?京唐港\s*(\d{2,5})", text)
    return int(m.group(1)) if m else None


def _parse_coke(text: str):
    """一级冶金焦 · A<12.5，S<0.7，CSR>65，MT<7 全国均价

    页面文本结构（2026-07-16 实测，inner_text 顺序）：
      SMM中国一级冶金焦价格指数\tA<12.5，S<0.7，CSR>65，MT<7\t\t1840-1840\t1840\t0\t
      SMM中国准一级冶金焦价格指数\tA<13.5，S<0.7，CSR>60，MT<7\t\t1750-1750\t1750\t0\t

    注意：同页还有「干熄 MT<0（2230）」「准一级 MT<7（1750）」两组，
    必须精确锁定「一级 + A<12.5 + CSR>65 + MT<7」这一行，避免误抓 1750/2230。
    取「价格区间」后的「均价」列；若无区间则取该行首个数字。
    """
    # 精确锁定一级冶金焦 MT<7 那一行（兼容全角/半角逗号两种写法）
    spec_pos = -1
    for spec in ("A<12.5，S<0.7，CSR>65，MT<7", "A<12.5,S<0.7,CSR>65,MT<7"):
        spec_pos = text.find(spec)
        if spec_pos >= 0:
            break
    if spec_pos < 0:
        # 退化：直接找第一个 MT<7（可能误抓准一级，但优先保证有值）
        spec_pos = text.find("MT<7")
    if spec_pos < 0:
        return None
    seg = text[spec_pos:spec_pos + 300]
    # 优先匹配区间（low-high），均价取区间后的第一个数
    m = re.search(r"(\d{3,5})\s*-\s*(\d{3,5})", seg)
    if m:
        low, high = int(m.group(1)), int(m.group(2))
        after = seg[m.end():]
        m2 = re.search(r"(\d{3,5})", after)
        return int(m2.group(1)) if m2 else (low + high) // 2
    # 无区间：取该行首个 3-5 位数字作为均价
    m3 = re.search(r"(\d{3,5})", seg)
    return int(m3.group(1)) if m3 else None


# ============================================================
# Playwright 抓取
# ============================================================
async def _grab(page, url: str) -> str:
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(7000)  # 等 AJAX 价格加载完
    return await page.inner_text("body")


async def _cdp_screenshot(page, out_path: Path) -> bool:
    """用 CDP 直接截取渲染表面，绕过 Playwright 高层的字体等待超时。

    返回 True 表示截图成功。
    """
    try:
        session = await page.context.new_cdp_session(page)
        metrics = await session.send("Page.getLayoutMetrics")
        w = metrics["contentSize"]["width"]
        h = metrics["contentSize"]["height"]
        res = await session.send(
            "Page.captureScreenshot",
            {
                "format": "png",
                "captureBeyondViewport": True,
                "clip": {"x": 0, "y": 0, "width": w, "height": h, "scale": 1},
            },
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(base64.b64decode(res["data"]))
        return True
    except Exception as e:
        print(f"  [steel] 截图存证失败(忽略): {e}")
        return False


async def _run() -> dict:
    from playwright.async_api import async_playwright

    result: dict = {}
    p = await async_playwright().start()
    browser = await p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
    page = await ctx.new_page()

    async def grab_until(url: str, needle: str) -> str:
        """抓取并等待关键文本出现（最多重试 2 次，间隔 3 秒），应对 AJAX 偶发未加载。"""
        text = await _grab(page, url)
        for _ in range(2):
            if needle in text:
                return text
            await page.wait_for_timeout(3000)
            text = await _grab(page, url)
        return text

    try:
        # 1. 铁矿石
        iron_text = await grab_until(IRON_URL, "京唐港")
        v = _parse_iron(iron_text)
        if v:
            result[IRON_CODE] = v
            print(f"  [steel] 铁矿石卡粉65%京唐港 = {v} 元/湿吨")
        else:
            print("  [steel] 铁矿石未匹配到（可能页面改版或网络异常）")
        await _cdp_screenshot(page, SHOT_DIR / "steel_iron.png")

        # 2. 冶金焦
        coke_text = await grab_until(COKE_URL, "MT<7")
        v = _parse_coke(coke_text)
        if v:
            result[COKE_CODE] = v
            print(f"  [steel] 一级冶金焦 MT<7 全国均价 = {v} 元/吨")
        else:
            print("  [steel] 冶金焦未匹配到（可能页面改版或网络异常）")
        await _cdp_screenshot(page, SHOT_DIR / "steel_coke.png")
    finally:
        await browser.close()
        await p.stop()
    return result


def fetch() -> dict:
    """同步入口：返回 {IRON_ORE: ..., COKE: ...}；异常时返回 {}。"""
    try:
        return asyncio.run(_run())
    except Exception as e:
        print(f"  [steel] 抓取异常: {e}")
        return {}


if __name__ == "__main__":
    print(fetch())
