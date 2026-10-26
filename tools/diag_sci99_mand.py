"""卓创（sci99）曼德品种抓取诊断：区分「页面 0 行」与「有行但无该编号」。

用法：unset NODE_OPTIONS && python tools/diag_sci99_mand.py
输出每个编号的：HTTP 状态 / 表格总行数 / 是否含目标编号 / 前几行首列样本。
"""
import asyncio
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jinggong_monitor.fetcher_sci99 import (  # noqa: E402
    SCI99_MAND_TARGETS, SEARCH_URL, _JS_MAND_TABLE, _load_cookies, parse_mand_row,
)


async def main() -> None:
    cookies = _load_cookies()
    print(f"cookie 条数: {len(cookies)}")

    from playwright.async_api import async_playwright

    today = dt.date.today()
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-quic", "--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36"),
            viewport={"width": 1600, "height": 1000},
            locale="zh-CN",
        )
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        try:
            await page.goto("https://www.sci99.com/", wait_until="domcontentloaded",
                            timeout=30000)
        except Exception as e:  # noqa: BLE001
            print("首页预热失败:", type(e).__name__, e)

        for code, vid, desc, scale in SCI99_MAND_TARGETS:
            url = SEARCH_URL.format(vid=vid)
            try:
                resp = await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
                rows = await page.evaluate(_JS_MAND_TABLE)
                title = await page.title()
                body_len = await page.evaluate("() => document.body.innerText.length")
                has_login = await page.evaluate(
                    "() => /登录|login/i.test(document.body.innerText.slice(0,500))")
            except Exception as e:  # noqa: BLE001
                print(f"[{code}] 加载失败 {type(e).__name__}: {e}")
                continue

            hit = parse_mand_row(rows, vid, today)
            sample = [" | ".join(r[:3]) for r in rows[:3]]
            print(f"[{code}] vid={vid} status={resp.status if resp else '?'} "
                  f"rows={len(rows)} body={body_len} login_hint={has_login} "
                  f"hit={'OK' if hit and hit.get('value') is not None else 'MISS'}")
            print(f"    title={title[:60]}")
            for s in sample:
                print(f"    row: {s[:120]}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
