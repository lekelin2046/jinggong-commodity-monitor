#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测卓创资讯「历史价格」可得性（只读）。

背景：曼德 5 项（PRND/PA6/PA66/PP_T30S/PP_EP548R）按品种编号锚定单行，
      而搜索页只返回**最新一期**。本探针判定登录态下能否取到历史序列，
      以及能回溯多久 —— 直接决定「能不能补历史」这个结论。

做法：
  1. 打开 `search.aspx?keyword=<编号>`，抽出所有链接（找详情页入口）
  2. 对候选详情/历史页逐个打开，检测页面内是否含**多日期**序列
     （形如 10/14、10/13… 或 JS 变量里的时间数组）
  3. 打印页面内命中的接口（XHR）与图表数据线索

用法：python tools/probes/probe_sci99_history.py [编号...]
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from jinggong_monitor.fetcher_sci99 import _load_cookies  # noqa: E402

DEFAULT_IDS = ["43234", "198236"]
SEARCH = "https://prices.sci99.com/cn/search.aspx?keyword={vid}"

# 常见的历史/详情入口候选（卓创站内路径形态）
CANDIDATE = [
    "https://prices.sci99.com/cn/price_detail.aspx?id={vid}",
    "https://prices.sci99.com/cn/price_history.aspx?id={vid}",
    "https://prices.sci99.com/cn/history.aspx?id={vid}",
    "https://prices.sci99.com/cn/price_trend.aspx?id={vid}",
    "https://prices.sci99.com/cn/price_search_detail.aspx?id={vid}",
]

JS_LINKS = """
() => [...document.querySelectorAll('a[href]')]
        .map(a => ({href: a.href, text: (a.innerText || '').trim().slice(0, 24)}))
        .filter(o => o.href && !o.href.startsWith('javascript'))
        .slice(0, 60)
"""

JS_DATEY = """
() => {
  const t = document.body ? document.body.innerText : '';
  const dates = t.match(/\\d{1,2}\\/\\d{1,2}/g) || [];
  const uniq = [...new Set(dates)];
  return {len: t.length, uniq_dates: uniq.slice(0, 40), n_dates: uniq.length,
          tail: t.replace(/\\s+/g, ' ').slice(0, 300)};
}
"""


async def run(vids: list) -> None:
    from playwright.async_api import async_playwright

    cookies = _load_cookies()
    print(f"cookie={'OK' if cookies else '不可用'}  待测编号={vids}")
    if not cookies:
        print("无 cookie，无法判定登录态能力，退出")
        return

    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context(locale="zh-CN", viewport={"width": 1600, "height": 1000})
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        xhr: list = []
        page.on("response", lambda r: xhr.append((r.request.method, r.url, r.status)))

        try:
            await page.goto("https://www.sci99.com/", wait_until="domcontentloaded", timeout=30000)
        except Exception:                                        # noqa: BLE001
            pass

        for vid in vids:
            print(f"\n{'=' * 78}\n[编号 {vid}] 搜索页链接枚举")
            try:
                await page.goto(SEARCH.format(vid=vid), timeout=60000,
                                wait_until="domcontentloaded")
                await page.wait_for_timeout(3500)
                links = await page.evaluate(JS_LINKS)
            except Exception as e:                               # noqa: BLE001
                print(f"  搜索页失败 {type(e).__name__}: {e}")
                links = []
            seen = set()
            for o in links:
                h = o["href"]
                if h in seen:
                    continue
                seen.add(h)
                if any(k in h.lower() for k in ("price", "detail", "history", "trend", "chart")):
                    print(f"  ★ {o['text'][:20]:<22} {h[:120]}")
            print(f"  （链接共 {len(seen)} 个）")

            print(f"\n[编号 {vid}] 候选历史页探测")
            for tpl in CANDIDATE:
                url = tpl.format(vid=vid)
                try:
                    resp = await page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    await page.wait_for_timeout(2000)
                    st = resp.status if resp else -1
                    info = await page.evaluate(JS_DATEY)
                    flag = "★多日期" if info["n_dates"] >= 3 else ""
                    print(f"  {st} {url}")
                    print(f"      {flag} 文本{info['len']}字 唯一日期{info['n_dates']}个 "
                          f"{info['uniq_dates'][:8]}")
                except Exception as e:                           # noqa: BLE001
                    print(f"  --- {url} → {type(e).__name__}")

        await b.close()

    print(f"\n[=] 站内 XHR 命中 {len(xhr)} 条（含 history/chart/kline 的）：")
    for m, u, st in xhr:
        if any(k in u.lower() for k in ("history", "chart", "trend", "kline", "curve", "line")):
            print(f"  {m} {st} {u[:150]}")


if __name__ == "__main__":
    args = sys.argv[1:]
    asyncio.run(run(args or DEFAULT_IDS))
