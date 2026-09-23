#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针：SMM「历史价格」站（price.smm.cn → history.smm.cn）的权限与接口（2026-09-17）

背景：hq.smm.cn 现货价只有当日 SSR 文本，历史在独立站
`{url}{spot}/v31/settlement/history/categories`（要 token）。
本探针带着 smm_cookies.json 打开该站，抓真实 XHR 地址 + 判定是否有权限。
只读，不写业务文件。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

os.environ.pop("NODE_OPTIONS", None)

ROOT = Path(__file__).resolve().parents[2]  # 2026-09-23 整理：本文件位于 tools/probes/，根目录上溯两级
sys.path.insert(0, str(ROOT))

from jinggong_monitor.fetcher_smm import COOKIE_FILE  # noqa: E402

TARGET = "https://price.smm.cn/spot_price"


async def main():
    from playwright.async_api import async_playwright
    hits: list[tuple[str, str, int, str]] = []

    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await b.new_context()
        if COOKIE_FILE.exists():
            await ctx.add_cookies(json.loads(COOKIE_FILE.read_text()))
            print(f"[i] 已加载 cookies: {COOKIE_FILE}")
        page = await ctx.new_page()

        async def on_response(resp):
            u = resp.url
            if "smm.cn" in u and any(k in u for k in
                                     ("v31", "settlement", "history", "price", "categories")):
                body = ""
                ct = (resp.headers or {}).get("content-type", "")
                if "json" in ct:
                    try:
                        body = (await resp.text())[:300]
                    except Exception:      # noqa: BLE001
                        pass
                hits.append((resp.request.method, u, resp.status, body))

        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        print(f"[i] 打开 {TARGET}")
        await page.goto(TARGET, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(10000)

        body_text = await page.inner_text("body")
        print("\n[=] 页面可见文本（前 600 字）：")
        print(body_text[:600].replace("\n", " | "))

        # 页面内直接试接口（借用页面登录态）
        for path in ("/v31/settlement/history/categories",):
            for host in ("https://platform.smm.cn", ""):
                url = host + path
                try:
                    r = await page.evaluate(
                        """async (u) => {
                            try {
                                const r = await fetch(u, {credentials:'include'});
                                const t = await r.text();
                                return {status: r.status, body: t.slice(0, 400)};
                            } catch (e) { return {status: -1, body: String(e)}; }
                        }""", url)
                    print(f"\n[=] fetch {url} → {r['status']}\n    {r['body'][:300]}")
                except Exception as e:         # noqa: BLE001
                    print(f"[!] fetch {url} 失败: {e}")

        await b.close()

    print(f"\n[=] 命中的 XHR（{len(hits)}）：")
    for m, u, st, body in hits[:20]:
        print(f"  {m} {st} {u[:130]}")
        if body:
            print(f"      ↳ {body[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
