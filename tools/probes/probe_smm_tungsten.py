#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测 SMM 是否能作为钨粉(W)的备选源 —— 中钨在线当日文章未发布时的兜底可行性核查。

背景（2026-10-22）：中钨在线 `news.chinatungsten.com` 栏目页可达，但当日稿件未上线，
`fetch_tungsten()` 报「跳过旧文章 5 篇」→ W 留空。需评估 SMM 能否顶替。

核查点：
  1. 带 data/smm_cookies.json 登录态，打开 https://hq.smm.cn/tungsten 钨频道；
  2. 抓「钨粉(国产)」报价页 innerText，判断价格是否对当前登录态可见；
  3. 打印可比对的数值，供人工确认口径（元/千克，≥99.7% 钨粉）。

用法：
    unset NODE_OPTIONS
    ~/.workbuddy/binaries/python/envs/jinggong/bin/python tools/probes/probe_smm_tungsten.py
"""

import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
COOKIE_FILE = ROOT / "data" / "smm_cookies.json"
OUT_TXT = Path("/tmp/smm_tungsten_page.txt")

LIST_URL = "https://hq.smm.cn/tungsten"


async def main() -> int:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = await b.new_context()
            if COOKIE_FILE.exists():
                cookies = json.loads(COOKIE_FILE.read_text())
                await ctx.add_cookies(cookies)
                print(f"已加载 cookies：{len(cookies)} 个")
            else:
                print("⚠️ 无 cookies 文件，将以未登录态探测")
            page = await ctx.new_page()
            await page.goto(LIST_URL, timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(10000)

            # 找当日「钨粉(国产)报价」详情链接
            links = await page.eval_on_selector_all(
                "a",
                "els => els.map(e => ({t: e.innerText.trim(), h: e.href}))",
            )
            cand = [l for l in links if "钨粉" in (l.get("t") or "") and "国产" in (l.get("t") or "")]
            if not cand:
                cand = [l for l in links if "钨粉" in (l.get("t") or "")]
            print("候选链接：")
            for c in cand[:5]:
                print(f"  {c['t']}  →  {c['h']}")

            target = cand[0]["h"] if cand else LIST_URL
            print(f"\n打开：{target}")
            await page.goto(target, timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(10000)
            text = await page.inner_text("body")
            OUT_TXT.write_text(text, encoding="utf-8")
            print(f"页面文本 {len(text)} 字符 → {OUT_TXT}\n")

            lines = [l.strip() for l in text.splitlines() if l.strip()]
            print("=" * 60)
            print("【一】含「钨粉」且带数字的行")
            print("=" * 60)
            hits = [l for l in lines if "钨粉" in l and re.search(r"\d", l)]
            for l in hits[:20]:
                print("  " + l)
            if not hits:
                print("  （无 → 价格对当前登录态不可见）")

            print()
            print("=" * 60)
            print("【二】疑似价格区间行（四位以上数字）")
            print("=" * 60)
            for l in lines:
                if re.search(r"\d{3,6}", l) and ("钨" in l or "元" in l):
                    print("  " + l)
        finally:
            await b.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
