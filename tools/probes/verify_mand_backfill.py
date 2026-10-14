#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""曼德看板历史回填验证（AL_A00 由客户走势工作簿回填后）。

校验链：
  ① data.json 层：AL_A00 覆盖天数、段结构、边界值、已有值未被覆盖
  ② 页面渲染层：起本地 HTTP 服务 + Playwright 载入 docs/mand/index.html
     - 无 JS 报错
     - 切到 2026-01 / 2026-08 / 2026-09 三个月份，逐列核对 AL_A00 单元格
     - KPI 卡片中 AL_A00 有值（非「—」）
     - 单品趋势图选 AL_A00 + 今年范围，数据点数与 data.json 一致

用法：python3 tools/probes/verify_mand_backfill.py
"""
import functools
import http.server
import json
import pathlib
import socketserver
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"

PASS, FAIL = [], []


def ok(cond, msg):
    (PASS if cond else FAIL).append(msg)
    print(("  ✓ " if cond else "  ✗ ") + msg)


def serve():
    class H(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    class S(socketserver.TCPServer):
        allow_reuse_address = True

    h = functools.partial(H, directory=str(DOCS))
    httpd = S(("127.0.0.1", 0), h)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def main() -> int:
    doc = json.loads((DOCS / "mand" / "data.json").read_text(encoding="utf-8"))
    d = doc["data"]
    a00_days = sorted(k for k in d if d[k].get("AL_A00") is not None)

    print("=== ① data.json 层 ===")
    ok(len(a00_days) == 159, f"AL_A00 覆盖 {len(a00_days)} 天（预期 159）")
    ok(a00_days[0] == "2026-01-05", f"首日 {a00_days[0]}（预期 2026-01-05）")
    ok(a00_days[-1] == "2026-10-14", f"末日 {a00_days[-1]}（预期 2026-10-14）")
    ok(d["2026-01-05"]["AL_A00"] == 23310, f"01-05 取值 {d['2026-01-05']['AL_A00']}（预期 23310）")
    ok(d["2026-08-18"]["AL_A00"] == 23900, f"08-18 取值 {d['2026-08-18']['AL_A00']}（预期 23900）")
    ok(d["2026-08-19"].get("AL_A00") is None, "08-19 留空（工作簿未覆盖，未编造）")
    ok(d["2026-09-16"].get("AL_A00") is None, "09-16 留空（工作簿未覆盖，未编造）")
    ok(d["2026-09-17"]["AL_A00"] == 24180, f"09-17 实时抓取值保留 {d['2026-09-17']['AL_A00']}（预期 24180）")
    ok(d["2026-10-14"]["AL_A00"] == 23620, f"10-14 最新值 {d['2026-10-14']['AL_A00']}（预期 23620）")
    ok(doc["total_days"] == 186, f"总天数 {doc['total_days']}（未新增日期列，预期 186）")
    ok("客户物料价格走势工作簿" in doc.get("backfill_note", ""), "backfill_note 已标注工作簿来源")

    print("\n=== ② 页面渲染层 ===")
    httpd, port = serve()
    try:
        from playwright.sync_api import sync_playwright

        errors = []
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto(f"http://127.0.0.1:{port}/mand/index.html",
                    wait_until="networkidle", timeout=45000)
            pg.wait_for_timeout(2500)

            ok(not errors, f"页面无 JS 报错" + (f"（{errors[:2]}）" if errors else ""))

            # KPI 卡片
            kpi = pg.evaluate("() => (document.getElementById('kpiRow')||{}).innerText || ''")
            ok("A00" in kpi, "KPI 卡片含 A00 品种")
            ok(str(d["2026-10-14"]["AL_A00"]).replace(".0", "") in kpi.replace(",", ""),
               f"KPI 卡片 A00 显示当日值（{kpi.replace(chr(10), ' | ')[:100]}）")

            def cell(month_value, head_label, variety_kw):
                """切到某月，取某品种行在指定表头列的单元格文本。"""
                pg.select_option("#monthSelect", month_value)
                pg.wait_for_timeout(900)
                return pg.evaluate(
                    """([hl, kw]) => {
                      const wrap = document.querySelector('#tableContainer');
                      const heads = [...wrap.querySelectorAll('thead th')].map(e=>e.innerText.trim());
                      const idx = heads.findIndex(h => h.startsWith(hl));
                      let hit = null;
                      for (const tr of wrap.querySelectorAll('tbody tr')) {
                        const c = [...tr.querySelectorAll('td')].map(e=>e.innerText.trim());
                        if ((c[0]||'').indexOf(kw) >= 0) { hit = {name:c[0], cell: idx>=0 ? c[idx] : null, n:c.length}; break; }
                      }
                      return {idx, hit};
                    }""", [head_label, variety_kw])

            jun = cell("01", "1/5", "A00铝")
            ok(jun["hit"] and jun["hit"]["cell"] == "23310",
               f"2026-01 表 1/5 列 A00 = {jun['hit']['cell'] if jun['hit'] else None}（预期 23310）")

            aug = cell("08", "8/18", "A00铝")
            ok(aug["hit"] and aug["hit"]["cell"] == "23900",
               f"2026-08 表 8/18 列 A00 = {aug['hit']['cell'] if aug['hit'] else None}（预期 23900）")

            aug19 = cell("08", "8/19", "A00铝")
            ok(aug19["hit"] and aug19["hit"]["cell"] in ("-", "—", ""),
               f"2026-08 表 8/19 列 A00 留空（实际 {aug19['hit']['cell'] if aug19['hit'] else None}）")

            sep = cell("09", "9/17", "A00铝")
            ok(sep["hit"] and sep["hit"]["cell"] == "24180",
               f"2026-09 表 9/17 列 A00 = {sep['hit']['cell'] if sep['hit'] else None}（预期 24180）")

            # 单品趋势：AL_A00 全年数据点（按交易日轴铺满，缺口为 null 断点）
            pg.select_option("#singleTrendVariety", "AL_A00")
            pg.wait_for_timeout(600)
            pg.evaluate("() => setSingleTrendRange('ytd')")
            pg.wait_for_timeout(1800)
            ts = pg.evaluate("""() => {
              const c = (window.Chart && Chart.getChart) ? Chart.getChart('singleTrendChart') : null;
              if (!c) return null;
              const dd = c.data.datasets[0].data || [];
              return {slots: dd.length, nonNull: dd.filter(v => v !== null && v !== undefined).length};
            }""")
            ok(ts is not None, "趋势图实例可取到")
            if ts:
                ok(ts["slots"] == doc["total_days"],
                   f"趋势图交易日槽位 {ts['slots']} 个（= 全年交易日 {doc['total_days']}）")
                ok(ts["nonNull"] == len(a00_days),
                   f"趋势图非空点 {ts['nonNull']} 个（= AL_A00 有值 {len(a00_days)} 天，缺口留断点）")

            b.close()
    finally:
        httpd.shutdown()

    print(f"\n=== 结果：{len(PASS)} 项通过 / {len(FAIL)} 项失败 ===")
    for f in FAIL:
        print("  ✗ " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
