#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多指标价格曲线对比 · 浏览器功能测试（Playwright）

验证：卡片结构 / 默认选中 / 6 档聚合切换 / 日期范围预设 / 消除曲线断点 /
      区间手填+确定 / 明细表联动 / 曲线下载 PNG 生成 / 无 JS 报错。
用法：python3 test_multi_trend.py [端口]
"""
import json
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8731"
PAGES = [
    ("橡胶页", f"http://127.0.0.1:{PORT}/docs/rubber/index.html"),
    ("内外饰页", f"http://127.0.0.1:{PORT}/docs/plastic/index.html"),
]

FAIL = []


def check(label, cond, detail=""):
    print(("  ✓ " if cond else "  ✗ ") + label + (f"  {detail}" if detail else ""))
    if not cond:
        FAIL.append(label)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for name, url in PAGES:
        print("=" * 78)
        print(f"{name}  {url}")
        print("=" * 78)
        page = browser.new_page(viewport={"width": 1500, "height": 1100})
        errors, console_errs = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: console_errs.append(m.text) if m.type == "error" else None)

        page.goto(url, wait_until="load")
        page.wait_for_timeout(2500)

        # --- 结构 ---
        check("卡片存在", page.locator("#singleTrendCard").count() == 1)
        title = page.locator("#singleTrendCard .mt-title").inner_text().strip()
        check("标题为「多指标价格曲线对比」", title == "多指标价格曲线对比", f"实际={title!r}")
        n_tabs = page.locator("#mtTabs .mt-tab").count()
        check("聚合档位=6（日/周/月/季/半年/年）", n_tabs == 6, f"实际={n_tabs}")
        tab_txt = [t.strip() for t in page.locator("#mtTabs .mt-tab").all_inner_texts()]
        check("档位文案正确", tab_txt == ["日价格", "周价格", "月价格", "季价格", "半年价格", "年价格"], str(tab_txt))
        check("曲线下载按钮存在", page.locator(".mt-dl").count() == 1)
        check("消除曲线断点复选框存在", page.locator("#mtSpanGaps").count() == 1)
        check("日期范围 4 档预设", page.locator("#mtQuickRange .seg-btn").count() == 4)
        check("起止日期输入框存在", page.locator("#mtStart").count() == 1 and page.locator("#mtEnd").count() == 1)
        check("确定按钮存在", page.locator(".mt-apply").count() == 1)

        # --- 默认状态 ---
        st = page.evaluate("""() => ({
            codes: Array.from(MS_STATE.msTrend || []),
            agg: trendAgg, start: trendStart, end: trendEnd,
            ds: (window._singleTrendChart ? window._singleTrendChart.data.datasets.length : 0),
            labels: (window._singleTrendChart ? window._singleTrendChart.data.labels.length : 0),
            names: (window._singleTrendChart ? window._singleTrendChart.data.datasets.map(d=>d.label) : []),
            spanGaps: (window._singleTrendChart ? window._singleTrendChart.data.datasets.map(d=>d.spanGaps) : [])
        })""")
        check("默认选中 2 项（SCRWF + RSS3）", len(st["codes"]) == 2, str(st["codes"]))
        check("默认聚合=日价格", st["agg"] == "day", st["agg"])
        check("默认区间约 1 年", bool(st["start"]) and bool(st["end"]), f"{st['start']} ~ {st['end']}")
        check("图表已生成 2 条曲线", st["ds"] == 2, f"datasets={st['ds']}")
        check("日价格点数 > 200", st["labels"] > 200, f"labels={st['labels']}")
        check("图例含品种名+单位", all("(" in n for n in st["names"]), str(st["names"]))

        # --- 聚合切换 ---
        for agg, expect_min, expect_max in [("week", 40, 70), ("month", 10, 16),
                                           ("quarter", 4, 6), ("half", 2, 4), ("year", 1, 3)]:
            page.click(f'#mtTabs .mt-tab[data-agg="{agg}"]')
            page.wait_for_timeout(320)
            r = page.evaluate("() => ({agg:trendAgg, n:window._singleTrendChart.data.labels.length,"
                              " act:document.querySelector('#mtTabs .mt-tab.active').dataset.agg})")
            check(f"{agg} 聚合生效且点数合理", r["agg"] == agg and r["act"] == agg and expect_min <= r["n"] <= expect_max,
                  f"labels={r['n']}（期望 {expect_min}~{expect_max}）")
        page.click('#mtTabs .mt-tab[data-agg="day"]')
        page.wait_for_timeout(300)

        # --- 日期范围预设 ---
        for months, lo, hi in [(1, 15, 35), (3, 50, 80), (6, 100, 145), (12, 220, 270)]:
            page.click(f'#mtQuickRange .seg-btn[data-months="{months}"]')
            page.wait_for_timeout(300)
            r = page.evaluate("() => ({n:window._singleTrendChart.data.labels.length,"
                              " s:trendStart, e:trendEnd,"
                              " act:document.querySelector('#mtQuickRange .seg-btn.active')?.dataset.months})")
            check(f"{months}月预设生效", lo <= r["n"] <= hi and r["act"] == str(months),
                  f"labels={r['n']}（期望 {lo}~{hi}）{r['s']}~{r['e']}")
        check("起止输入框已同步", page.input_value("#mtStart") != "" and page.input_value("#mtEnd") != "")

        # --- 手填区间 + 确定 ---
        page.fill("#mtStart", "2021-01-04")
        page.fill("#mtEnd", "2021-12-31")
        page.click(".mt-apply")
        page.wait_for_timeout(350)
        r = page.evaluate("() => ({s:trendStart,e:trendEnd,n:window._singleTrendChart.data.labels.length})")
        check("手填区间+确定生效", r["s"] == "2021-01-04" and r["e"] == "2021-12-31" and 240 <= r["n"] <= 260,
              f"{r['s']}~{r['e']} labels={r['n']}")

        # --- 消除曲线断点 ---
        page.click("#mtSpanGaps")
        page.wait_for_timeout(300)
        sg = page.evaluate("() => window._singleTrendChart.data.datasets.map(d=>d.spanGaps)")
        check("勾选后 spanGaps=true", all(v is True for v in sg), str(sg))
        page.click("#mtSpanGaps")
        page.wait_for_timeout(300)
        sg = page.evaluate("() => window._singleTrendChart.data.datasets.map(d=>d.spanGaps)")
        check("取消后 spanGaps=false", all(v is False for v in sg), str(sg))

        # --- 多选联动 ---
        page.evaluate("() => { MS_STATE.msTrend = new Set(Array.from(MS_STATE.msTrend).concat(['ACC_M']));renderMsList('msTrend','msTrendList');renderSingleTrend(); }")
        page.wait_for_timeout(320)
        check("增选后曲线数增加", page.evaluate("() => window._singleTrendChart.data.datasets.length") == 3)

        # --- 明细表点品种名联动 ---
        page.evaluate("() => selectSingleTrend('AL_A00')")
        page.wait_for_timeout(350)
        r = page.evaluate("() => ({n:window._singleTrendChart.data.datasets.length,"
                          " codes:Array.from(MS_STATE.msTrend),"
                          " name:window._singleTrendChart.data.datasets[0].label})")
        check("明细表联动：改为单选该品种",
              r["n"] == 1 and r["codes"] == ["AL_A00"] and "A00" in r["name"], str(r))

        # --- 曲线下载 ---
        dl = page.evaluate("""() => {
            const src = document.getElementById('singleTrendChart');
            const tmp = document.createElement('canvas');
            tmp.width = src.width; tmp.height = src.height;
            const ctx = tmp.getContext('2d');
            ctx.fillStyle = '#fff'; ctx.fillRect(0,0,tmp.width,tmp.height);
            ctx.drawImage(src, 0, 0);
            const url = tmp.toDataURL('image/png');
            return { len: url.length, head: url.slice(0,22), w: tmp.width, h: tmp.height };
        }""")
        check("导出 PNG 数据有效", dl["len"] > 5000 and dl["head"].startswith("data:image/png"),
              f"len={dl['len']} {dl['w']}x{dl['h']}")
        page.evaluate("() => downloadTrendChart()")   # 确认不抛异常
        page.wait_for_timeout(200)
        check("downloadTrendChart() 无异常", len(errors) == 0, str(errors[:2]))

        # --- JS 错误 ---
        check("无未捕获 JS 异常", len(errors) == 0, str(errors[:3]))
        check("无 console.error", len(console_errs) == 0, str(console_errs[:3]))

        # --- 截图 ---
        page.click("#mtQuickRange .seg-btn[data-months=\"12\"]")
        page.wait_for_timeout(400)
        el = page.locator("#singleTrendCard")
        el.screenshot(path=f"/tmp/multitrend_{name}.png")
        print(f"  → 截图 /tmp/multitrend_{name}.png")
        page.close()

    browser.close()

print()
print("=" * 78)
if FAIL:
    print(f"❌ 失败 {len(FAIL)} 项：")
    for f in FAIL:
        print("   -", f)
    sys.exit(1)
print("✅ 全部通过")
