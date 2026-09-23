#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把看板「单品日趋势」改造为「多指标价格曲线对比」（复刻隆众形态）。

改动点（每处都断言命中次数，避免静默漏改）：
  1. CSS   新增 .mt-* 样式
  2. HTML  替换 #singleTrendCard 卡片
  3. JS    状态变量 singleTrendRange → trendAgg / trendStart / trendEnd
  4. JS    重写 renderSingleTrend + 新增聚合/区间/下载，替换 setSingleTrendRange
  5. JS    initNewDropdowns 中单品下拉 → 多选下拉 msTrend
用法：python3 patch_multi_trend.py docs/rubber/index.html docs/plastic/index.html
"""
import io
import re
import sys

CSS_NEW = """
/* ===== 多指标价格曲线对比（复刻隆众「多指标价格曲线对比」形态）===== */
.mt-head{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:10px}
.mt-title{font-size:15px;font-weight:700;color:#0f172a;display:flex;align-items:center;gap:8px;margin:0}
.mt-bar{width:4px;height:16px;border-radius:2px;background:#dc2626}
.mt-head-right{margin-left:auto;display:flex;align-items:center;gap:10px}
.mt-spanwrap{font-size:12px;color:#475569;display:inline-flex;align-items:center;gap:5px;cursor:pointer;user-select:none}
.mt-dl{appearance:none;border:0;background:#dc2626;color:#fff;font-size:12px;font-weight:600;padding:6px 12px;border-radius:6px;cursor:pointer}
.mt-dl:hover{background:#b91c1c}
.mt-tabs{display:flex;border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;width:fit-content;margin-bottom:12px;flex-wrap:wrap}
.mt-tab{appearance:none;border:0;background:#fff;padding:7px 16px;font-size:13px;cursor:pointer;color:#475569;border-right:1px solid #e2e8f0}
.mt-tab:last-child{border-right:0}
.mt-tab:hover{background:#f8fafc}
.mt-tab.active{background:#dc2626;color:#fff;font-weight:600}
#mtQuickRange .seg-btn.active{background:#dc2626}
.mt-foot{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:12px;padding-top:10px;border-top:1px solid #f1f5f9}
.mt-foot-label{font-size:12px;color:#64748b;font-weight:600}
.mt-date{padding:5px 8px;border:1px solid #cbd5e1;border-radius:6px;font-size:12px;color:#334155;background:#fff}
.mt-tilde{font-size:12px;color:#94a3b8}
.mt-apply{appearance:none;border:1px solid #dc2626;background:#fff;color:#dc2626;font-size:12px;font-weight:600;padding:5px 14px;border-radius:6px;cursor:pointer}
.mt-apply:hover{background:#fef2f2}
"""

HTML_NEW = """  <div class="card" id="singleTrendCard">
    <div class="mt-head">
      <h3 class="mt-title"><span class="mt-bar"></span>多指标价格曲线对比</h3>
      <div class="mt-head-right">
        <label class="mt-spanwrap"><input type="checkbox" id="mtSpanGaps" onchange="renderSingleTrend()">消除曲线断点</label>
        <button type="button" class="mt-dl" onclick="downloadTrendChart()">&#11015; 曲线下载</button>
      </div>
    </div>

    <div class="mt-tabs" id="mtTabs">
      <button type="button" class="mt-tab active" data-agg="day" onclick="setTrendAgg('day')">日价格</button>
      <button type="button" class="mt-tab" data-agg="week" onclick="setTrendAgg('week')">周价格</button>
      <button type="button" class="mt-tab" data-agg="month" onclick="setTrendAgg('month')">月价格</button>
      <button type="button" class="mt-tab" data-agg="quarter" onclick="setTrendAgg('quarter')">季价格</button>
      <button type="button" class="mt-tab" data-agg="half" onclick="setTrendAgg('half')">半年价格</button>
      <button type="button" class="mt-tab" data-agg="year" onclick="setTrendAgg('year')">年价格</button>
    </div>

    <div class="trend-controls">
      <div class="ms" id="msTrendWrap">
        <button class="ms-trigger" type="button" onclick="toggleMs('msTrend')"><span id="msTrendLabel">选择指标（可多选）</span><span class="ms-caret">&#9662;</span></button>
        <div class="ms-panel" id="msTrend" style="display:none">
          <input class="ms-search" placeholder="搜索品种" oninput="filterMs('msTrend', this.value)">
          <div class="ms-list" id="msTrendList"></div>
          <div class="ms-foot"><button type="button" onclick="msAll('msTrend')">全选</button><button type="button" onclick="msClear('msTrend')">清空</button></div>
        </div>
      </div>
      <span id="singleTrendMeta" class="trend-meta"></span>
    </div>

    <div class="chart-wrap" style="height:340px"><canvas id="singleTrendChart"></canvas></div>

    <div class="mt-foot">
      <span class="mt-foot-label">日期范围：</span>
      <div class="seg" id="mtQuickRange">
        <button type="button" class="seg-btn" data-months="1" onclick="setTrendQuickRange(1)">1月</button>
        <button type="button" class="seg-btn" data-months="3" onclick="setTrendQuickRange(3)">3月</button>
        <button type="button" class="seg-btn" data-months="6" onclick="setTrendQuickRange(6)">6月</button>
        <button type="button" class="seg-btn active" data-months="12" onclick="setTrendQuickRange(12)">1年</button>
      </div>
      <input type="date" id="mtStart" class="mt-date">
      <span class="mt-tilde">至</span>
      <input type="date" id="mtEnd" class="mt-date">
      <button type="button" class="mt-apply" onclick="applyTrendRange()">确定</button>
    </div>
  </div>
"""

JS_STATE_NEW = """let trendAgg = "day";
let trendStart = null;
let trendEnd = null;
const TREND_AGG_LABEL = { day: "日", week: "周", month: "月", quarter: "季", half: "半年", year: "年" };
"""

JS_BLOCK_NEW = """// ===== 多指标价格曲线对比（多选指标 + 日/周/月/季/半年/年 聚合 + 自定义区间）=====
function allTrendCodes() { return CATEGORIES.flatMap(c => c.codes); }
function allDataDates() { return Object.keys(ALL_DATA).sort(); }

function initTrendRange() {
  const ds = allDataDates();
  if (!ds.length) return;
  const last = ds[ds.length - 1];
  trendEnd = last;
  const d = new Date(last + "T00:00:00");
  d.setFullYear(d.getFullYear() - 1);
  const s = formatDateLocal(d);
  trendStart = ds.find(x => x >= s) || ds[0];
}

function syncTrendInputs() {
  const a = document.getElementById("mtStart"), b = document.getElementById("mtEnd");
  if (a) a.value = trendStart || "";
  if (b) b.value = trendEnd || "";
}

function setTrendAgg(agg) {
  trendAgg = agg;
  document.querySelectorAll("#mtTabs .mt-tab").forEach(b => b.classList.toggle("active", b.dataset.agg === agg));
  renderSingleTrend();
}

function setTrendQuickRange(months) {
  const ds = allDataDates();
  if (!ds.length) return;
  const last = ds[ds.length - 1];
  const d = new Date(last + "T00:00:00");
  d.setMonth(d.getMonth() - months);
  const s = formatDateLocal(d);
  trendStart = ds.find(x => x >= s) || ds[0];
  trendEnd = last;
  document.querySelectorAll("#mtQuickRange .seg-btn").forEach(b => {
    b.classList.toggle("active", String(b.dataset.months) === String(months));
  });
  syncTrendInputs();
  renderSingleTrend();
}

function applyTrendRange() {
  const a = document.getElementById("mtStart"), b = document.getElementById("mtEnd");
  if (a && a.value) trendStart = a.value;
  if (b && b.value) trendEnd = b.value;
  if (trendStart && trendEnd && trendStart > trendEnd) {
    const t = trendStart; trendStart = trendEnd; trendEnd = t;
  }
  document.querySelectorAll("#mtQuickRange .seg-btn").forEach(b => b.classList.remove("active"));
  syncTrendInputs();
  renderSingleTrend();
}

// 日期 → 聚合桶键与标签
function trendBucket(dateStr) {
  const p = dateStr.split("-"), y = +p[0], m = +p[1], dd = +p[2];
  if (trendAgg === "day") return { k: dateStr, label: m + "/" + dd };
  const dt = new Date(Date.UTC(y, m - 1, dd));
  if (trendAgg === "week") {
    const dow = (dt.getUTCDay() + 6) % 7;            // 周一为 0
    dt.setUTCDate(dt.getUTCDate() - dow);
    return { k: dt.toISOString().slice(0, 10), label: (dt.getUTCMonth() + 1) + "/" + dt.getUTCDate() };
  }
  if (trendAgg === "month") return { k: y + "-" + String(m).padStart(2, "0"), label: String(y).slice(2) + "/" + m };
  if (trendAgg === "quarter") { const q = Math.floor((m - 1) / 3) + 1; return { k: y + "-Q" + q, label: String(y).slice(2) + "/Q" + q }; }
  if (trendAgg === "half") { const h = m <= 6 ? 1 : 2; return { k: y + "-H" + h, label: String(y).slice(2) + "/H" + h }; }
  return { k: String(y), label: y + "年" };
}

// 多指标价格曲线对比：所选指标各一条线，按聚合口径取区间均价
function renderSingleTrend() {
  const canvas = document.getElementById("singleTrendChart");
  if (!canvas) return;
  const metaEl = document.getElementById("singleTrendMeta");
  if (!trendStart || !trendEnd) initTrendRange();
  syncTrendInputs();

  const codes = Array.from(MS_STATE.msTrend || []);
  const spanGaps = !!(document.getElementById("mtSpanGaps") || {}).checked;

  const ds = allDataDates().filter(k => (!trendStart || k >= trendStart) && (!trendEnd || k <= trendEnd));
  const order = [], buckets = new Map();
  ds.forEach(k => {
    const b = trendBucket(k);
    if (!buckets.has(b.k)) { buckets.set(b.k, { label: b.label, sum: {}, n: {} }); order.push(b.k); }
    const bk = buckets.get(b.k);
    codes.forEach(c => {
      const v = ALL_DATA[k] ? ALL_DATA[k][c] : null;
      if (v != null && v !== "") { bk.sum[c] = (bk.sum[c] || 0) + Number(v); bk.n[c] = (bk.n[c] || 0) + 1; }
    });
  });

  const labels = order.map(k => buckets.get(k).label);
  const datasets = codes.map(c => {
    const color = COLORS[allTrendCodes().indexOf(c) % COLORS.length];
    const data = order.map(k => {
      const b = buckets.get(k);
      return b.n[c] ? +(b.sum[c] / b.n[c]).toFixed(2) : null;
    });
    return {
      label: VARIETY_NAMES[c] + " (" + (VARIETY_UNITS[c] || DEFAULT_UNIT) + ")",
      data: data, borderColor: color, backgroundColor: color + "14", fill: false,
      tension: 0.25, borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, spanGaps: spanGaps
    };
  });

  // 元信息
  if (metaEl) {
    if (!codes.length) {
      metaEl.textContent = "请至少选择一个指标";
    } else if (!labels.length) {
      metaEl.textContent = "该区间暂无数据";
    } else {
      let html = "已选 <b>" + codes.length + "</b> 项 · " + (TREND_AGG_LABEL[trendAgg] || "") +
                 "度 <b>" + labels.length + "</b> 点 · " + trendStart + " ~ " + trendEnd;
      if (codes.length === 1) {
        const c = codes[0], arr = datasets[0].data.filter(v => v !== null);
        if (arr.length) {
          const first = arr[0], last = arr[arr.length - 1];
          const chg = first ? (last - first) / first * 100 : 0;
          const cls = chg >= 0 ? "#dc2626" : "#16a34a", arrow = chg >= 0 ? "▲" : "▼";
          html += " · 最新 <b>" + Math.round(last).toLocaleString() + "</b> " + (VARIETY_UNITS[c] || DEFAULT_UNIT) +
                  " · 区间 <span style=\\"color:" + cls + "\\">" + arrow + Math.abs(chg).toFixed(1) + "%</span>";
        }
      }
      metaEl.innerHTML = html;
    }
  }

  if (window._singleTrendChart) window._singleTrendChart.destroy();
  const units = codes.map(c => VARIETY_UNITS[c] || DEFAULT_UNIT);
  const unit = units.length && units.every(u => u === units[0]) ? units[0] : DEFAULT_UNIT;
  window._singleTrendChart = new Chart(canvas, {
    type: "line",
    data: { labels: labels, datasets: datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "top", labels: { boxWidth: 18, boxHeight: 2, padding: 12, font: { size: 11 } } },
        tooltip: { mode: "index", intersect: false }
      },
      scales: {
        x: { title: { display: true, text: "日期" }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
        y: { title: { display: true, text: "价格 (" + unit + ")" }, beginAtZero: false }
      }
    }
  });
}

// 曲线下载（白底 PNG，避免透明背景）
function downloadTrendChart() {
  const src = document.getElementById("singleTrendChart");
  if (!src) return;
  const tmp = document.createElement("canvas");
  tmp.width = src.width; tmp.height = src.height;
  const ctx = tmp.getContext("2d");
  ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, tmp.width, tmp.height);
  ctx.drawImage(src, 0, 0);
  const a = document.createElement("a");
  a.download = "多指标价格曲线_" + (TREND_AGG_LABEL[trendAgg] || "") + "价格_" +
               (trendStart || "") + "_" + (trendEnd || "") + ".png";
  a.href = tmp.toDataURL("image/png");
  a.click();
}

// 从明细表点品种名联动：把该指标设为唯一选中项
function selectSingleTrend(code) {
  // 注意：MS_STATE 是顶层 const，不会挂到 window 上，必须用 typeof 判断
  if (typeof MS_STATE !== "undefined" && MS_STATE.msTrend) {
    MS_STATE.msTrend = new Set([code]);
    renderMsList("msTrend", "msTrendList");
    updateMsLabel("msTrend");
  }
  renderSingleTrend();
  const card = document.getElementById("singleTrendCard");
  if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
}
"""

JS_INIT_NEW = """  // 多指标价格曲线对比：默认选中天然橡胶 SCRWF/RSS3（与隆众参考图一致）
  const trendDefault = ["NR_SCRWF", "NR_RSS3"].filter(c => allCodes.indexOf(c) >= 0);
  setupMultiSelect("msTrend", "msTrendList",
    trendDefault.length ? trendDefault : allCodes.slice(0, 2),
    () => renderSingleTrend());
"""


def patch(path):
    with io.open(path, encoding="utf-8") as f:
        src = f.read()
    orig = src
    checks = []

    # --- 1. CSS ---
    anchor = '.trend-meta{font-size:12px;color:#64748b}'
    assert src.count(anchor) == 1, f"{path}: CSS 锚点命中 {src.count(anchor)} 次"
    src = src.replace(anchor, anchor + "\n" + CSS_NEW, 1)
    checks.append("CSS")

    # --- 2. HTML 卡片 ---
    m = re.search(r'  <div class="card" id="singleTrendCard"[\s\S]*?\n  </div>\n(?=</div>)', src)
    assert m, f"{path}: 未定位到 singleTrendCard 卡片"
    src = src[:m.start()] + HTML_NEW + src[m.end():]
    checks.append("HTML卡片")

    # --- 3. 状态变量 ---
    old_state = 'let singleTrendRange = "month";'
    assert src.count(old_state) == 1, f"{path}: 状态变量命中 {src.count(old_state)} 次"
    src = src.replace(old_state, JS_STATE_NEW.rstrip("\n"), 1)
    checks.append("状态变量")

    # --- 4. renderSingleTrend 区块 ---
    start_marker = "// 单品日趋势图：选一个品种，只画它自己一条线"
    end_marker = '  if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });\n}\n'
    i = src.index(start_marker)
    j = src.index(end_marker, i) + len(end_marker)
    src = src[:i] + JS_BLOCK_NEW + src[j:]
    checks.append("趋势图逻辑")

    # --- 5. initNewDropdowns 单品下拉 → 多选 ---
    st = src.index("  // 单品日趋势下拉框")
    en = src.index("    stSel.value = allCodes[0];\n  }\n", st) + len("    stSel.value = allCodes[0];\n  }\n")
    src = src[:st] + JS_INIT_NEW + src[en:]
    checks.append("初始化")

    # 残留检查
    for bad in ["singleTrendRange", "singleTrendVariety", "setSingleTrendRange"]:
        assert bad not in src, f"{path}: 仍残留旧标识 {bad}"
    checks.append("无旧标识残留")

    with io.open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"✓ {path}  改动 {', '.join(checks)}  | {len(orig)} → {len(src)} 字符")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        patch(p)
