"""16 品种抓取 + 写历史 JSON + 生成 HTML 看板（分类趋势图 v4）
2026-07-02 —— 参照 PDF 快报风格，4 张分类趋势图，WTI 已补上
"""
import asyncio, sys, os, json, re
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ["NO_PROXY"] = "ccmn.cn,chinatungsten.com,smm.cn,hq.smm.cn,user.smm.cn,asianmetal.cn"

PROJECT   = Path(__file__).parent
DATA_FILE = PROJECT / "data" / "price_history.json"
HTML_OUT  = PROJECT / "docs" / "index.html"

# ========== 品种分类（参照 PDF 快报分组逻辑） ==========
CATEGORIES = [
    {
        "name": "铝及铝合金",
        "varieties": [
            ("A00_AL",  "A00铝（现货）", "ccmn",  "元/吨"),
            ("ADC12",   "ADC12",          "SMM",   "元/吨"),
            ("A380",    "A380",           "SMM",   "元/吨"),
            ("AlSi9Cu3","AlSi9Cu3",      "SMM",   "元/吨"),
            ("A356",    "A356",           "SMM",   "元/吨"),
        ],
    },
    {
        "name": "铜、金属硅、镁、锰",
        "varieties": [
            ("CU",              "铜（1#）",        "ccmn", "元/吨"),
            ("SI_553_331_AVG","金属硅中间价441",  "ccmn", "元/吨"),
            ("SI_3303_2202_MIN","金属硅中间价3303","ccmn","元/吨"),
            ("SI_553_331_MAX","金属硅中间价331",  "ccmn", "元/吨"),
            ("MG",              "镁（99.9%）",      "ccmn", "元/吨"),
            ("MN",              "电解锰",            "ccmn", "元/吨"),
        ],
    },
    {
        "name": "镁合金及闻喜镁锭",
        "varieties": [
            ("Wenxi_MG","闻喜镁锭 99.9%min","SMM",  "元/吨"),
            ("AM60B",   "AM60B 出厂价",     "SMM",  "元/吨"),
            ("AZ91D",   "AZ91D 出厂价",     "SMM",  "元/吨"),
        ],
    },
    {
        "name": "钨粉及 WTI 原油",
        "varieties": [
            ("W",   "钨粉（中钨在线）", "中钨", "元/千克"),
            ("WTI", "WTI 原油",         "akshare", "USD/bbl"),
        ],
    },
]

# 每类配色（Chart.js 用）
CAT_COLORS = [
    ["#3b82f6","#f59e0b","#ef4444","#22c55e","#06b6d4"],
    ["#8b5cf6","#6366f1","#a855f7","#ec4899","#14b8a6","#64748b"],
    ["#f43f5e","#e11d48","#be185d"],
    ["#78716c","#a8a29e"],
]

def key_to_label(k): return [v[1] for cat in CATEGORIES for v in cat["varieties"] if v[0]==k][0]
def key_to_src(k):   return [v[2] for cat in CATEGORIES for v in cat["varieties"] if v[0]==k][0]
def key_to_unit(k):  return [v[3] for cat in CATEGORIES for v in cat["varieties"] if v[0]==k][0]

# ========== 数据采集 ==========
async def _launch():
    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    b = await p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled","--no-sandbox"])
    return p, b

async def _login_smm(ctx):
    page = await ctx.new_page()
    await page.goto("https://user.smm.cn/login", timeout=30000, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)
    await page.locator("#userName").fill("13512903125")
    await page.locator("#password").fill("Lt_091788")
    await page.locator("#user_account_password_login_button").click()
    await asyncio.sleep(5)
    ok = "login" not in page.url.lower()
    await page.close()
    return ok

def _extract_smm(text, pat):
    m = re.search(pat, text)
    return int(m.group(3)) if m else None

def get_ccmn():
    from jinggong_monitor.fetcher_ccmn import CcmnFetcher
    return CcmnFetcher().fetch(datetime.now().strftime("%Y-%m-%d"))

async def get_smm():
    p, b = await _launch()
    ctx = await b.new_context(viewport={"width":1280,"height":900}, bypass_csp=True)
    if not await _login_smm(ctx):
        await b.close(); await p.stop()
        return {}
    page = await ctx.new_page()
    await page.goto("https://hq.smm.cn/aluminum", timeout=20000, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)
    al = await page.inner_text("body")
    mg_page = await ctx.new_page()
    await mg_page.goto("https://hq.smm.cn/magnesium", timeout=20000, wait_until="domcontentloaded")
    await mg_page.wait_for_timeout(5000)
    mg = await mg_page.inner_text("body")
    await mg_page.close(); await page.close(); await ctx.close()
    await b.close(); await p.stop()
    return {
        "ADC12":    _extract_smm(al, r"ADC12\D+?(\d+)\D+?(\d+)\D+?(\d+)"),
        "A380":     _extract_smm(al, r"A380\D+?(\d+)\D+?(\d+)\D+?(\d+)"),
        "AlSi9Cu3": _extract_smm(al, r"AlSi9Cu3\D+?(\d+)\D+?(\d+)\D+?(\d+)"),
        "A356":     _extract_smm(al, r"A356铝合金\s+\D+?(\d+)\D+?(\d+)\D+?(\d+)"),
        "Wenxi_MG": _extract_smm(mg, r"镁锭9990（闻喜）\D+?(\d+)\D+?(\d+)\D+?(\d+)"),
        "AM60B":    _extract_smm(mg, r"AM60B出厂价\D+?(\d+)\D+?(\d+)\D+?(\d+)"),
        "AZ91D":    _extract_smm(mg, r"AZ91D出厂价[^（]*?(\d+)\D+?(\d+)\D+?(\d+)"),
    }

# ========== 历史数据读写 ==========
def load_history():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {}

def save_history(history):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

# ========== HTML 看板生成 ==========
def build_html(history, today_str):
    dates = sorted(history.keys())
    today_data = history.get(today_str, {})

    # ---- 今日价格表 ----
    table_rows = ""
    for ci, cat in enumerate(CATEGORIES):
        table_rows += f'<tr class="cat-hdr"><td colspan="4">▌ {cat["name"]}</td></tr>\n'
        for key, label, src, unit in cat["varieties"]:
            v = today_data.get(key)
            if v is not None:
                if key == "WTI":
                    val = f"{v:.2f}"
                else:
                    val = f"{v:,.0f}"
                src_badge = f'<span class="badge">{src}</span>'
                table_rows += f'<tr><td class="vname">{label}</td><td>{src_badge}</td><td class="val">{val}</td><td class="unit">{unit}</td></tr>\n'
            else:
                src_badge = f'<span class="badge na">—</span>'
                table_rows += f'<tr><td class="vname">{label}</td><td>{src_badge}</td><td class="val na">—</td><td class="unit">—</td></tr>\n'

    # ---- 分类趋势图 JS ----
    chart_canvases = ""
    chart_js_blocks = ""
    for ci, cat in enumerate(CATEGORIES):
        canvas_id = f"c{ci}"
        colors = CAT_COLORS[ci]
        datasets = []
        for vi, (key, label, src, unit) in enumerate(cat["varieties"]):
            color = colors[vi % len(colors)]
            data_arr = [str(history[d].get(key)) if history[d].get(key) is not None else "null" for d in dates]
            # 单位后缀（tooltip 显示）
            unit_str = " 元/吨" if "元/吨" in unit else (" 元/千克" if "元/千克" in unit else " USD/bbl")
            datasets.append(
                f'{{label:"{label}",data:[{",".join(data_arr)}],'
                f'borderColor:"{color}",backgroundColor:"{color}18",'
                f'fill:true,tension:0.35,pointRadius:3,pointHoverRadius:6,borderWidth:2,'
                f'tooltipSuffix:"{unit_str}"}}'
            )

        chart_canvases += f'''
        <div class="card">
          <div class="card-title">{cat["name"]} · 历史趋势</div>
          <div class="chart-wrap"><canvas id="{canvas_id}"></canvas></div>
        </div>'''

        # Chart.js 配置（用 IIFE 避免变量冲突）
        chart_js_blocks += f'''
  (function(){{
    new Chart(document.getElementById("{canvas_id}"),{{
      type:"line",
      data:{{labels:{json.dumps(dates)},datasets:[{",".join(datasets)}]}},
      options:{{
        responsive:true,maintainAspectRatio:false,
        interaction:{{mode:"index",intersect:false}},
        plugins:{{
          legend:{{position:"top",labels:{{boxWidth:12,padding:12,font:{{size:12}}}}}},
          tooltip:{{callbacks:{{
            label:function(ctx){{
              const v = ctx.parsed.y;
              if(v===null) return ctx.dataset.label+": 无数据";
              const suffix = ctx.dataset.tooltipSuffix || "";
              return ctx.dataset.label+": "+v.toLocaleString()+suffix;
            }}
          }}}}
        }},
        scales:{{
          x:{{grid:{{display:false}},ticks:{{font:{{size:11}},maxRotation:45}}}},
          y:{{beginAtZero:false,
               grid:{{color:"#f1f5f9"}},
               ticks:{{font:{{size:11}},callback:v=>v.toLocaleString()}}}}
        }}
      }}
    }});
  }})();'''

    # ---- 完整 HTML ----
    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>精工有色金属 · 每日价格看板</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{
    font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
    background:#f0f4f8;color:#1e293b;
    padding:20px;max-width:1180px;margin:0 auto;
  }}
  .header{{margin-bottom:18px}}
  h1{{font-size:20px;font-weight:700;display:flex;align-items:center;gap:8px;margin-bottom:4px}}
  .sub{{color:#64748b;font-size:12.5px}}
  .card{{background:#fff;border-radius:10px;padding:16px 18px;
         box-shadow:0 1px 4px rgba(0,0,0,.06);margin-bottom:16px}}
  .card-title{{font-size:14px;font-weight:600;margin-bottom:10px;color:#334155}}
  .chart-wrap{{position:relative;height:320px}}

  /* 价格表 */
  .tbl{{width:100%;border-collapse:collapse;font-size:13px;margin-top:4px}}
  .tbl th,.tbl td{{padding:6px 10px;text-align:left;border-bottom:1px solid #e2e8f0}}
  .tbl th{{background:#f8fafc;font-weight:600;color:#475569;font-size:11.5px;position:sticky;top:0}}
  .cat-hdr td{{background:#f1f5f9;font-weight:700;color:#334155;font-size:12.5px;padding:7px 10px}}
  .vname{{font-weight:500;color:#334155}}
  .badge{{display:inline-block;padding:1px 7px;border-radius:4px;font-size:10.5px;font-weight:600;
          background:#dbeafe;color:#1e40af}}
  .badge.na{{background:#f1f5f9;color:#94a3b8}}
  .val{{font-weight:700;font-size:14px;text-align:right;font-variant-numeric:tabular-nums}}
  .val.na{{color:#cbd5e1}}
  .unit{{color:#94a3b8;font-size:11.5px}}

  .update-meta{{text-align:center;color:#94a3b8;font-size:11px;margin-top:12px;padding-top:10px;
               border-top:1px solid #e2e8f0}}

  @media(max-width:640px){{
    body{{padding:10px}} h1{{font-size:17px}} .card{{padding:10px}}
    .chart-wrap{{height:240px}} .tbl{{font-size:12px}}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>🏭 精工有色金属 · 每日价格看板</h1>
  <div class="sub">📅 {today_str} &nbsp;·&nbsp; 数据源：ccmn ／ SMM ／ akshare ／ 中钨在线 &nbsp;·&nbsp; 自动采集</div>
</div>

<div class="card">
  <div class="card-title">📅 今日价格（{today_str}）</div>
  <table class="tbl">
    <thead><tr><th>品种</th><th>数据源</th><th style="text-align:right">价格</th><th>单位</th></tr></thead>
    <tbody>{table_rows}</tbody>
  </table>
</div>

{chart_canvases}

<div class="update-meta">自动更新 · 每个交易日 17:00 &nbsp;·&nbsp; 共 {len(dates)} 个交易日历史数据</div>

<script>{chart_js_blocks}
</script>
</body>
</html>'''

# ========== 主流程 ==========
async def main():
    print("=" * 60)
    print(f"  精工有色金属 · 看板更新  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    today = datetime.now().strftime("%Y-%m-%d")

    # 1. 采集
    print("\n[1/4] ccmn ... ", end="", flush=True)
    ccmn = get_ccmn()
    print(f"{len(ccmn)} 品种")

    print("[2/4] SMM  ... ", end="", flush=True)
    smm = await get_smm()
    print(f"{len([v for v in smm.values() if v])} 品种")

    print("[3/4] WTI ... ", end="", flush=True)
    try:
        import akshare as ak
        df = ak.futures_foreign_commodity_realtime(symbol="CL")
        wti = round(float(df.iloc[0]["最新价"]), 2)
        print(f"{wti}  USD/bbl")
    except Exception as e:
        wti = None
        print(f"⚠️  {e}")

    print("[4/4] 钨粉 ... ", end="", flush=True)
    try:
        from jinggong_monitor.fetcher_tungsten import ChinatungstenFetcher
        w = ChinatungstenFetcher().fetch().get("W")
        print(f"{w}  元/千克" if w else "未获取")
    except Exception as e:
        w = None
        print(f"⚠️  {e}")

    # 2. 合并
    today_row = {}
    for cat in CATEGORIES:
        for key, label, src, unit in cat["varieties"]:
            if key in ("ADC12","A380","AlSi9Cu3","A356","Wenxi_MG","AM60B","AZ91D"):
                today_row[key] = smm.get(key)
            elif key == "W":
                today_row[key] = w
            elif key == "WTI":
                today_row[key] = wti
            else:
                today_row[key] = ccmn.get(key)

    # 3. 累计历史
    history = load_history()
    history[today] = today_row
    save_history(history)
    print(f"\n📦 历史数据: {len(history)} 个交易日")

    # 4. 生成 HTML
    html = build_html(history, today)
    HTML_OUT.parent.mkdir(parents=True, exist_ok=True)
    HTML_OUT.write_text(html, encoding="utf-8")
    print(f"📄 看板 HTML: {HTML_OUT}")

    print("\n" + "=" * 60)
    print("完成 ✅")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
