#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测卓创搜索页 DOM 结构 + 「品种编号」精确检索能力（只读）。

目的：为 fetcher_sci99 新增「按编号/规格精确定位」能力前，先确认两件事：
  ① 搜索页表格能否用 page.evaluate 稳定提取为二维数组（含空单元格）
  ② keyword=<品种编号> 是否精确返回该编号那一行（而非模糊结果）

用法：
  /Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/python tools/probes/probe_sci99_table.py 43234 34618
  ... tools/probes/probe_sci99_table.py -            # 默认测试集
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from jinggong_monitor.fetcher_sci99 import _load_cookies  # noqa: E402

DEFAULT_KWS = ["43234", "34618", "16980", "17969", "198236", "204759"]

JS_TABLE = """
() => {
  const out = [];
  for (const tr of document.querySelectorAll('table tr')) {
    const cells = [...tr.querySelectorAll('th,td')].map(td => td.innerText.trim());
    if (cells.some(c => c !== '')) out.push(cells);
  }
  return out;
}
"""


async def run(kws: list) -> None:
    from playwright.async_api import async_playwright

    cookies = _load_cookies()
    print(f"cookie={'OK' if cookies else '不可用'}  待测 keyword={kws}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(locale="zh-CN",
                                        viewport={"width": 1600, "height": 1000})
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        try:
            await page.goto("https://www.sci99.com/", wait_until="domcontentloaded",
                            timeout=30000)
        except Exception:                                        # noqa: BLE001
            pass

        for kw in kws:
            url = f"https://prices.sci99.com/cn/search.aspx?keyword={kw}"
            try:
                await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                await page.wait_for_timeout(3500)
                table = await page.evaluate(JS_TABLE)
            except Exception as e:                               # noqa: BLE001
                print(f"\n[{kw}] 失败 {type(e).__name__}: {e}")
                continue
            print(f"\n{'=' * 78}\n[{kw}] 提取到 {len(table)} 行")
            for i, row in enumerate(table[:12]):
                joined = " | ".join(row)
                print(f"  r{i:02d}({len(row)}列) {joined[:300]}")
        await browser.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    kws = DEFAULT_KWS if (not args or args == ["-"]) else args
    asyncio.run(run(kws))
