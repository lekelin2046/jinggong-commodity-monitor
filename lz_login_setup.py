"""隆众资讯 人工登录引导 + 会员权限体检

用途：回答「有账号密码能抓多少」——登录一次，立刻把权限边界测出来。

模式（与项目 LME / ccmn 一致）：持久化 Playwright profile。
- 人工在有头浏览器里登录一次（含网易易盾验证码）
- 登录态由 profile 自然保存（cookie + localStorage + 设备指纹一致）
- 之后 daily 抓取脚本复用同一 profile，无需重复登录

为什么不学卓创那样「导出 cookie 给脚本用」：
  隆众登录页挂了网易易盾风控探针（cstaticdun wm.3.0.0 + initCaptchaWatchman），
  会持续采集设备指纹。cookie 挪到别的浏览器环境，指纹对不上可能被判风险。
  profile 模式指纹天然一致，最稳。

用法：
    unset NODE_OPTIONS
    /Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/python lz_login_setup.py \
        --username 你的账号 --password 你的密码
    # 或者不带参数，纯手工在浏览器里输入

结束后会打印权限体检报告：哪些文章解锁了、价格中心能否访问。
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).parent
PROFILE_DIR = PROJECT / "cookies" / "lz_profile"
COOKIE_BACKUP = PROJECT / "cookies" / "lz.json"

LOGIN_URL = "https://www.oilchem.net/"

# 已知受限文章（未登录态正文长度 83 字符、0 处「元/吨」）
GATED_ARTICLES = [
    ("天胶价格汇总", "https://www.oilchem.net/26-0916-17-66f8295a0e00e000.html"),
    ("顺丁出厂价",   "https://www.oilchem.net/26-0916-16-e7a54bfe4c3f002a.html"),
]

# 价格中心（结构化数据库，若账号有权限比爬文章更优）
PRICE_CENTER = "https://price.oilchem.net/"

WAIT_LOGIN_S = 300      # 给人工登录的窗口：5 分钟
RENDER_WAIT_S = 3


def _ensure_dir(p: Path):
    """受限环境下 mkdir(exist_ok=True) 会被拦截并伪装成其他错误，改为不存在才建 + 容错"""
    if not p.exists():
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"  [warn] 目录创建失败（可能已存在，忽略）: {e}")


def _env_without_proxy():
    env = os.environ.copy()
    env.pop("NODE_OPTIONS", None)
    for d in ["*.oilchem.net", "*.126.net", "*.163.com"]:
        env["NO_PROXY"] = (env.get("NO_PROXY", "") + "," + d).strip(",")
    env["no_proxy"] = env["NO_PROXY"]
    return env


async def _article_state(page) -> tuple[bool, int, int, int, str]:
    """返回 (是否仍受限, 元/吨计数, 4~5位数计数, 正文长度, 正文摘要)"""
    txt = await page.evaluate("""() => {
        const el = document.querySelector('.xq-content, .article-content, .content, #content')
                || document.body;
        return (el.innerText || '').replace(/\\s+/g, ' ').trim();
    }""")
    gated = ("暂未登录" in txt or "注册为会员" in txt
             or "免费开通会员" in txt or "浏览权" in txt)
    return gated, txt.count("元/吨"), len(re.findall(r"\d{4,5}", txt)), len(txt), txt[:200]


async def _detect_captcha(page) -> str:
    """检测网易易盾验证码/风控弹层是否出现，返回命中的选择器（未出现返回空串）"""
    try:
        return await page.evaluate("""() => {
            const sels = ['.yidun_popup', '.yidun_modal', '.yidun_panel', '.yidun_intellisense',
                          'iframe[src*="dun.163.com"]', '#cap_iframe', '.nc_container',
                          '.captcha', '.verify-wrap'];
            for (const s of sels) {
                const el = document.querySelector(s);
                if (el && el.offsetParent !== null) return s;
            }
            return '';
        }""")
    except Exception:
        return ""


async def _login_error(page) -> str:
    """抓取登录弹窗内的错误提示（账密错误 / 需要验证码等）"""
    try:
        return await page.evaluate("""() => {
            const sels = ['.error', '.err', '.tips', '.tip', '.dialog-error',
                          '.login-tip', '.msg', '.el-message'];
            for (const s of sels) {
                for (const el of document.querySelectorAll(s)) {
                    const t = (el.innerText || '').trim();
                    if (t && el.offsetParent !== null && t.length < 80) return t;
                }
            }
            return '';
        }""")
    except Exception:
        return ""


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--username", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--timeout", type=int, default=WAIT_LOGIN_S)
    args = ap.parse_args()

    from playwright.async_api import async_playwright

    _ensure_dir(PROFILE_DIR.parent)
    new_profile = not PROFILE_DIR.exists()
    print("=" * 72)
    print("隆众资讯 登录引导 + 权限体检")
    print("=" * 72)
    print(f"profile: {PROFILE_DIR}  ({'新建' if new_profile else '复用已有（若已登录可跳过）'})")
    print()

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,                      # 必须有头：人工要输入 + 过易盾验证码
            channel="chrome",
            viewport={"width": 1400, "height": 950},
            locale="zh-CN",
            args=["--disable-blink-features=AutomationControlled"],
            env=_env_without_proxy(),
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(RENDER_WAIT_S * 1000)

        # ---------- 1. 打开登录弹窗 + 自动填表提交（验证码如需则人工） ----------
        dialog_ok = False
        try:
            for sel in ['a.login', 'a:has-text("登录")', '.login-btn', 'text=登录']:
                el = page.locator(sel).first
                if await el.count() and await el.is_visible():
                    await el.click(timeout=5000)
                    dialog_ok = True
                    print(f"    已点开登录入口（{sel}）")
                    break
            await page.wait_for_timeout(2500)
            for sel in ['text=账号登录', 'text=账号密码登录', 'text=密码登录']:
                try:
                    tab = page.locator(sel).first
                    if await tab.count() and await tab.is_visible():
                        await tab.click(timeout=4000)
                        await page.wait_for_timeout(1200)
                        print(f"    已切到「{sel.split('=')[-1]}」tab")
                        break
                except Exception:
                    continue
        except Exception as e:
            print(f"    打开登录弹窗异常: {e}")

        if args.username and args.password and dialog_ok:
            print("[1] 自动填充账号密码并提交")
            try:
                await page.fill("#dialogUsername", args.username, timeout=8000)
                await page.fill("#dialogPassword", args.password, timeout=8000)
                print("    已填入账号密码")
                submitted = False
                for sel in ['button:has-text("登录")', '.dialogLoginBtn', '#dialogLoginSubmit',
                            'a:has-text("立即登录")', 'input[type="submit"]', '.login-submit']:
                    try:
                        btn = page.locator(sel).last
                        if await btn.count() and await btn.is_visible():
                            await btn.click(timeout=5000)
                            submitted = True
                            print(f"    已点击登录按钮（{sel}）")
                            break
                    except Exception:
                        continue
                if not submitted:
                    print("    ! 未自动找到登录按钮，请在浏览器里手动点击")
                await page.wait_for_timeout(3500)
                cap = await _detect_captcha(page)
                err = await _login_error(page)
                shot_dir = PROJECT / "data" / "probe_lz_login"
                _ensure_dir(shot_dir)
                await page.screenshot(path=str(shot_dir / "02_after_submit.png"))
                if cap:
                    print(f"    ⚠ 检测到验证码/风控层（{cap}）→ 请在浏览器里完成，脚本继续等待登录")
                else:
                    print("    ✓ 未检测到验证码弹层")
                if err:
                    print(f"    ! 页面提示：{err}")
                print("    （截图 → data/probe_lz_login/02_after_submit.png）")
            except Exception as e:
                print(f"    自动填充/提交未成功（{type(e).__name__}: {e}）→ 请手动在浏览器里登录")
        elif args.username and args.password:
            print("[1] 未能自动打开登录弹窗 → 请手动在浏览器里登录")
        else:
            print("[1] 请在打开的浏览器里手动登录（点右上角「登录」，可用账号 / 手机号 / 微信扫码）")

        # ---------- 2. 等待登录完成（用文章正文解锁作判据，最可靠） ----------
        print()
        print(f"[2] 等待登录完成（最长 {args.timeout}s）——判据：受限文章正文是否解锁")
        deadline = time.time() + args.timeout
        logged = False
        last_note = 0
        probe_page = await ctx.new_page()
        while time.time() < deadline:
            try:
                await probe_page.goto(GATED_ARTICLES[0][1], wait_until="domcontentloaded",
                                      timeout=45000)
                await probe_page.wait_for_timeout(RENDER_WAIT_S * 1000)
                gated, yen, nums, tlen, sample = await _article_state(probe_page)
                if not gated and (yen > 0 or nums >= 3):
                    logged = True
                    break
                if time.time() - last_note > 20:
                    last_note = time.time()
                    print(f"    尚未登录 / 正文仍受限（正文 {tlen} 字符, 元/吨×{yen}）…等待中")
            except Exception as e:
                if time.time() - last_note > 20:
                    last_note = time.time()
                    print(f"    检测异常（{type(e).__name__}），继续等待…")
            await asyncio.sleep(5)

        if not logged:
            print()
            print("  ✗ 未检测到登录成功（超时）。可能原因：未完成登录 / 账号权限不足（免费会员无权看全文）。")
            print(f"    profile 已保存于 {PROFILE_DIR}，可重跑本脚本继续。")
            await ctx.close()
            return

        print("  ✓ 检测到正文已解锁，登录态有效")

        # ---------- 3. 权限体检 ----------
        print()
        print("[3] 会员权限体检（这决定 15 个品类能抓多少）")
        ok_cnt = 0
        for name, url in GATED_ARTICLES:
            try:
                await probe_page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await probe_page.wait_for_timeout(RENDER_WAIT_S * 1000)
                gated, yen, nums, tlen, sample = await _article_state(probe_page)
                mark = "✗ 仍受限" if gated else "✓ 已解锁"
                if not gated:
                    ok_cnt += 1
                print(f"    {mark}  {name}: 正文 {tlen} 字符, 元/吨×{yen}, 4~5位数×{nums}")
                print(f"          {sample[:150]}")
            except Exception as e:
                print(f"    ! {name}: 异常 {e}")
        print(f"    → 文章解锁 {ok_cnt}/{len(GATED_ARTICLES)}")

        # 价格中心
        print()
        try:
            await probe_page.goto(PRICE_CENTER, wait_until="domcontentloaded", timeout=45000)
            await probe_page.wait_for_timeout(RENDER_WAIT_S * 1000)
            title = await probe_page.title()
            body_len = len(await probe_page.evaluate("() => document.body.innerText || ''"))
            print(f"    价格中心 price.oilchem.net: title={title!r} 可见文本 {body_len} 字符")
            print("      （SPA，需登录态调其数据接口；本次仅确认页面可达）")
        except Exception as e:
            print(f"    价格中心异常: {e}")

        # ---------- 4. 保存 cookie 备份 + profile ----------
        print()
        print("[4] 保存登录态")
        cookies = await ctx.cookies()
        _ensure_dir(COOKIE_BACKUP.parent)
        COOKIE_BACKUP.write_text(
            json.dumps(cookies, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"    cookie 备份 → {COOKIE_BACKUP}（{len(cookies)} 条）")
        key = ["_member_user_tonken_", "refcheck", "refpay", "refsite", "AGL_USER_ID"]
        for c in cookies:
            if c["name"] in key:
                v = c.get("value", "")
                exp = c.get("expires", -1)
                exp_s = "会话" if exp < 0 else time.strftime("%Y-%m-%d", time.localtime(exp))
                print(f"      {c['name']:24s} 值长度={len(v):4d} 过期={exp_s}")
        print(f"    profile → {PROFILE_DIR}")

        await ctx.close()

    print()
    print("=" * 72)
    print("完成。登录态已持久化，后续抓取脚本可直接复用该 profile。")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
