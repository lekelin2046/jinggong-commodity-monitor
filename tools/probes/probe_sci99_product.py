#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测卓创「品种页」的历史数据能力（只读）。

发现路径：搜索页存在「数据及曲线对比」/「查看对比曲线」/「下载历史数据」
与「时间周期」选择器 —— 说明站内**存在历史数据功能**。
品种页入口：`product.aspx?ppid=<n>&ppname=<品种>`（曼德所述「塑料→工程塑料→PA6」
即此导航树），PA6 ppid=12703。

本探针：打开品种页 → 枚举数据行/按钮 → 尝试触发「数据及曲线对比」，
       捕获其 XHR（可能即历史曲线接口），判定能否取到多日期序列。

用法：python tools/probes/probe_sci99_product.py [ppid...]
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

DEFAULT_PPIDS = ["12703"]          # PA6
URL = "https://prices.sci99.com/cn/product.aspx?ppid={ppid}"


async def run(ppids: list) -> None:
    from playwright.async_api import async_playwright

    cookies = _load_cookies()
    print(f"cookie={'OK' if cookies else '不可用'}  ppid={ppids}")

    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context(locale="zh-CN", viewport={"width": 1700, "height": 1100},
                                  accept_downloads=True)
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        xhr: list = []

        async def on_resp(r):
            u = r.url
            if any(k in u.lower() for k in ("getlines", "lines", "history", "excel",
                                            "export", "download", "curve", "chart")):
                try:
                    body = await r.text()
                except Exception as e:                           # noqa: BLE001
                    body = f"<{e}>"
                xhr.append({"m": r.request.method, "u": u, "s": r.status,
                            "post": (r.request.post_data or "")[:300],
                            "body": body[:600]})

        page.on("response", lambda r: asyncio.create_task(on_resp(r)))

        for ppid in ppids:
            url = URL.format(ppid=ppid)
            print(f"\n{'=' * 78}\n[ppid {ppid}] {url}")
            try:
                await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                await page.wait_for_timeout(5000)
            except Exception as e:                               # noqa: BLE001
                print(f"  打开失败 {type(e).__name__}: {e}")
                continue

            info = await page.evaluate(r"""() => {
              const rows = [...document.querySelectorAll('table tr')]
                  .map(tr => [...tr.querySelectorAll('th,td')].map(t=>t.innerText.trim()))
                  .filter(c => c.some(x => x !== ''));
              const clickable = [...document.querySelectorAll('a,button,span,label')]
                  .filter(e => /曲线|历史|下载|对比|导出|Excel/i.test(e.innerText || ''))
                  .map(e => ({tag:e.tagName, cls:(e.className||'').toString().slice(0,40),
                              t:(e.innerText||'').trim().replace(/\s+/g,' ').slice(0,30)}));
              const periods = [...document.querySelectorAll('select option')]
                  .map(o => o.text.trim()).slice(0, 10);
              return {n_rows: rows.length, head: rows.slice(0,3), tail: rows.slice(-3),
                      clickable: clickable.slice(0, 20), periods,
                      has_cb: document.querySelectorAll('input[type=checkbox]').length,
                      body_head: (document.body.innerText||'').replace(/\s+/g,' ').slice(0, 260)};
            }""")
            print(f"  表格行 {info['n_rows']}｜复选框 {info['has_cb']}")
            print(f"  周期选项: {info['periods']}")
            print(f"  页面首段: {info['body_head']}")
            print("  表头:", info["head"][0] if info["head"] else "-")
            for r in info["head"][1:3] + info["tail"]:
                print("   行:", r[:12])
            print("  历史相关可点元素:")
            for c in info["clickable"]:
                print(f"    {c['tag']:<7} {c['t']:<28} cls={c['cls']}")

            # 尝试勾选数据行并触发曲线
            try:
                cbs = await page.query_selector_all("input[type=checkbox]")
                n = 0
                for cb in cbs:
                    try:
                        if await cb.is_visible():
                            await cb.check(timeout=3000)
                            n += 1
                        if n >= 3:
                            break
                    except Exception:                            # noqa: BLE001
                        continue
                print(f"  已勾选 {n} 行，等待曲线请求…")
                await page.wait_for_timeout(4000)
            except Exception as e:                               # noqa: BLE001
                print(f"  勾选异常 {e}")

        await b.close()

    print(f"\n[=] 命中 XHR {len(xhr)} 条：")
    for x in xhr:
        dates = re.findall(r"\d{4}-\d{1,2}-\d{1,2}", x["body"])
        print(f"  {x['m']} {x['s']} {x['u'][:120]}")
        if x["post"]:
            print(f"      post={x['post']}")
        print(f"      body={x['body'][:300]}")
        if dates:
            print(f"      ↳ 日期 {len(set(dates))} 个: {sorted(set(dates))[:8]}")
    if xhr:
        Path("/tmp/sci99_product_xhr.json").write_text(
            json.dumps(xhr, ensure_ascii=False, indent=1), encoding="utf-8")
        print("    落盘 /tmp/sci99_product_xhr.json")


if __name__ == "__main__":
    args = sys.argv[1:]
    asyncio.run(run(args or DEFAULT_PPIDS))
