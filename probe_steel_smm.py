"""PoC 探针：验证能否从 steel.smm.cn 抓取铁矿石/冶金焦价格
分两阶段：先无登录访问，再登录 SMM 后访问，对比是否需要登录。
截图容错：失败不阻断数据提取。
"""
import asyncio
import re
import sys
from pathlib import Path

PROJECT_DIR = Path("/Users/siqi/Desktop/AI/jinggong-commodity-monitor")
sys.path.insert(0, str(PROJECT_DIR))
from playwright.async_api import async_playwright
from jinggong_monitor.credentials import require_smm

SMM_ACCOUNT, SMM_PASSWORD = require_smm()

IRON_URL = "https://steel.smm.cn/steel/090?city=1195"
COKE_URL = "https://steel.smm.cn/steel/106"
SHOT_DIR = PROJECT_DIR / "screenshots" / "2026-07-16"
SHOT_DIR.mkdir(parents=True, exist_ok=True)


async def grab(page, url):
    await page.goto(url, timeout=30000, wait_until="domcontentloaded")
    await page.wait_for_timeout(7000)
    return await page.inner_text("body")


async def safe_shot(page, path):
    try:
        await page.screenshot(path=str(path), full_page=True, timeout=15000)
    except Exception as e:
        print("  ⚠️ 截图失败(忽略):", repr(e)[:100])


def parse_iron(text):
    res = {}
    m = re.search(r"卡粉\s*65%[\s\S]{0,80}?京唐港\s*(\d{2,5})", text)
    if m:
        res["卡粉65%_京唐港"] = int(m.group(1))
    m2 = re.search(r"卡粉\s*65%[\s\S]{0,80}?曹妃甸\s*(\d{2,5})", text)
    if m2:
        res["卡粉65%_曹妃甸"] = int(m2.group(1))
    return res


def parse_coke(text):
    res = {}
    i = text.find("MT<7")
    if i >= 0:
        seg = text[i:i + 260]
        m = re.search(r"(\d{3,5})\s*-\s*(\d{3,5})", seg)
        if m:
            low, high = int(m.group(1)), int(m.group(2))
            after = seg[m.end():]
            m2 = re.search(r"(\d{3,5})", after)
            res["一级冶金焦_MT7_区间"] = [low, high]
            res["一级冶金焦_MT7_均价"] = int(m2.group(1)) if m2 else None
    return res


async def main():
    p = await async_playwright().start()
    browser = await p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
    page = await ctx.new_page()

    print("########## 阶段A：无登录 ##########")
    iron_a = await grab(page, IRON_URL)
    pa_iron = parse_iron(iron_a)
    print("[无登录] 铁矿石:", pa_iron)
    i = iron_a.find("京唐港")
    print("  京唐港上下文:", repr(iron_a[max(0, i - 60):i + 110]) if i >= 0 else "未找到京唐港")
    await safe_shot(page, SHOT_DIR / "iron_nologin.png")
    coke_a = await grab(page, COKE_URL)
    pa_coke = parse_coke(coke_a)
    print("[无登录] 冶金焦:", pa_coke)
    i = coke_a.find("MT<7")
    print("  MT<7上下文:", repr(coke_a[i:i + 220].replace("\n", " ")) if i >= 0 else "未找到MT<7")
    await safe_shot(page, SHOT_DIR / "coke_nologin.png")

    print("########## 阶段B：登录 SMM 后 ##########")
    await page.goto("https://user.smm.cn/login", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)
    await page.fill("#userName", SMM_ACCOUNT)
    await page.fill("#password", SMM_PASSWORD)
    await page.click("#user_account_password_login_button")
    await asyncio.sleep(5)
    login_ok = "login" not in page.url.lower()
    print("LOGIN_OK:", login_ok, "URL:", page.url)

    iron_b = await grab(page, IRON_URL)
    pb_iron = parse_iron(iron_b)
    print("[登录后] 铁矿石:", pb_iron)
    i = iron_b.find("京唐港")
    print("  京唐港上下文:", repr(iron_b[max(0, i - 60):i + 110]) if i >= 0 else "未找到京唐港")
    await safe_shot(page, SHOT_DIR / "iron_login.png")
    coke_b = await grab(page, COKE_URL)
    pb_coke = parse_coke(coke_b)
    print("[登录后] 冶金焦:", pb_coke)
    i = coke_b.find("MT<7")
    print("  MT<7上下文:", repr(coke_b[i:i + 220].replace("\n", " ")) if i >= 0 else "未找到MT<7")
    await safe_shot(page, SHOT_DIR / "coke_login.png")

    print("\n================ 最终对比 ================")
    print("铁矿石 无登录:", pa_iron, " | 登录后:", pb_iron)
    print("冶金焦 无登录:", pa_coke, " | 登录后:", pb_coke)

    await browser.close()
    await p.stop()


if __name__ == "__main__":
    asyncio.run(main())
