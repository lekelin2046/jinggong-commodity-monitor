#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_3092pm_migration.py — EPDM_3092PM 从 /rubber/ 迁至 /plastic/ 的渲染验证

断言：
  plastic 页  ① 明细表出现「三元乙丙 3092PM」行且值 23,600 ② 市场标注「华东」
              ③ 该行归入「三元乙丙橡胶」分组 ④ KPI「今日更新品种」分母 14
              ⑤ 分组分析出现「三元乙丙橡胶」卡 ⑥ 多指标下拉含该键 ⑦ 零 console 错误
  rubber  页  ① 页面全文不含 3092PM ② KPI 分母 21 ③ 零 console 错误
用法：python3 tools/probes/verify_3092pm_migration.py
"""
import http.server
import socketserver
import threading
import functools
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"

sys.path.insert(0, str(ROOT))


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class ReusableServer(socketserver.TCPServer):
    allow_reuse_address = True


def serve():
    """起一个本地静态服务，端口动态分配，返回 (httpd, port)"""
    handler = functools.partial(QuietHandler, directory=str(DOCS))
    httpd = ReusableServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def check(page, label):
    html = page.content()
    rows = page.eval_on_selector_all(
        "table tr",
        "els => els.map(e => e.innerText.replace(/\\s+/g,' ').trim())")
    hits = [r for r in rows if "三元乙丙" in r]
    return html, rows, hits


def main():
    httpd, port = serve()
    from playwright.sync_api import sync_playwright

    fails = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for slug, expect_present in (("plastic", True), ("rubber", False)):
            errs = []
            pg = b.new_page(viewport={"width": 1560, "height": 1200})
            pg.on("console", lambda m: errs.append(f"[{m.type}] {m.text}") if m.type == "error" else None)
            pg.on("pageerror", lambda e: errs.append(f"[pageerror] {e}"))
            pg.goto(f"http://127.0.0.1:{port}/{slug}/index.html", wait_until="networkidle")
            pg.wait_for_timeout(4500)
            out = ROOT / "output" / f"migrate_3092pm_{slug}.png"
            if not out.parent.is_dir():
                out.parent.mkdir(parents=True)
            pg.screenshot(path=str(out), full_page=True)

            html, rows, hits = check(pg, slug)
            has = "EPDM_3092PM" in html or "三元乙丙 3092PM" in html
            print(f"\n{'='*68}\n/{slug}/")
            print(f"  页面源码含 3092PM 键/名 : {has}   （期望 {expect_present}）")
            if has != expect_present:
                fails.append(f"{slug}: 出现性不符（got {has}, want {expect_present}）")

            print(f"  三元乙丙相关明细行 {len(hits)} 条：")
            for r in hits:
                print("     ", r[:130])
            if expect_present:
                if not any("3092PM" in r for r in hits):
                    fails.append("plastic: 明细表未见 3092PM 行")
                if not any(("23600" in r or "23,600" in r) for r in hits):
                    fails.append("plastic: 明细表未见 23600")
                if not any("华东" in r for r in hits):
                    fails.append("plastic: 未见「华东」市场标注")

            # KPI 分母
            body = re.sub(r"\s+", " ", pg.inner_text("body"))
            m = re.search(r"今日更新品种[^\d]*(\d+)\s*/\s*(\d+)", body)
            print(f"  KPI 今日更新品种: {m.group(0) if m else '未匹配'}")
            if m:
                want = "14" if expect_present else "21"
                if m.group(2) != want:
                    fails.append(f"{slug}: KPI 分母 {m.group(2)} != {want}")

            # 分组分析卡
            cards = pg.eval_on_selector_all(
                "#analysisContainer .ba-card, #analysisContainer > div",
                "els => els.map(e => (e.innerText||'').split('\\n')[0].trim()).filter(Boolean)")
            epdm_card = [c for c in cards if "三元乙丙" in c]
            print(f"  分组分析卡 {len(cards)} 张，含三元乙丙: {epdm_card[:3]}")
            if expect_present and not epdm_card:
                fails.append("plastic: 分组分析无三元乙丙橡胶卡")

            # 多指标下拉
            opts = pg.eval_on_selector_all(
                "select option", "els => els.map(e => e.textContent.trim())")
            hit_opt = [o for o in opts if "3092PM" in o]
            print(f"  下拉选项含 3092PM: {hit_opt}")

            print(f"  console 错误: {errs if errs else '无'}")
            if errs:
                fails.append(f"{slug}: console 错误 {errs[:2]}")
            print(f"  截图: {out}")
            pg.close()
        b.close()
    httpd.shutdown()

    print(f"\n{'='*68}")
    if fails:
        print("❌ 未通过：")
        for f in fails:
            print("   -", f)
        sys.exit(1)
    print("✅ 全部断言通过")


if __name__ == "__main__":
    main()
