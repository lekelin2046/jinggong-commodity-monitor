#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_mand_varieties.py — 曼德看板 2026-10-14 品种口径优化的渲染验证

断言（本地起静态服务 + Playwright 无头浏览器）：
  ① badge 文案为「13 品种 · 13 项已接入（长江有色 3 / SMM 5 / 卓创 5）」
  ② 全文不含已移除/已改源的品种字样：巴斯夫 / PP-TD20 / PP-TD40 / 亚洲金属网
  ③ 明细表含 5 个新品种行：镨钕金属 / PA6 / PA66 / PP T30S / PP EP548R
  ④ 市场口径标签正确显示：PrNd≥99% · 中国 ｜ BL3280H · 华南 ｜ EPR27 · 神马塑料
                             大庆石化 · 沈阳 ｜ 大庆炼化 · 余姚
  ⑤ 当日取值正确渲染：镨钕金属 900,000 ｜ PA6 15,000 ｜ PA66 19,000 ｜ PP T30S 10,730
  ⑥ 分组含「稀土金属」「工程塑料」「PP 聚丙烯」，且不含「改性塑料」「巴斯夫PA66」
  ⑦ 零 console 错误

用法：/Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/python tools/probes/verify_mand_varieties.py
"""
from __future__ import annotations

import functools
import http.server
import pathlib
import re
import socketserver
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class ReusableServer(socketserver.TCPServer):
    allow_reuse_address = True


def serve():
    handler = functools.partial(QuietHandler, directory=str(DOCS))
    httpd = ReusableServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def main() -> int:
    httpd, port = serve()
    from playwright.sync_api import sync_playwright

    fails: list[str] = []
    checks: list[str] = []

    def ok(cond, msg):
        (checks if cond else fails).append(msg)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}/mand/index.html",
                  wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(2500)

        html = page.content()
        flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))

        # ① badge
        badge = "13 品种 · 13 项已接入（长江有色 3 / SMM 5 / 卓创 5）"
        ok(badge in flat, f"② badge 文案 = {badge}" if badge in flat else f"✗ badge 文案缺失")

        # ② 已移除 / 已改源字样
        for bad in ("巴斯夫", "PP-TD20", "PP-TD40", "亚洲金属网", "改性塑料"):
            ok(bad not in flat, f"② 全文不含「{bad}」"
               if bad not in flat else f"✗ 全文仍含「{bad}」")

        # ③ 新品种行
        rows = page.eval_on_selector_all(
            "table tr", "els => els.map(e => e.innerText.replace(/\\s+/g,' ').trim())")
        rowtext = " || ".join(rows)
        for name in ("镨钕金属", "PA6", "PA66", "PP T30S", "PP EP548R"):
            ok(name in rowtext, f"③ 明细表含 {name}" if name in rowtext
               else f"✗ 明细表缺 {name}")

        # ④ 市场口径标签
        for tag in ("PrNd≥99% · 中国", "BL3280H · 华南", "EPR27 · 神马塑料",
                    "大庆石化 · 沈阳", "大庆炼化 · 余姚"):
            ok(tag in rowtext, f"④ 市场标签「{tag}」"
               if tag in rowtext else f"✗ 市场标签缺「{tag}」")

        # ⑤ 当日取值（明细表数值无千分位；EP548R 按源报价日归位到 10-13）
        for val in ("900000", "15000", "19000", "10730", "10775"):
            ok(val in rowtext, f"⑤ 取值 {val} 已渲染" if val in rowtext
               else f"✗ 取值 {val} 未渲染")

        # ⑤b 精确列校验：EP548R 落 10-13（源报价日），T30S 落 10-14（当日）
        #     注意当日表头带「今日」后缀（"10/14\n今日"），须用前缀匹配
        pos = page.evaluate("""() => {
          const wrap = document.querySelector('.table-wrap');
          const heads = [...wrap.querySelectorAll('thead th')].map(e => e.innerText.trim());
          const i13 = heads.findIndex(h => h.indexOf('10/13') === 0);
          const i14 = heads.findIndex(h => h.indexOf('10/14') === 0);
          const out = {i13: i13, i14: i14};
          for (const tr of wrap.querySelectorAll('tbody tr')) {
            const cells = [...tr.querySelectorAll('td')].map(e => e.innerText.trim());
            const nm = cells[0] || '';
            if (nm.indexOf('PP EP548R') >= 0) out.ep = [cells[i13], cells[i14]];
            if (nm.indexOf('PP T30S') >= 0)  out.t30 = [cells[i13], cells[i14]];
          }
          return out;
        }""")
        ok(pos.get("ep") == ["10775", "-"],
           f"⑤b PP EP548R 落 10-13 列（{pos.get('ep')}），未伪标为 10-14"
           if pos.get("ep") == ["10775", "-"] else f"✗ PP EP548R 列位异常 {pos.get('ep')} idx={pos.get('i13')}/{pos.get('i14')}")
        ok(pos.get("t30") == ["-", "10730"],
           f"⑤b PP T30S 落 10-14 列（{pos.get('t30')}）"
           if pos.get("t30") == ["-", "10730"] else f"✗ PP T30S 列位异常 {pos.get('t30')} idx={pos.get('i13')}/{pos.get('i14')}")

        # ⑥ 分组
        for grp in ("稀土金属", "工程塑料", "PP 聚丙烯"):
            ok(grp in rowtext, f"⑥ 分组「{grp}」" if grp in rowtext
               else f"✗ 分组缺「{grp}」")

        # ⑦ 控制台
        shown = [e for e in errors if "favicon" not in e.lower()]
        ok(not shown, "⑦ 零 console 错误" if not shown else f"✗ console 错误 {shown[:3]}")

        browser.close()
    httpd.shutdown()

    print("=" * 70)
    for c in checks:
        print("  ✓", c)
    for f in fails:
        print("  ", f)
    print("=" * 70)
    print(f"通过 {len(checks)} 项，失败 {len(fails)} 项")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
