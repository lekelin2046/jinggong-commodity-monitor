"""登录态修复助手

主人 SMM / 亚洲金属网登录态过期时使用：
1. 自动打开 SMM + 亚洲金属网登录页（在调试 Chrome 里）
2. 实时检测登录状态（轮询）
3. 登录成功后自动重跑 fill_and_verify 流程

用法：
  python3 relogin_assistant.py
"""
import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright

sys.path.insert(0, '/Users/siqi/Desktop/AI/jinggong-commodity-monitor')

SMM_LOGIN_URL = "https://hq.smm.cn/login"
ASIANMETAL_LOGIN_URL = "https://www.asianmetal.cn/login/login.shtml"
CDP_URL = "http://localhost:9223"


async def wait_for_login(page, site_name: str, check_fn) -> bool:
    """轮询检测登录态"""
    print(f"\n⏳ 等待 {site_name} 登录...")
    for i in range(60):  # 最多等 5 分钟
        try:
            logged_in = await check_fn(page)
            if logged_in:
                print(f"✅ {site_name} 登录成功！")
                return True
        except Exception as e:
            pass
        await asyncio.sleep(5)
        if i % 6 == 0:
            print(f"   等待中... ({i*5}s)")
    print(f"❌ {site_name} 登录超时")
    return False


async def check_smm_login(page) -> bool:
    """SMM 登录态检测：访问 hq.smm.cn/aluminum 看是否含真实价格"""
    await page.goto("https://hq.smm.cn/aluminum", timeout=15000, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    text = await page.inner_text("body")
    # 登录态正常：表格行含具体价格数字
    # 未登录：表格行显示"未登录"
    return "未登录" not in text and ("ADC12" in text and any(c.isdigit() for c in text))


async def check_asianmetal_login(page) -> bool:
    """亚洲金属网登录态检测：访问镁锭文章看价格是否可访问"""
    await page.goto("https://www.asianmetal.cn/news/2969853/", timeout=15000, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    text = await page.inner_text("body")
    # 登录态正常：文章表格有闻喜镁锭价格
    # 未登录：被踢回登录页
    return "闻喜" in text and "16,050" in text or "16,100" in text or "镁锭" in text and not "返回登录" in text


async def main():
    print("=" * 60)
    print("  SMM + 亚洲金属网 登录态修复助手")
    print("=" * 60)
    print(f"\n请在调试 Chrome 中登录这两个站：")
    print(f"  1. SMM 上海有色 (hq.smm.cn)")
    print(f"  2. 亚洲金属网 (asianmetal.cn)")
    print(f"\n登录页已自动打开...")
    print(f"登录后我会自动检测，登录成功立即继续抓取")

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]

        # 用一个新页面打开登录引导
        page = await context.new_page()

        # Step 1: 打开 SMM 登录页
        print(f"\n[1/3] 打开 SMM 登录页...")
        await page.goto(SMM_LOGIN_URL, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        print(f"   已打开: {page.url}")

        smm_ok = await wait_for_login(page, "SMM 上海有色", check_smm_login)

        # Step 2: 打开亚洲金属网登录页
        print(f"\n[2/3] 打开亚洲金属网登录页...")
        await page.goto(ASIANMETAL_LOGIN_URL, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        print(f"   已打开: {page.url}")

        asianmetal_ok = await wait_for_login(page, "亚洲金属网", check_asianmetal_login)

        await page.close()

        # Step 3: 跑抓取
        print("\n" + "=" * 60)
        if smm_ok and asianmetal_ok:
            print("✅ 两个站都登录成功！开始抓取 6/25 数据...")
            # 复用 fill_and_verify 流程
            sys.path.insert(0, '.')
            import fill_and_verify
            await fill_and_verify.main()
        elif smm_ok or asianmetal_ok:
            print(f"⚠️ 部分登录成功（SMM={smm_ok}, 亚洲金属网={asianmetal_ok}）")
            print("继续抓取能抓的部分...")
            sys.path.insert(0, '.')
            import fill_and_verify
            await fill_and_verify.main()
        else:
            print("❌ 两个站都没登录成功（超时）")


if __name__ == "__main__":
    asyncio.run(main())
