"""隆众资讯 登录机制探针

目的：判定「有账号密码能否抓」
1. 登录弹窗有哪几种方式（账号密码 / 手机验证码 / 微信扫码）
2. 网易易盾 NECaptcha 是否强制人工交互（滑块/点选/无感静默通过）
3. 未登录 vs 已登录态下，文章正文的差异

不执行真实登录（无账号），只观察登录界面形态。
"""
import asyncio
import os
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "data" / "probe_lz_login"  # 2026-09-23 整理：本文件位于 tools/probes/，根目录上溯两级
OUT.mkdir(parents=True, exist_ok=True)

ARTICLES = [
    ("天胶价格汇总", "https://www.oilchem.net/26-0916-17-66f8295a0e00e000.html"),
    ("顺丁出厂价", "https://www.oilchem.net/26-0916-16-e7a54bfe4c3f002a.html"),
]


async def main():
    from playwright.async_api import async_playwright

    env = os.environ.copy()
    env.pop("NODE_OPTIONS", None)
    for d in ["*.oilchem.net", "*.a1static.oilchem.net", "*.163.com"]:
        env.setdefault("NO_PROXY", "")
        env["NO_PROXY"] = (env["NO_PROXY"] + "," + d).strip(",")
    env["no_proxy"] = env["NO_PROXY"]

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            env=env,
        )
        ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
            viewport={"width": 1440, "height": 1000},
            locale="zh-CN",
        )
        page = await ctx.new_page()

        # ---- 1. 首页，触发登录弹窗 ----
        print("=" * 70)
        print("[1] 打开首页 → 点击登录")
        await page.goto("https://www.oilchem.net/", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)

        # 记录未登录 cookie
        ck0 = await ctx.cookies()
        print(f"    首页 cookie 数: {len(ck0)}")
        print(f"    关键 cookie: {[c['name'] for c in ck0][:15]}")

        # 找登录入口并点击
        clicked = False
        for sel in ['a.login', 'a:has-text("登录")', 'text=登录', '#loginBtn', '.login-btn']:
            try:
                el = page.locator(sel).first
                if await el.count() and await el.is_visible():
                    await el.click(timeout=5000)
                    clicked = True
                    print(f"    已点击登录入口: {sel}")
                    break
            except Exception:
                continue
        if not clicked:
            print("    ⚠ 未找到可见登录入口，改用 JS 触发 openAlertOne()")
            try:
                await page.evaluate("openAlertOne && openAlertOne()")
                clicked = True
            except Exception as e:
                print("    JS 触发失败:", e)

        await page.wait_for_timeout(4000)
        await page.screenshot(path=str(OUT / "01_login_dialog.png"), full_page=False)
        print(f"    截图 → {OUT/'01_login_dialog.png'}")

        # ---- 2. 分析弹窗结构 ----
        print()
        print("[2] 登录弹窗结构")
        info = await page.evaluate("""() => {
            const out = {tabs: [], inputs: [], captcha: [], iframes: [], buttons: []};
            // tab 页签
            document.querySelectorAll('.tab, .tabs li, .tab-title, [class*=tab]').forEach(e => {
                const t = (e.innerText||'').trim().replace(/\\s+/g,' ').slice(0,30);
                if (t && t.length < 30) out.tabs.push(t);
            });
            // 输入框
            document.querySelectorAll('input').forEach(e => {
                if (e.offsetParent !== null)
                    out.inputs.push({name: e.name||e.id, type: e.type,
                                     ph: e.placeholder||'', vis: true});
            });
            // 验证码容器
            ['#lzValid','#smsValid','.NECaptcha','[id*=Valid]','[class*=captcha]','[id*=captcha]']
              .forEach(sel => {
                document.querySelectorAll(sel).forEach(e => {
                    out.captcha.push({sel, id: e.id, cls: (e.className||'').toString().slice(0,60),
                                      vis: e.offsetParent !== null,
                                      txt: (e.innerText||'').trim().slice(0,60)});
                });
              });
            // iframe（易盾有时用 iframe 承载）
            document.querySelectorAll('iframe').forEach(e => {
                if (e.offsetParent !== null) out.iframes.push({src: (e.src||'').slice(0,120), id: e.id});
            });
            // 按钮
            document.querySelectorAll('button, a[class*=login], a[class*=reg]').forEach(e => {
                if (e.offsetParent !== null) {
                    const t = (e.innerText||'').trim().slice(0,20);
                    if (t) out.buttons.push(t);
                }
            });
            return out;
        }""")
        print("    Tab 页签:", sorted(set(info["tabs"]))[:10])
        print("    可见输入框:", info["inputs"][:8])
        print("    验证码容器:", info["captcha"][:8])
        print("    可见 iframe:", info["iframes"][:6])
        print("    按钮:", sorted(set(info["buttons"]))[:10])

        # ---- 3. 易盾脚本加载情况 ----
        print()
        print("[3] 网易易盾 NECaptcha 加载情况")
        dun = await page.evaluate("""() => {
            const r = {hasNECaptcha: typeof window.initNECaptcha === 'function',
                       hasCaptchaIns: typeof window.captchaIns !== 'undefined',
                       scripts: [], dunGlobals: []};
            document.querySelectorAll('script[src]').forEach(s => {
                if (/dun|163|NECaptcha/i.test(s.src)) r.scripts.push(s.src.slice(0,110));
            });
            Object.keys(window).filter(k => /NECaptcha|initNECaptcha|captcha|dun/i.test(k))
                  .forEach(k => r.dunGlobals.push(k));
            return r;
        }""")
        print("    initNECaptcha 可用:", dun["hasNECaptcha"])
        print("    captchaIns 实例:", dun["hasCaptchaIns"])
        print("    易盾脚本:", dun["scripts"][:5])
        print("    易盾全局对象:", sorted(set(dun["dunGlobals"]))[:10])

        # ---- 4. 未登录态文章正文 ----
        print()
        print("[4] 未登录态文章正文检查")
        for name, url in ARTICLES:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(3000)
                txt = await page.evaluate("""() => {
                    const el = document.querySelector('.xq-content, .article-content, .content, #content')
                            || document.body;
                    return (el.innerText || '').replace(/\\s+/g, ' ');
                }""")
                gated = "暂未登录" in txt or "免费开通会员" in txt or "注册为会员" in txt
                yen = txt.count("元/吨")
                nums = len(__import__("re").findall(r"\\d{4,5}", txt))
                print(f"    [{name}] 门槛={'受限' if gated else '开放'} 元/吨×{yen} 4~5位数×{nums} 长度{len(txt)}")
                print(f"        摘要: {txt[:180]}")
            except Exception as e:
                print(f"    [{name}] 异常: {e}")

        # ---- 5. 结论 ----
        print()
        print("=" * 70)
        print("[5] cookie 现状（未登录）")
        ck1 = await ctx.cookies()
        for c in ck1[:20]:
            print(f"    {c['name']:24s} domain={c['domain'][:30]:32s} exp={'会话' if c['expires']<0 else int(c['expires'])}")

        await browser.close()
    print()
    print("探测完成")


if __name__ == "__main__":
    asyncio.run(main())
