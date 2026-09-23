"""隆众价格中心（dc.oilchem.net）接口侦察

目的：找出价格中心真实调用的数据接口，并判定未登录态返回什么。
方法：Playwright 打开价格中心列表页，拦截全部 XHR/fetch。
     若接口可免登录调用 → 15 个品类很可能一次性解决；
     若返回需登录 → 也必须登录，但接口结构化，比爬文章正文可靠得多。
"""
import asyncio
import json
import os
import re
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "data" / "probe_dc"  # 2026-09-23 整理：本文件位于 tools/probes/，根目录上溯两级
OUT.mkdir(parents=True, exist_ok=True)

# 柴油 channelIdNew=1695（从首页链接取得）
URLS = [
    ("柴油-市场价格", "https://dc.oilchem.net/page/#/list?channelIdNew=1695&name=%E6%9F%B4%E6%B2%B9&businessType=3"),
    ("价格中心首页", "https://dc.oilchem.net/page/#/index"),
]

SKIP = re.compile(r"\.(js|css|png|jpg|jpeg|gif|svg|woff2?|ttf|ico)(\?|$)")


async def main():
    from playwright.async_api import async_playwright

    env = os.environ.copy()
    env.pop("NODE_OPTIONS", None)
    for d in ["*.oilchem.net", "*.126.net", "*.163.com", "*.mysteelcdn.com"]:
        env["NO_PROXY"] = (env.get("NO_PROXY", "") + "," + d).strip(",")
    env["no_proxy"] = env["NO_PROXY"]

    captured = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            env=env,
        )
        ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
            viewport={"width": 1440, "height": 1000}, locale="zh-CN")

        async def on_response(resp):
            u = resp.url
            if SKIP.search(u):
                return
            if not re.search(r"\.(json|do|action)|/api|/dc/|query|list|price|data", u, re.I):
                return
            rec = {"url": u, "status": resp.status,
                   "method": resp.request.method,
                   "type": resp.request.resource_type}
            try:
                body = await resp.text()
                rec["len"] = len(body)
                rec["body"] = body[:1200]
            except Exception as e:
                rec["err"] = str(e)
            captured.append(rec)

        ctx.on("response", on_response)

        for name, url in URLS:
            print("=" * 72)
            print(f"[{name}] {url}")
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(9000)      # 等 SPA 拉数据
                txt = await page.evaluate("() => (document.body.innerText||'').replace(/\\s+/g,' ').trim()")
                print(f"    可见文本 {len(txt)} 字符")
                print(f"    摘要: {txt[:400]}")
                # 登录/权限提示
                for kw in ["登录", "会员", "无权限", "开通", "元/吨"]:
                    c = txt.count(kw)
                    if c:
                        print(f"      含「{kw}」×{c}")
                await page.screenshot(path=str(OUT / f"{name}.png"))
            except Exception as e:
                print(f"    异常: {e}")
            await page.close()

        await browser.close()

    print()
    print("=" * 72)
    print(f"[网络请求] 捕获 {len(captured)} 条")
    for r in captured:
        print(f"  {r['status']} {r['method']:5s} [{r['type']:10s}] {r['url'][:135]}")
        if "body" in r:
            b = re.sub(r"\s+", " ", r["body"])
            print(f"        {b[:260]}")
        print()

    (OUT / "network.json").write_text(
        json.dumps(captured, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"明细 → {OUT/'network.json'}")


if __name__ == "__main__":
    asyncio.run(main())
