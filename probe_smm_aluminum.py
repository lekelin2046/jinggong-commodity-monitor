#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_smm_aluminum.py — 探测 hq.smm.cn/aluminum 页面可用品种

用途：为「塑料橡胶看板扩充品类」核实 A00 / ZLD104 是否在 SMM 聚合页中。
做法：复用 fetcher_smm 的登录态（data/smm_cookies.json），抓取页面 innerText，
      落盘到 data/smm_aluminum_probe.txt 供离线分析，并打印含铝字样的行。
"""
import asyncio
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jinggong_monitor.fetcher_smm import _fetch_page_text, _login_and_save_cookies, COOKIE_FILE, SMM_PAGES
from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "data" / "smm_aluminum_probe.txt"


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = await b.new_context()
            if COOKIE_FILE.exists():
                cookies = json.loads(COOKIE_FILE.read_text())
                await ctx.add_cookies(cookies)
                print(f"已加载 {len(cookies)} 个 cookies")
            text = await _fetch_page_text(ctx, SMM_PAGES["aluminum"], wait_ms=12000)
            print(f"aluminum 页文本长度: {len(text)}")
            # 关键：是否已登录（未登录会截断/提示）
            for kw in ["登录", "登录后", "会员"]:
                if kw in text:
                    print(f"  ⚠️ 页面含「{kw}」")
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(text, encoding="utf-8")
            print(f"已落盘: {OUT}")
            print("=" * 70)
            print("含「铝」或价格样式的行（前 120 行）：")
            print("=" * 70)
            n = 0
            for line in text.splitlines():
                s = line.strip()
                if not s:
                    continue
                if ("铝" in s or re.search(r"\d{4,6}~\d{4,6}", s)):
                    print(" ", s[:160])
                    n += 1
                    if n >= 120:
                        break
        finally:
            await b.close()


if __name__ == "__main__":
    os.environ.pop("NODE_OPTIONS", None)
    asyncio.run(main())
