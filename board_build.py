"""board_build.py v5 — 月度日趋势图 + 年度趋势图 + 横拉月度明细表
2026-07-03：SQLite 化，支持年份/月份切换，Excel 历史数据已通过 import_excel.py 导入
用法：python3 board_build.py          # 采集今日价格 → 写入 SQLite → 生成看板
      python3 board_build.py --html-only  # 仅生成 HTML（不采集）
"""
import asyncio, sys, os, json, sqlite3, re, math
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
os.environ["NO_PROXY"] = "ccmn.cn,chinatungsten.com,smm.cn,hq.smm.cn,user.smm.cn,asianmetal.cn"

PROJECT  = Path(__file__).parent
DB_PATH  = PROJECT / "data" / "prices.db"
HTML_OUT = PROJECT / "docs" / "index.html"
DATA_DIR = PROJECT / "data"

# ============== 品种定义 ==============
CATEGORIES = [
    {"name": "铝及铝合金", "codes": ["ADC12", "A380", "AlSi9Cu3", "A356", "A00_AL"]},
    {"name": "铜硅镁锰",   "codes": ["CU", "SI_441", "SI_3303", "SI_331", "MG", "MN"]},
    {"name": "镁合金",     "codes": ["Wenxi_MG", "AM60B", "AZ91D"]},
    {"name": "钨粉及原油", "codes": ["W", "WTI"]},
]

VARIETY_NAMES = {
    "ADC12": "ADC12", "A380": "A380", "AlSi9Cu3": "AlSi9Cu3", "A356": "A356",
    "A00_AL": "A00铝", "CU": "铜",
    "SI_441": "硅441", "SI_3303": "硅3303", "SI_331": "硅331",
    "MG": "镁", "MN": "电解锰",
    "Wenxi_MG": "闻喜镁锭", "AM60B": "AM60B", "AZ91D": "AZ91D",
    "W": "钨粉", "WTI": "WTI原油",
}

VARIETY_UNITS = {
    "W": "元/千克", "WTI": "USD/bbl",
}
DEFAULT_UNIT = "元/吨"

# Chart 颜色
CHART_COLORS = [
    "#2563eb","#dc2626","#16a34a","#ca8a04","#9333ea",
    "#0891b2","#ea580c","#4f46e5","#be123c","#0d9488",
    "#d97706","#7c3aed",
]

# ============== 数据库初始化 ==============
def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            date   TEXT NOT NULL,
            code   TEXT NOT NULL,
            price  REAL,
            source TEXT DEFAULT 'auto',
            PRIMARY KEY (date, code)
        )
    """)
    return conn


# ============== 数据采集 ==============
async def fetch_ccmn():
    from jinggong_monitor.fetcher_ccmn import CcmnFetcher
    f = CcmnFetcher()
    today = datetime.now().strftime("%Y-%m-%d")
    return f.fetch(today) or {}


async def fetch_smm():
    """headless 自动登录 SMM → 抓 7 品种"""
    from playwright.async_api import async_playwright
    SMM_USER = "13512903125"
    SMM_PASS = "Lt_091788"

    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width": 1280, "height": 900}, bypass_csp=True)
        page = await ctx.new_page()

        # 登录
        await page.goto("https://user.smm.cn/login", timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        await page.locator("#userName").fill(SMM_USER)
        await page.locator("#password").fill(SMM_PASS)
        await page.locator("#user_account_password_login_button").click()
        await asyncio.sleep(5)

        results = {}

        # 铝页
        await page.goto("https://hq.smm.cn/aluminum", timeout=20000, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        al = await page.inner_text("body")

        # 镁页
        page2 = await ctx.new_page()
        await page2.goto("https://hq.smm.cn/magnesium", timeout=20000, wait_until="domcontentloaded")
        await page2.wait_for_timeout(5000)
        mg = await page2.inner_text("body")

        patterns = {
            "ADC12":    (al, r"SMM铝合金ADC12\D+?(\d+)\D+?(\d+)\D+?(\d+)"),
            "A380":     (al, r"A380铝合金\D+?(\d+)\D+?(\d+)\D+?(\d+)"),
            "AlSi9Cu3": (al, r"AlSi9Cu3铝合金\D+?(\d+)\D+?(\d+)\D+?(\d+)"),
            "A356":     (al, r"A356铝合金\D+?(\d+)\D+?(\d+)\D+?(\d+)"),
            "Wenxi_MG": (mg, r"镁锭9990[（(]闻喜[）)]\D+?(\d+)\D+?(\d+)\D+?(\d+)"),
            "AM60B":    (mg, r"AM60B出厂价\D+?(\d+)\D+?(\d+)\D+?(\d+)"),
            "AZ91D":    (mg, r"AZ91D出厂价[^（]*?(\d+)\D+?(\d+)\D+?(\d+)"),
        }
        for code, (text, pat) in patterns.items():
            m = re.search(pat, text)
            if m:
                results[code] = int(m.group(3))

        await page2.close()
        await page.close()
        await ctx.close()
        await b.close()
    return results


def fetch_wti():
    """akshare WTI 时点价"""
    try:
        import akshare as ak
        df = ak.futures_foreign_commodity_realtime(symbol="CL")
        if df is not None and not df.empty:
            return float(df.iloc[0]["最新价"])
    except Exception as e:
        print(f"  ⚠️ WTI 抓取失败: {e}")
    return None


def fetch_tungsten():
    """中钨在线钨粉"""
    try:
        from jinggong_monitor.fetcher_tungsten import ChinatungstenFetcher
        f = ChinatungstenFetcher()
        prices = f.fetch()
        return prices.get("W", None)
    except Exception as e:
        print(f"  ⚠️ 钨粉抓取失败: {e}")
    return None


def save_today(conn, data: dict):
    today = datetime.now().strftime("%Y-%m-%d")
    for code, price in data.items():
        if price is None:
            continue
        try:
            conn.execute(
                "INSERT OR REPLACE INTO prices (date, code, price, source) VALUES (?,?,?,?)",
                (today, code, float(price), "auto")
            )
        except Exception as e:
            print(f"  ⚠️ 保存 {code}={price}: {e}")
    conn.commit()


# ============== 数据查询辅助 ==============
def load_prices(conn):
    """返回 {date_str: {code: price}}"""
    data = defaultdict(dict)
    for row in conn.execute("SELECT date, code, price FROM prices ORDER BY date"):
        data[row[0]][row[1]] = row[2]
    return dict(data)


def get_months(data: dict):
    """从数据中提取所有年-月"""
    months = sorted(set(d[:7] for d in data.keys()))
    return months


def month_dates(year, month):
    """返回某月所有日期（1日到最后一天）"""
    first = datetime(year, month, 1)
    if month == 12:
        last = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = datetime(year, month + 1, 1) - timedelta(days=1)
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def monthly_avg(data: dict, year: int, month: int):
    """返回某月各品种的均价"""
    prefix = f"{year}-{month:02d}"
    sums = defaultdict(float)
    counts = defaultdict(int)
    for d, prices in data.items():
        if d.startswith(prefix):
            for code, p in prices.items():
                if p:
                    sums[code] += p
                    counts[code] += 1
    return {c: round(sums[c] / counts[c], 2) for c in sums if counts[c] > 0}


# ============== HTML 生成 ==============
def build_html(all_data: dict, today_str: str) -> str:
    months = get_months(all_data)
    if not months:
        return "<html><body><h2>暂无数据</h2></body></html>"

    latest_month = months[-1]
    year_start = months[0][:4]
    year_end = months[-1][:4]

    # 嵌入 JSON
    data_json = json.dumps(all_data, ensure_ascii=False)
    names_json = json.dumps(VARIETY_NAMES, ensure_ascii=False)
    units_json = json.dumps(VARIETY_UNITS, ensure_ascii=False)
    cats_json = json.dumps(CATEGORIES, ensure_ascii=False)
    colors_json = json.dumps(CHART_COLORS, ensure_ascii=False)

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>有色金属每日价格看板</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#f1f5f9;color:#1e293b;padding:16px}}
.header{{display:flex;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap}}
.header h1{{font-size:18px;white-space:nowrap}}
.header .updated{{color:#64748b;font-size:12px;margin-left:auto}}
.controls{{display:flex;gap:8px;align-items:center;margin-bottom:14px}}
.controls select{{padding:4px 8px;border:1px solid #cbd5e1;border-radius:6px;font-size:13px;background:#fff;cursor:pointer}}
.card{{background:#fff;border-radius:10px;padding:14px 16px;box-shadow:0 1px 3px rgba(0,0,0,.06);margin-bottom:14px}}
.card h3{{font-size:14px;font-weight:600;margin-bottom:8px;color:#334155}}
.chart-wrap{{position:relative;height:240px}}
.chart-wrap.annual{{height:300px}}

/* 横拉表 */
.table-wrap{{overflow-x:auto;margin-top:4px;-webkit-overflow-scrolling:touch}}
.table-wrap table{{border-collapse:collapse;font-size:12px;white-space:nowrap;min-width:100%}}
.table-wrap th,.table-wrap td{{padding:5px 8px;border:1px solid #e2e8f0;text-align:center}}
.table-wrap thead th{{background:#f8fafc;position:sticky;top:0;z-index:2;font-weight:600}}
.table-wrap tbody td{{min-width:60px}}
.table-wrap .sticky-col{{position:sticky;left:0;background:#f8fafc;z-index:1;text-align:left;font-weight:600;min-width:90px}}
.table-wrap thead .sticky-col{{z-index:3}}
.table-wrap .cat-row td{{background:#e2e8f0;font-weight:700;text-align:left;font-size:12px;padding:3px 8px;position:sticky;left:0;z-index:1}}
.table-wrap .cat-row td:first-child{{z-index:3}}
.no-data{{color:#94a3b8}}
.avg-col{{background:#fefce8;font-weight:600}}
.unit-tag{{font-size:10px;color:#94a3b8;margin-left:2px}}

@media (max-width:768px){{
  body{{padding:8px}}
  .card{{padding:10px}}
  .chart-wrap{{height:200px}}
}}
</style>
</head>
<body>

<div class="header">
  <h1>📊 有色金属每日价格看板</h1>
  <span class="updated">最后更新: {today_str}</span>
</div>

<div class="controls">
  <select id="yearSelect" onchange="switchMonth()"></select>
  <select id="monthSelect" onchange="switchMonth()"></select>
</div>

<div id="charts"></div>

<div class="card">
  <h3>📋 月度价格明细表（左右横拉 →）</h3>
  <div class="table-wrap" id="tableContainer"></div>
</div>

<script>
// ===== DATA =====
const ALL_DATA = {data_json};
const VARIETY_NAMES = {names_json};
const VARIETY_UNITS = {units_json};
const CATEGORIES = {cats_json};
const COLORS = {colors_json};
const CHART_IDS = [];

const DEFAULT_UNIT = "元/吨";

// ===== SELECTOR =====
function initSelectors() {{
  const months = Object.keys(ALL_DATA).map(d => d.substring(0,7));
  const uniqueMonths = [...new Set(months)].sort();
  const years = [...new Set(uniqueMonths.map(m => m.substring(0,4)))].sort();
  
  const ys = document.getElementById("yearSelect");
  const ms = document.getElementById("monthSelect");
  ys.innerHTML = years.map(y => `<option value="${{y}}">${{y}}年</option>`).join("");
  
  if(uniqueMonths.length > 0) {{
    const [ly, lm] = uniqueMonths[uniqueMonths.length-1].split("-");
    ys.value = ly;
    updateMonthOptions(ly, lm);
  }}
}}

function updateMonthOptions(year, selectedMonth) {{
  const ms = document.getElementById("monthSelect");
  const mm = ALL_DATA ? Object.keys(ALL_DATA)
    .filter(d => d.startsWith(year))
    .map(d => d.substring(5,7))
    .filter((v,i,a) => a.indexOf(v)===i)
    .sort() : [];
  ms.innerHTML = mm.map(m => `<option value="${{m}}">${{m}}月</option>`).join("");
  if(selectedMonth && mm.includes(selectedMonth)) ms.value = selectedMonth;
  else if(mm.length > 0) ms.value = mm[mm.length-1];
}}

function switchMonth() {{
  const y = document.getElementById("yearSelect").value;
  const prevMonth = document.getElementById("monthSelect").value;
  updateMonthOptions(y, prevMonth);
  const m = document.getElementById("monthSelect").value;
  renderAll(y, parseInt(m));
}}

function getSelected() {{
  return {{
    year: parseInt(document.getElementById("yearSelect").value),
    month: parseInt(document.getElementById("monthSelect").value)
  }};
}}

// ===== RENDER =====
function renderAll(year, month) {{
  destroyCharts();
  const container = document.getElementById("charts");
  container.innerHTML = "";
  
  renderMonthlyTrends(container, year, month);
  renderAnnualTrend(container, year);
  renderTable(year, month);
}}

// 月度日趋势图
function renderMonthlyTrends(container, year, month) {{
  const prefix = `${{year}}-${{String(month).padStart(2,"0")}}`;
  const days = getMonthDays(year, month);
  const labels = days.map(d => d.getDate());
  
  CATEGORIES.forEach(cat => {{
    const card = document.createElement("div");
    card.className = "card";
    const cid = "chart-" + Math.random().toString(36).substr(2,6);
    card.innerHTML = `<h3>📈 ${{cat.name}} · 日趋势</h3><div class="chart-wrap"><canvas id="${{cid}}"></canvas></div>`;
    container.appendChild(card);
    
    const datasets = cat.codes.map((code, i) => {{
      const points = days.map(d => {{
        const ds = d.toISOString().substring(0,10);
        const prices = ALL_DATA[ds];
        return prices && prices[code] != null ? prices[code] : null;
      }});
      const unit = VARIETY_UNITS[code] || DEFAULT_UNIT;
      return {{
        label: VARIETY_NAMES[code] + " (" + unit + ")",
        data: points,
        borderColor: COLORS[i % COLORS.length],
        backgroundColor: "transparent",
        tension: 0.3,
        pointRadius: 2,
        pointHoverRadius: 5,
        spanGaps: false,
      }};
    }}).filter(ds => ds.data.some(v => v !== null));
    
    if(datasets.length > 0) {{
      new Chart(document.getElementById(cid), {{
        type: "line",
        data: {{ labels, datasets }},
        options: {{
          responsive: true, maintainAspectRatio: false,
          plugins: {{ tooltip: {{ mode: "index", intersect: false }} }},
          scales: {{
            x: {{ title: {{ display: true, text: "日期" }} }},
            y: {{ title: {{ display: true, text: "价格" }}, beginAtZero: false }}
          }}
        }}
      }});
    }} else {{
      card.innerHTML += '<p class="no-data">本月暂无数据</p>';
    }}
  }});
}}

// 年度趋势图（按天）
function renderAnnualTrend(container, year) {{
  const card = document.createElement("div");
  card.className = "card";
  const cid = "chart-annual-" + Math.random().toString(36).substr(2,6);
  card.innerHTML = `<h3>📊 年度趋势图 (${{year}}年)</h3><div class="chart-wrap annual"><canvas id="${{cid}}"></canvas></div>`;
  container.appendChild(card);
  
  // 获取该年所有有数据的日期
  const allDates = Object.keys(ALL_DATA)
    .filter(d => d.startsWith(String(year)) && Object.values(ALL_DATA[d]).some(v => v !== null))
    .sort();
  if(allDates.length === 0) {{ card.innerHTML += '<p class="no-data">暂无年度数据</p>'; return; }}
  
  const labels = allDates.map(d => d.substring(5)); // "MM-DD"
  
  const allCodes = CATEGORIES.flatMap(c => c.codes);
  const datasets = allCodes.map((code, i) => {{
    const points = allDates.map(d => {{
      const prices = ALL_DATA[d];
      return prices && prices[code] != null ? prices[code] : null;
    }});
    const unit = VARIETY_UNITS[code] || DEFAULT_UNIT;
    return {{
      label: VARIETY_NAMES[code]+"("+unit+")",
      data: points,
      borderColor: COLORS[i % COLORS.length],
      backgroundColor: "transparent",
      tension: 0.1, pointRadius: 0,
      spanGaps: false
    }};
  }}).filter(ds => ds.data.some(v => v !== null));
  
  if(datasets.length > 0) {{
    new Chart(document.getElementById(cid), {{
      type: "line",
      data: {{ labels, datasets }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ tooltip: {{ mode: "index", intersect: false }} }},
        scales: {{
          x: {{ 
            title: {{ display: true, text: "日期" }},
            ticks: {{
              maxTicksLimit: 14,
              autoSkip: true
            }}
          }},
          y: {{ title: {{ display: true, text: "价格" }}, beginAtZero: false }}
        }}
      }}
    }});
  }}
}}

// 月度横拉表
function renderTable(year, month) {{
  const container = document.getElementById("tableContainer");
  const prefix = `${{year}}-${{String(month).padStart(2,"0")}}`;
  const days = getMonthDays(year, month);
  const allCodes = CATEGORIES.flatMap(c => c.codes);
  
  // 收集该月有数据的日期
  const activeDays = days.filter(d => {{
    const ds = d.toISOString().substring(0,10);
    return ALL_DATA[ds] && Object.values(ALL_DATA[ds]).some(v => v !== null);
  }});
  
  if(activeDays.length === 0) {{
    container.innerHTML = '<p class="no-data" style="padding:20px">该月份暂无数据</p>';
    return;
  }}
  
  let html = '<table><thead><tr><th class="sticky-col">品种</th>';
  activeDays.forEach(d => html += `<th>${{d.getMonth()+1}}/${{d.getDate()}}</th>`);
  html += '<th class="avg-col">月均价</th></tr></thead><tbody>';
  
  CATEGORIES.forEach(cat => {{
    // 分类行
    html += `<tr class="cat-row"><td colspan="${{activeDays.length+2}}">${{cat.name}}</td></tr>`;
    cat.codes.forEach(code => {{
      html += `<tr><td class="sticky-col">${{VARIETY_NAMES[code]}}<span class="unit-tag">${{VARIETY_UNITS[code] || DEFAULT_UNIT}}</span></td>`;
      let sum=0, cnt=0;
      activeDays.forEach(d => {{
        const ds = d.toISOString().substring(0,10);
        const v = ALL_DATA[ds] && ALL_DATA[ds][code] != null ? ALL_DATA[ds][code] : null;
        if(v != null) {{ sum += v; cnt++; html += `<td>${{Number.isInteger(v) ? v : v.toFixed(2)}}</td>`; }}
        else html += '<td class="no-data">—</td>';
      }});
      const avg = cnt > 0 ? Math.round(sum/cnt) : null;
      html += `<td class="avg-col">${{avg != null ? (Number.isInteger(avg) ? avg : avg.toFixed(2)) : "—"}}</td></tr>`;
    }});
  }});
  
  html += '</tbody></table>';
  container.innerHTML = html;
}}

// ===== HELPERS =====
function getMonthDays(year, month) {{
  const days = [];
  const d = new Date(year, month-1, 1);
  while(d.getMonth() === month-1) {{ days.push(new Date(d)); d.setDate(d.getDate()+1); }}
  return days;
}}

function destroyCharts() {{
  // Chart.js 实例存在全局 registry
  Object.values(Chart.instances || {{}}).forEach(c => c.destroy());
}}

// ===== INIT =====
document.addEventListener("DOMContentLoaded", () => {{
  initSelectors();
  const sel = getSelected();
  renderAll(sel.year, sel.month);
}});
</script>
</body>
</html>'''
    return html


# ============== 主流程 ==============
async def main():
    html_only = "--html-only" in sys.argv
    conn = init_db()
    today_str = datetime.now().strftime("%Y-%m-%d")

    if not html_only:
        print("=" * 50)
        print(f"📊 采集 {today_str} 价格数据 ...")

        # 并行采集（ccmn + smm 是 async）
        print("  ① ccmn 公开接口 ... ", end="", flush=True)
        ccmn = await fetch_ccmn()
        print(f"{len(ccmn)} 品种")

        print("  ② SMM 自动登录 ... ", end="", flush=True)
        smm = {}
        try:
            smm = await fetch_smm()
            print(f"{len(smm)} 品种")
        except Exception as e:
            print(f"失败: {e}")

        print("  ③ akshare WTI ... ", end="", flush=True)
        wti = fetch_wti()
        print(f"{wti}")

        print("  ④ 中钨在线钨粉 ... ", end="", flush=True)
        w = fetch_tungsten()
        print(f"{w}")

        all_prices = {**ccmn, **smm}
        if wti: all_prices["WTI"] = wti
        if w:   all_prices["W"] = w

        save_today(conn, all_prices)
        print(f"  ✅ 保存 {len(all_prices)} 个品种到 SQLite")

    # 读全部数据生成 HTML
    all_data = load_prices(conn)
    conn.close()

    if not all_data:
        print("❌ 数据库中无价格数据，请先运行 import_excel.py")
        return

    html = build_html(all_data, today_str)
    HTML_OUT.parent.mkdir(parents=True, exist_ok=True)
    HTML_OUT.write_text(html, encoding="utf-8")
    print(f"  ✅ HTML 已生成: {HTML_OUT} ({len(html)} 字节)")
    print(f"  📎 访问: https://lekelin2046.github.io/jinggong-commodity-monitor/")


if __name__ == "__main__":
    asyncio.run(main())
