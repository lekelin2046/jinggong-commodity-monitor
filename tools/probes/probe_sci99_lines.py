#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测卓创 `selectedlines/getlines.ashx` 曲线接口（只读）。

发现路径：`probe_sci99_history.py` 观测到搜索页自身会 POST
`https://prices.sci99.com/selectedlines/getlines.ashx`（200），
疑似「选中行的价格曲线」数据源 —— 若返回多日期序列，则曼德 5 项
（PRND/PA6/PA66/PP_T30S/PP_EP548R）**可回补历史**。

本探针：抓该接口的请求体 + 响应体，并判定响应里是否含日期序列。

用法：python tools/probes/probe_sci99_lines.py [编号...]
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

DEFAULT_IDS = ["43234"]
SEARCH = "https://prices.sci99.com/cn/search.aspx?keyword={vid}"


async def run(vids: list) -> None:
    from playwright.async_api import async_playwright

    cookies = _load_cookies()
    print(f"cookie={'OK' if cookies else '不可用'}  编号={vids}")

    caught: list = []

    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context(locale="zh-CN", viewport={"width": 1600, "height": 1000})
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        async def on_resp(resp):
            if "getlines" not in resp.url:
                return
            try:
                req = resp.request
                pd = req.post_data or ""
                txt = await resp.text()
            except Exception as e:                               # noqa: BLE001
                pd, txt = f"<{e}>", ""
            caught.append({"url": resp.url, "method": req.method,
                           "status": resp.status, "post_data": pd, "body": txt})

        page.on("response", lambda r: asyncio.create_task(on_resp(r)))

        try:
            await page.goto("https://www.sci99.com/", wait_until="domcontentloaded",
                            timeout=30000)
        except Exception:                                        # noqa: BLE001
            pass

        for vid in vids:
            print(f"\n{'=' * 78}\n[编号 {vid}] 打开搜索页，监听 getlines")
            before = len(caught)
            try:
                await page.goto(SEARCH.format(vid=vid), timeout=60000,
                                wait_until="domcontentloaded")
                await page.wait_for_timeout(6000)
            except Exception as e:                               # noqa: BLE001
                print(f"  页面失败 {type(e).__name__}: {e}")
                continue
            print(f"  本次捕获 {len(caught) - before} 条 getlines 请求")
            for c in caught[before:]:
                print(f"  --- {c['status']} {c['method']} {c['url']}")
                print(f"      请求体: {c['post_data'][:500]}")
                body = c["body"]
                print(f"      响应 {len(body)} 字: {body[:700]}")
                dates = re.findall(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}", body)
                print(f"      ↳ 命中日期样式 {len(dates)} 个，唯一 {len(set(dates))} 个: "
                      f"{sorted(set(dates))[:12]}")

        await b.close()

    print(f"\n[=] 共捕获 {len(caught)} 条")
    if caught:
        Path("/tmp/sci99_lines.json").write_text(
            json.dumps(caught, ensure_ascii=False, indent=1), encoding="utf-8")
        print("    已落盘 /tmp/sci99_lines.json 供细读")


if __name__ == "__main__":
    args = sys.argv[1:]
    asyncio.run(run(args or DEFAULT_IDS))
