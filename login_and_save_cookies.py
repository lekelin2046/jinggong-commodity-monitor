"""SMM + 亚洲金属网 自动化登录 & Cookie 保存

用 Playwright 有头浏览器登录两个站点，保存 cookies 供后续数据抓取复用。
支持用户手动完成验证码/滑块。

用法：
  python3 login_and_save_cookies.py
"""
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent))

# 防止代理阻断国内站点
os.environ["NO_PROXY"] = "sci99.com,chinatungsten.com,51bxg.com,steelcn.cn,ccmn.cn,cnfeol.com,ctia.com.cn,smm.cn,asianmetal.cn,hq.smm.cn"
os.environ["no_proxy"] = os.environ["NO_PROXY"]

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================

# 账号信息从环境变量 / .env 读取（不落盘、不保留默认密码）
from jinggong_monitor.credentials import require_smm, require_asianmetal

# 延迟调用（遵循 credentials.py 动态读取设计，非 import 时固化）
_smm_cred = None
_asianmetal_cred = None

def _get_smm():
    global _smm_cred
    if _smm_cred is None:
        _smm_cred = require_smm()
    return _smm_cred

def _get_asianmetal():
    global _asianmetal_cred
    if _asianmetal_cred is None:
        _asianmetal_cred = require_asianmetal()
    return _asianmetal_cred

# 站点 URL
SMM_LOGIN_URL = "https://user.smm.cn/login"                    # SMM 实际登录页
SMM_ALUMINUM_URL = "https://hq.smm.cn/aluminum"                # SMM 铝行情（login后跳转）
ASIANMETAL_LOGIN_URL = "https://www.asianmetal.cn/login/login.shtml"
ASIANMETAL_HOME = "https://www.asianmetal.cn/"


def now_str():
    return datetime.now().strftime("%H:%M:%S")


async def login_smm(browser) -> bool:
    """SMM 上海有色网登录

    表单结构（已验证 2026-06-30）：
      input#userName        → 手机号／邮箱／用户名
      input#password        → 输入登录密码
      input#account_remember_check → 记住我
      button#user_account_password_login_button → 登录
    """
    print(f"\n{'=' * 60}")
    print(f"[{now_str()}]  [1/2] SMM 上海有色网登录")
    print(f"{'=' * 60}")

    context = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        bypass_csp=True,
    )
    page = await context.new_page()

    try:
        # Step 1: 打开登录页（等 DOM 加载即可，networkidle 会因 SMM 长连接永远超时）
        print(f"[{now_str()}]  打开登录页: {SMM_LOGIN_URL}")
        await page.goto(SMM_LOGIN_URL, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Step 2: 确认当前是密码登录 tab（默认就是，不需要点）
        # 注意：页面默认状态就是 #userName + #password 可见，
        # 点击「密码登录」文字反而会跳到短信验证码模式（已踩坑）

        # Step 3: 填账号（id=userName，精确匹配，绝不碰搜索框）
        try:
            SMM_ACCOUNT, SMM_PASSWORD = _get_smm()
            account_input = page.locator("#userName")
            await account_input.wait_for(state="visible", timeout=5000)
            await account_input.fill(SMM_ACCOUNT)
            print(f"[{now_str()}]  填入账号 → #userName")
        except Exception as e:
            print(f"[{now_str()}]  ❌ 找不到账号输入框: {e}")
            return False

        # Step 4: 填密码（id=password）
        try:
            pwd_input = page.locator("#password")
            await pwd_input.wait_for(state="visible", timeout=5000)
            await pwd_input.fill(SMM_PASSWORD)
            print(f"[{now_str()}]  填入密码 → #password")
        except Exception as e:
            print(f"[{now_str()}]  ❌ 找不到密码输入框: {e}")
            return False

        # Step 5: 点击登录
        try:
            login_btn = page.locator("#user_account_password_login_button")
            await login_btn.wait_for(state="visible", timeout=5000)
            await login_btn.click()
            print(f"[{now_str()}]  点击登录按钮")
        except Exception as e:
            print(f"[{now_str()}]  ❌ 找不到登录按钮: {e}")
            return False

        # Step 6: 等待登录结果（最多 30s，两站均无验证码，通常 5s 内完成）
        print(f"\n[{now_str()}]  ⏳ 等待登录完成（最长30s）...")
        success = False
        for i in range(6):
            await asyncio.sleep(5)
            try:
                current_url = page.url

                # 成功标志：URL 不再含 login
                if "login" not in current_url.lower():
                    success = True
                    print(f"\n[{now_str()}]  ✅ SMM 登录成功！(等待 {i*5}s)")
                    break

                # 检查有没有错误提示
                try:
                    error_text = await page.locator("[class*=error], [class*=Error]").first.inner_text()
                    if error_text and len(error_text) > 1:
                        print(f"[{now_str()}]  ⚠️  登录错误提示: {error_text}")
                except Exception:
                    pass

            except Exception:
                pass

            if i % 2 == 0 and i > 0:
                print(f"[{now_str()}]    等待中... ({i*5}s)")

        if not success:
            print(f"[{now_str()}]  ⚠️  登录等待超时，仍尝试保存 cookies")

        # Step 7: 保存 cookies
        cookies = await context.cookies()
        cookie_path = DATA_DIR / "smm_cookies.json"
        with open(cookie_path, "w") as f:
            json.dump(cookies, f, indent=2, ensure_ascii=False)
        print(f"[{now_str()}]  💾 SMM cookies → {cookie_path} ({len(cookies)} 条)")

        # 截图确认
        screenshot_path = DATA_DIR / f"smm_login_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        await page.screenshot(path=str(screenshot_path), full_page=False)
        print(f"[{now_str()}]  📸 截图 → {screenshot_path}")

        return success

    except Exception as e:
        print(f"[{now_str()}]  ❌ SMM 登录异常: {e}")
        return False
    finally:
        await page.close()
        await context.close()


async def login_asianmetal(browser) -> bool:
    """亚洲金属网登录（通过顶部登录弹窗）

    2026-07-02 实测：主登录表单（txtUserLoginName/txtUserPwd）只返回 /access 路径的
    asianmetal cookie，无法建立主站会话。真正可用的登录入口是顶部弹窗：
      input#cnopenloginname  → 用户名
      input#cnopenloginpwd   → 密码
      input#openloginbutn    → 登录按钮（调用 loginByWin）
    登录后跳回受限页面，主页右上角显示「欢迎 山西振鑫镁业有限公司」。
    """
    print(f"\n{'=' * 60}")
    print(f"[{now_str()}]  [2/2] 亚洲金属网登录")
    print(f"{'=' * 60}")

    context = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        bypass_csp=True,
    )
    page = await context.new_page()

    # 受保护文章URL，访问它会触发登录弹窗
    PROTECTED_URL = "https://www.asianmetal.cn/news/2974825/"

    try:
        print(f"[{now_str()}]  打开受保护页面触发登录弹窗: {PROTECTED_URL}")
        await page.goto(PROTECTED_URL, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        print(f"[{now_str()}]  当前URL: {page.url}")

        # 通过 JavaScript 显示登录弹窗并填充凭据（弹窗默认隐藏，顶部登录链接可能被遮罩层拦截）
        ASIANMETAL_ACCOUNT, ASIANMETAL_PASSWORD = _get_asianmetal()
        print(f"[{now_str()}]  填充顶部登录弹窗...")
        await page.evaluate(
            """(args) => {
                const loginWin = document.getElementById("loginWin");
                const showFilter = document.getElementById("showFilter");
                if (loginWin) loginWin.style.display = "block";
                if (showFilter) showFilter.style.display = "block";
                document.getElementById("cnopenloginname").value = args.user;
                document.getElementById("cnopenloginpwd").value = args.pwd;
            }""",
            {"user": ASIANMETAL_ACCOUNT, "pwd": ASIANMETAL_PASSWORD},
        )
        await page.wait_for_timeout(500)

        # 点击登录按钮
        try:
            await page.locator("#openloginbutn").click(timeout=5000)
            print(f"[{now_str()}]  点击登录按钮")
        except Exception as e:
            print(f"[{now_str()}]  ❌ 找不到弹窗登录按钮: {e}")
            return False

        # 处理「账号在线中」强制下线弹窗：点 #outlinebutn 继续
        try:
            for _ in range(2):
                await page.wait_for_timeout(3000)
                body = await page.inner_text("body")
                if "此账号在线中" in body or "强制对方下线" in body:
                    print(f"[{now_str()}]  检测到账号在线中弹窗，点击「登陆」强制进入...")
                    try:
                        await page.locator("#outlinebutn").click(timeout=3000)
                    except Exception:
                        # 兜底：直接调用 outLine()
                        await page.evaluate('''() => { if (typeof outLine === "function") outLine(); }''')
                    await page.wait_for_timeout(3000)
        except Exception as e:
            print(f"[{now_str()}]  处理在线弹窗时忽略异常: {e}")

        # 等待登录结果
        print(f"\n[{now_str()}]  ⏳ 等待登录完成（最长30s）...")
        success = False
        for i in range(6):
            await asyncio.sleep(5)
            try:
                current_url = page.url
                body = await page.inner_text("body")

                # 成功：URL 不再含 index.shtml?s=1，且页面出现价格表或注销/欢迎信息
                if "news/2974825" in current_url and ("注销" in body or "欢迎" in body):
                    success = True
                    print(f"\n[{now_str()}]  ✅ 亚洲金属网登录成功！(等待 {i*5}s)")
                    break

                if "用户名或密码错误" in body:
                    print(f"[{now_str()}]  ❌ 用户名或密码错误")
                    return False
            except Exception:
                pass

            if i % 2 == 0 and i > 0:
                print(f"[{now_str()}]    等待中... ({i*5}s)")

        if not success:
            print(f"[{now_str()}]  ⚠️  登录等待超时，仍尝试保存 cookies")

        # 保存 cookies
        cookies = await context.cookies()
        cookie_path = DATA_DIR / "asianmetal_cookies.json"
        with open(cookie_path, "w") as f:
            json.dump(cookies, f, indent=2, ensure_ascii=False)
        print(f"[{now_str()}]  💾 亚洲金属网 cookies → {cookie_path} ({len(cookies)} 条)")

        # 截图确认
        screenshot_path = DATA_DIR / f"asianmetal_login_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        await page.screenshot(path=str(screenshot_path), full_page=False)
        print(f"[{now_str()}]  📸 截图 → {screenshot_path}")

        return success

    except Exception as e:
        print(f"[{now_str()}]  ❌ 亚洲金属网登录异常: {e}")
        return False
    finally:
        await page.close()
        await context.close()


async def main():
    print("=" * 60)
    print("  SMM + 亚洲金属网 自动化登录")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print()
    print("  两站均无需验证码，将在后台自动登录")
    print("  登录成功后 cookies 将保存到 data/ 目录")
    print()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,  # 两站均无需验证码，headless 更稳定
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )

        try:
            smm_ok = await login_smm(browser)
            asianmetal_ok = await login_asianmetal(browser)
        finally:
            await browser.close()

    print(f"\n{'=' * 60}")
    print(f"  结果汇总:")
    print(f"    SMM 上海有色网: {'✅ 成功' if 'smm_ok' in dir() and smm_ok else '❌ 失败'}")
    print(f"    亚洲金属网:     {'✅ 成功' if 'asianmetal_ok' in dir() and asianmetal_ok else '❌ 失败'}")
    print(f"{'=' * 60}")

    return 0 if (smm_ok and asianmetal_ok) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
