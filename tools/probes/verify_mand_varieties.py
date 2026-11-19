#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_mand_varieties.py — 曼德看板 2026-10-14 品种口径优化的渲染验证

断言（本地起静态服务 + Playwright 无头浏览器）：
  ① badge 文案为「14 品种 · 14 项已接入（长江有色 3 / SMM 6 / 卓创 5）」
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
        badge = "14 品种 · 14 项已接入（长江有色 3 / SMM 6 / 卓创 5）"
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

        # ⑤ 当日取值（动态读 data.json 最新日，不再硬编码 10-14 快照，避免随数据推进而失效）
        import json
        doc = json.loads((ROOT / "docs" / "mand" / "data.json").read_text(encoding="utf-8"))
        latest = max(doc["data"].keys())
        latest_row = doc["data"][latest]
        def _shown(v):
            f = float(v)
            return str(int(f)) if f.is_integer() else f"{f:.2f}"
        shown_vals = [_shown(v) for v in latest_row.values()]
        for val in shown_vals:
            ok(val in rowtext, f"⑤ 最新日({latest})取值 {val} 已渲染" if val in rowtext
               else f"✗ 最新日取值 {val} 未渲染")

        # ⑤b 精确列校验：最新日期列，逐品种比对页面单元格数值与 data.json（含小数容差）
        mmdd = latest[5:7] + "/" + latest[8:10]
        pos = page.evaluate("""({mmdd, expect}) => {
          const wrap = document.querySelector('.table-wrap');
          const heads = [...wrap.querySelectorAll('thead th')].map(e => e.innerText.trim());
          const idx = heads.findIndex(h => h.indexOf(mmdd) === 0);
          const out = {idx: idx, diffs: []};
          if (idx < 0) return out;
          for (const tr of wrap.querySelectorAll('tbody tr')) {
            const span = tr.querySelector('.variety-name');
            if (!span) continue;
            const code = span.dataset.code || '';
            if (!(code in expect)) continue;
            const tds = [...tr.querySelectorAll('td')].map(e => e.innerText.trim());
            const got = parseFloat(String(tds[idx]).replace(/,/g, ''));
            if (!isFinite(got) || Math.abs(got - expect[code]) > 0.005)
              out.diffs.push(code + ':' + tds[idx] + '≠' + expect[code]);
          }
          return out;
        }""", {"mmdd": mmdd, "expect": latest_row})
        ok(pos.get("idx", -1) >= 0, f"⑤b 最新日表头 {mmdd} 存在（idx={pos.get('idx')}）"
           if pos.get("idx", -1) >= 0 else f"✗ 最新日表头 {mmdd} 未找到")
        ok(not pos.get("diffs"), f"⑤b 最新日 {latest} 全品种列位数值一致（{len(latest_row)} 项）"
           if not pos.get("diffs") else f"✗ 列位数值不符 {pos.get('diffs')}")

        # ⑥ 黄金 AU（2026-11-19 新增）：明细表行 + 元/克单位 + 小数未被 Math.round 抹平
        ok("黄金（金99）" in rowtext, "⑥ 明细表含黄金（金99）" if "黄金（金99）" in rowtext
           else "✗ 明细表缺黄金（金99）")
        # 金99 当日值 797.75 —— KPI/明细应显示两位小数，而非取整成 798
        gold_view = page.evaluate("""() => {
          const flat = document.body.innerText.replace(/\\s+/g, ' ');
          return { hasDecimal: flat.indexOf('797.75') >= 0, hasRounded: /(^|\\D)798(\\D|$)/.test(flat) };
        }""")
        ok(gold_view["hasDecimal"], "⑥ 黄金小数 797.75 完整显示（未被取整）"
           if gold_view["hasDecimal"] else f"✗ 黄金小数未显示 {gold_view}")
        # 明细表黄金属元/克（非默认元/吨）
        au_unit = page.evaluate("""() => {
          for (const tr of document.querySelectorAll('table tr')) {
            const tds = [...tr.querySelectorAll('td')].map(e => e.innerText.trim());
            if (tds[0] && tds[0].indexOf('黄金') >= 0) return tds[1] || '';
          }
          return '';
        }""")
        ok(au_unit == "元/克", f"⑥ 黄金单位为元/克（实际 {au_unit}）"
           if au_unit == "元/克" else f"✗ 黄金单位异常 {au_unit}")

        # ⑦ 分组
        for grp in ("稀土金属", "工程塑料", "PP 聚丙烯"):
            ok(grp in rowtext, f"⑥ 分组「{grp}」" if grp in rowtext
               else f"✗ 分组缺「{grp}」")

        # ⑧ 控制台
        shown = [e for e in errors if "favicon" not in e.lower()]
        ok(not shown, "⑧ 零 console 错误" if not shown else f"✗ console 错误 {shown[:3]}")

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
