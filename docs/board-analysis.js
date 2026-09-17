/* ==========================================================================
   诺博板块 · 分组分析模块（周报形态）
   --------------------------------------------------------------------------
   形态复刻自《诺博橡胶大宗物料价格走势-2026.xlsx》
   工作表「原材料价格走势-周报」。

   原表结构：按分组循环 ——【折线走势图】→【统计表】→【总结文字】
   统计表：行 = 指标，列 = 品种
   指标行：周均价 / 月均价 / 年度均价 / 较上周涨幅 / 较上月涨幅 / 较XX年均价涨幅

   ⚠ 口径已修正原表缺陷（不照搬 bug）：
     ① 原表「周均价」窗口内常只有 2 个交易日有值（=2日均价）；
        此处严格取最近 5 个有值交易日，不足 5 天不计算。
     ② 原表「月均价」部分板块实为 10 日均价；此处取所在自然月全部有值日。
     ③ 原表各板块数据截止日不一致（铝/三元乙丙/炭黑=8/18，天然胶/助剂=6/12）；
        此处统一按各品种自身最新有值日锚定，并在覆盖说明中逐条标注。
     ④ 原表涨幅单元格为纯 0.00%、负值不变色；此处按中国习惯红涨绿跌。
     ⑤ 涨幅一律 (本期 − 基期) / 基期，2 位小数。

   铁律：抓不到就留空（显示 “-”），绝不推算、不沿用前值。

   CSV 导出：每组卡右上「导出CSV」= 单组；「分组分析 · 统计口径」卡右上 = 全部。
             导出内容取自屏幕表格的同一份快照（exportStore），不重算。
             文件名前缀由调用方 `fileBase` 决定。

   依赖：Chart.js（页面已通过 vendor 引入）
   ========================================================================== */
(function (global) {
  "use strict";

  var WEEK_N = 5;              // 「周」= 最近 5 个有值交易日
  var FLAT_EPS = 0.005;        // 涨跌平判定阈值（百分点）
  var DEFAULT_RANGE = "6m";
  var RANGES = [
    { key: "1m",  label: "近1月", days: 30 },
    { key: "3m",  label: "近3月", days: 90 },
    { key: "6m",  label: "近6月", days: 180 },
    { key: "1y",  label: "近1年", days: 365 },
    { key: "all", label: "全部", days: 100000 }
  ];

  var state = {};    // { 分组名: rangeKey }
  var charts = {};   // { 分组名: Chart 实例 }
  var ctxRef = null;    // 最近一次 render 的上下文
  var exportStore = []; // 每组导出快照：与屏幕表格同源取值，杜绝口径漂移

  /* ------------------------------------------------------------------ 工具 */
  function uniq(arr) {
    var seen = {}, out = [];
    for (var i = 0; i < arr.length; i++) {
      if (!seen[arr[i]]) { seen[arr[i]] = 1; out.push(arr[i]); }
    }
    return out;
  }
  function avgOf(list) {
    if (!list || !list.length) return null;
    var s = 0;
    for (var i = 0; i < list.length; i++) s += list[i].v;
    return s / list.length;
  }
  function pctOf(cur, base) {
    if (cur == null || base == null || base === 0 || !isFinite(cur) || !isFinite(base)) return null;
    return (cur - base) / base * 100;
  }
  function pad2(n) { return n < 10 ? "0" + n : "" + n; }
  function fmtPrice(v) {
    if (v == null || !isFinite(v)) return "-";
    return v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function fmtPct(v) {
    if (v == null || !isFinite(v)) return "-";
    return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
  }
  function pctCls(v) {
    if (v == null || !isFinite(v)) return "ba-flat";
    return v > FLAT_EPS ? "ba-up" : (v < -FLAT_EPS ? "ba-down" : "ba-flat");
  }
  function shortDate(d) {
    var p = d.split("-");
    return parseInt(p[1], 10) + "/" + parseInt(p[2], 10);
  }
  function shiftDays(ds, n) {
    var p = ds.split("-");
    var dt = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]));
    dt.setUTCDate(dt.getUTCDate() + n);
    return dt.getUTCFullYear() + "-" + pad2(dt.getUTCMonth() + 1) + "-" + pad2(dt.getUTCDate());
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  /* ------------------------------------------------------------ 数据提取 */
  function seriesOf(data, dates, code) {
    var out = [];
    for (var i = 0; i < dates.length; i++) {
      var row = data[dates[i]];
      var v = row ? row[code] : null;
      if (v === null || v === undefined || v === "" || isNaN(v) || !isFinite(v)) continue;
      out.push({ d: dates[i], v: +v });
    }
    return out;
  }

  /* ------------------------------------------------------------ 指标计算 */
  function computeStats(series) {
    var n = series.length;
    if (!n) return { n: 0 };
    var anchor = series[n - 1].d;
    var anchorYear = anchor.substring(0, 4);
    var anchorMonth = anchor.substring(0, 7);

    // 本周 / 上周（严格 5 个有值交易日窗口）
    var week = n >= WEEK_N ? avgOf(series.slice(n - WEEK_N)) : null;
    var prevWeek = n >= WEEK_N * 2 ? avgOf(series.slice(n - WEEK_N * 2, n - WEEK_N)) : null;

    // 本月 / 上月（自然月内全部有值日）
    var months = uniq(series.map(function (x) { return x.d.substring(0, 7); })).sort();
    var mi = months.indexOf(anchorMonth);
    var prevMonthKey = mi > 0 ? months[mi - 1] : null;
    var monthPts = series.filter(function (x) { return x.d.substring(0, 7) === anchorMonth; });
    var monthAvg = avgOf(monthPts);
    var prevMonthPts = prevMonthKey
      ? series.filter(function (x) { return x.d.substring(0, 7) === prevMonthKey; })
      : [];
    var prevMonthAvg = avgOf(prevMonthPts);

    // 年度均价（年初 → 最新有值日）
    var ytdPts = series.filter(function (x) { return x.d.substring(0, 4) === anchorYear; });
    var ytdAvg = avgOf(ytdPts);

    // 各历史年度均价（除锚定年）
    var years = uniq(series.map(function (x) { return x.d.substring(0, 4); })).sort();
    var yearRows = [];
    for (var i = years.length - 1; i >= 0; i--) {
      var y = years[i];
      if (y === anchorYear) continue;
      var pts = series.filter(function (x) { return x.d.substring(0, 4) === y; });
      if (!pts.length) continue;
      yearRows.push({
        year: y, avg: avgOf(pts), n: pts.length,
        first: pts[0].d, last: pts[pts.length - 1].d
      });
    }

    return {
      n: n, anchor: anchor, first: series[0].d, anchorYear: anchorYear,
      week: week, prevWeek: prevWeek,
      monthAvg: monthAvg, prevMonthKey: prevMonthKey,
      prevMonthAvg: prevMonthAvg, monthN: monthPts.length, prevMonthN: prevMonthPts.length,
      ytdAvg: ytdAvg, ytdN: ytdPts.length,
      yearRows: yearRows,
      chgWeek: pctOf(week, prevWeek),
      chgMonth: pctOf(monthAvg, prevMonthAvg)
    };
  }

  /* ---------------------------------------------------------------- 样式 */
  function ensureStyle() {
    if (document.getElementById("boardAnalysisStyle")) return;
    var st = document.createElement("style");
    st.id = "boardAnalysisStyle";
    st.textContent = [
      ".ba-card{background:#fff;border-radius:10px;padding:14px 16px;box-shadow:0 1px 3px rgba(0,0,0,.06);margin-bottom:14px;border-left:3px solid #0f766e}",
      ".ba-intro{border-left-color:#64748b}",
      ".ba-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}",
      ".ba-head h3{font-size:14px;font-weight:600;color:#334155;margin:0}",
      ".ba-unit{font-size:11px;color:#94a3b8}",
      ".ba-seg{margin-left:auto;display:inline-flex;border:1px solid #cbd5e1;border-radius:6px;overflow:hidden}",
      ".ba-seg button{appearance:none;border:0;background:#fff;padding:4px 10px;font-size:12px;color:#475569;cursor:pointer;border-right:1px solid #e2e8f0}",
      ".ba-seg button:last-child{border-right:0}",
      ".ba-seg button.active{background:#0f766e;color:#fff;font-weight:600}",
      ".ba-chart{position:relative;height:260px}",
      ".ba-chart-cap{font-size:11px;color:#94a3b8;margin-top:4px}",
      ".ba-table-wrap{overflow-x:auto;margin-top:10px}",
      "table.ba-table{border-collapse:collapse;font-size:12px;width:100%}",
      ".ba-table th,.ba-table td{border:1px solid #e2e8f0;padding:5px 8px;text-align:right;white-space:nowrap}",
      ".ba-table thead th{background:#f8fafc;font-weight:600}",
      ".ba-table th:first-child,.ba-table td:first-child{text-align:left;min-width:168px}",
      ".ba-table thead th .ba-code-sub{display:block;font-size:10px;font-weight:400;color:#94a3b8;margin-top:1px}",
      ".ba-table tbody td:first-child{color:#475569}",
      ".ba-table tbody td:first-child .ba-sub{display:block;font-size:10px;color:#94a3b8;font-weight:400;margin-top:1px}",
      ".ba-table tbody tr.ba-emph td{background:#fff7e0}",
      ".ba-table tbody tr.ba-emph td:first-child{font-weight:600;color:#334155}",
      ".ba-table tbody tr.ba-base td{color:#94a3b8}",
      ".ba-up{color:#dc2626;font-weight:600}",
      ".ba-down{color:#16a34a;font-weight:600}",
      ".ba-flat{color:#94a3b8}",
      ".ba-note{font-size:11px;color:#94a3b8;margin-top:8px;line-height:1.7}",
      ".ba-sum{font-size:12px;color:#334155;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:8px 10px;margin-top:10px;line-height:1.8}",
      ".ba-sum .ba-sum-title{font-weight:600;color:#0f766e}",
      ".ba-sum .ba-dim{color:#94a3b8}",
      ".ba-empty{padding:18px;color:#94a3b8;font-size:12px}",
      ".ba-btn{appearance:none;border:1px solid #cbd5e1;background:#fff;color:#475569;font-size:11px;line-height:1;padding:5px 10px;border-radius:6px;cursor:pointer;white-space:nowrap}",
      ".ba-btn:hover{border-color:#0f766e;color:#0f766e;background:#f0fdfa}",
      ".ba-export-all{margin-left:auto}",
      "@media print{.ba-seg{display:none!important}.ba-btn{display:none!important}.ba-chart{height:180px!important}.ba-card{break-inside:avoid;page-break-inside:avoid;box-shadow:none;border:1px solid #e2e8f0}}"
    ].join("");
    document.head.appendChild(st);
  }

  /* -------------------------------------------------------------- 画图 */
  function renderChart(catName, codes, canvasEl, capEl) {
    var rk = state[catName] || DEFAULT_RANGE;
    var rdef = RANGES[0];
    for (var i = 0; i < RANGES.length; i++) { if (RANGES[i].key === rk) rdef = RANGES[i]; }

    var ctx = ctxRef;
    var anchor = ctx.dates[ctx.dates.length - 1];
    var cutoff = shiftDays(anchor, -rdef.days);
    var win = ctx.dates.filter(function (d) { return d >= cutoff; });

    // 横轴标签：跨度 ≥ 1 年时带年份，否则 M/D（否则多年数据会出现 "7/1" 这种年份歧义）
    var multiYear = false;
    if (win.length >= 2) {
      multiYear = (+win[win.length - 1].substring(0, 4) - +win[0].substring(0, 4)) >= 1;
    }
    var labels = win.map(function (d) {
      return multiYear ? d.substring(0, 4) + "/" + parseInt(d.substring(5, 7), 10) : shortDate(d);
    });
    var datasets = [];
    codes.forEach(function (code) {
      var pts = ctx.seriesMap[code] || [];
      if (!pts.length) return;
      var map = {};
      for (var i = 0; i < pts.length; i++) map[pts[i].d] = pts[i].v;
      var data = win.map(function (d) { return map[d] !== undefined ? map[d] : null; });
      var nPts = 0;
      for (var j = 0; j < data.length; j++) { if (data[j] !== null) nPts++; }
      if (!nPts) return;
      var color = ctx.colors[ctx.allCodes.indexOf(code) % ctx.colors.length];
      datasets.push({
        label: ctx.names[code] || code,
        data: data,
        borderColor: color,
        backgroundColor: "transparent",
        borderWidth: 1.8,
        tension: 0.25,
        // 数据点极少的品种放大点径，否则单点会看不见
        pointRadius: nPts <= 3 ? 4 : (win.length > 130 ? 0 : 2),
        pointHoverRadius: 5,
        spanGaps: false
      });
    });

    if (charts[catName]) {
      try { charts[catName].destroy(); } catch (e) { /* 已被 destroyCharts 清掉 */ }
      charts[catName] = null;
    }

    var old = canvasEl.parentNode.querySelector(".ba-chart-empty");
    if (old) old.parentNode.removeChild(old);

    if (!datasets.length) {
      if (capEl) capEl.textContent = "该区间暂无数据";
      return;
    }

    charts[catName] = new global.Chart(canvasEl, {
      type: "line",
      data: { labels: labels, datasets: datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 10 } } },
          tooltip: {
            callbacks: {
              title: function (items) {
                if (!items || !items.length) return "";
                return win[items[0].dataIndex];
              }
            }
          }
        },
        scales: {
          x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
          y: { beginAtZero: false, title: { display: true, text: "价格 (" + (ctx.units[codes[0]] || ctx.defaultUnit) + ")" } }
        }
      }
    });

    if (capEl) {
      var firstD = null, lastD = null, nData = 0;
      for (var k = 0; k < win.length; k++) {
        var has = datasets.some(function (ds) { return ds.data[k] !== null; });
        if (has) { if (!firstD) firstD = win[k]; lastD = win[k]; nData++; }
      }
      capEl.textContent = firstD
        ? "显示区间 " + firstD + " ~ " + lastD + "（其中 " + nData + " 个交易日有数据）"
        : "";
    }
  }

  /* ------------------------------------------------------------ 自动摘要 */
  function buildSummary(codes, statsMap, ctx) {
    function pick(getter) {
      var list = [];
      codes.forEach(function (c) {
        var st = statsMap[c];
        var v = st ? getter(st) : null;
        if (v == null || !isFinite(v)) return;
        list.push({ name: ctx.names[c] || c, v: v });
      });
      if (!list.length) return null;
      var up = 0, down = 0, flat = 0;
      list.forEach(function (x) {
        if (x.v > FLAT_EPS) up++; else if (x.v < -FLAT_EPS) down++; else flat++;
      });
      var sorted = list.slice().sort(function (a, b) { return b.v - a.v; });
      return { n: list.length, up: up, down: down, flat: flat, max: sorted[0], min: sorted[sorted.length - 1] };
    }

    function line(title, agg) {
      if (!agg) return "<div>" + title + "：<span class=\"ba-dim\">数据不足，无法计算</span></div>";
      var head = title + "：可算 " + agg.n + " 个品种，" +
        agg.up + " 涨 / " + agg.down + " 跌 / " + agg.flat + " 平";
      var tail;
      if (agg.up === 0 && agg.down === 0) {
        tail = "；<span class=\"ba-dim\">全部持平（|涨幅| ≤ " + FLAT_EPS + "%）</span>";
      } else if (agg.n === 1) {
        tail = "；<span class=\"" + pctCls(agg.max.v) + "\">" + esc(agg.max.name) + " " + fmtPct(agg.max.v) + "</span>";
      } else if (agg.up === 0) {
        tail = "；全部下跌，跌幅最大 <span class=\"" + pctCls(agg.min.v) + "\">" + esc(agg.min.name) + " " + fmtPct(agg.min.v) + "</span>";
      } else if (agg.down === 0) {
        tail = "；全部上涨，涨幅最大 <span class=\"" + pctCls(agg.max.v) + "\">" + esc(agg.max.name) + " " + fmtPct(agg.max.v) + "</span>";
      } else {
        tail = "；涨幅最大 <span class=\"" + pctCls(agg.max.v) + "\">" + esc(agg.max.name) + " " + fmtPct(agg.max.v) + "</span>" +
               "，跌幅最大 <span class=\"" + pctCls(agg.min.v) + "\">" + esc(agg.min.name) + " " + fmtPct(agg.min.v) + "</span>";
      }
      return "<div>" + head + tail + "</div>";
    }

    var w = pick(function (st) { return st.chgWeek; });
    var m = pick(function (st) { return st.chgMonth; });
    return "<div class=\"ba-sum\">" +
      "<span class=\"ba-sum-title\">自动摘要</span> <span class=\"ba-dim\">（由表内数值机械计算，不含人工判断）</span>" +
      line("本周较上周", w) + line("本月较上月", m) +
      "</div>";
  }

  /* ------------------------------------------------------------ 分组渲染 */
  function renderGroup(cat, ctx, idx) {
    var codes = cat.codes.slice();
    var statsMap = {};
    codes.forEach(function (c) { statsMap[c] = computeStats(ctx.seriesMap[c] || []); });

    // 该分组涉及的历史年度（取各品种并集，倒序）
    var yearSet = {};
    codes.forEach(function (c) {
      var st = statsMap[c];
      if (!st || !st.yearRows) return;
      st.yearRows.forEach(function (r) { yearSet[r.year] = 1; });
    });
    var years = Object.keys(yearSet).sort().reverse();

    var anchorGlobal = ctx.dates[ctx.dates.length - 1];
    var ytdYear = anchorGlobal.substring(0, 4);
    var unit = ctx.units[codes[0]] || ctx.defaultUnit;
    var allSameUnit = codes.every(function (c) { return (ctx.units[c] || ctx.defaultUnit) === unit; });

    var rangeKey = state[cat.name] || DEFAULT_RANGE;
    // ⚠ 画布 ID 必须用索引：分组名全为中文，做正则转义后会全部塌成 "_" 而互相撞车
    var canvasId = "baChart_" + idx;

    /* ---- 表头/表格 ---- */
    var head = "<thead><tr><th>指标</th>";
    codes.forEach(function (c) {
      var st = statsMap[c];
      var cov = (st && st.n) ? (st.n + " 天") : "无数据";
      head += "<th>" + esc(ctx.names[c] || c) +
        "<span class=\"ba-code-sub\">" + esc(ctx.units[c] || ctx.defaultUnit) + " · " + cov + "</span></th>";
    });
    head += "</tr></thead>";

    var rows = [
      { label: "本周均价", sub: "近 " + WEEK_N + " 个有值交易日", kind: "price", emph: false, base: false,
        get: function (st) { return st.week; } },
      { label: "上周均价", sub: "前 " + WEEK_N + " 个有值交易日", kind: "price", emph: false, base: true,
        get: function (st) { return st.prevWeek; } },
      { label: "较上周涨幅", sub: "本周 ÷ 上周 − 1", kind: "pct", emph: true, base: false,
        get: function (st) { return st.chgWeek; } },
      { label: "本月均价", sub: "自然月内全部有值日", kind: "price", emph: false, base: false,
        get: function (st) { return st.monthAvg; } },
      { label: "上个月均价", sub: anchorGlobal.substring(0, 7) + " 的上一个自然月", kind: "price", emph: false, base: true,
        get: function (st) { return st.prevMonthAvg; } },
      { label: "较上月涨幅", sub: "本月 ÷ 上月 − 1", kind: "pct", emph: true, base: false,
        get: function (st) { return st.chgMonth; } },
      { label: ytdYear + "年年度均价", sub: "年初至各品种最新有值日", kind: "price", emph: false, base: false,
        get: function (st) { return st.ytdAvg; } }
    ];
    years.forEach(function (y) {
      rows.push({
        label: "较" + y + "年均价涨幅", sub: "年度均价 ÷ " + y + "年均价 − 1",
        kind: "pct", emph: false, base: false, year: y,
        get: function (st) {
          if (!st || !st.yearRows) return null;
          for (var i = 0; i < st.yearRows.length; i++) {
            if (st.yearRows[i].year === y) return pctOf(st.ytdAvg, st.yearRows[i].avg);
          }
          return null;
        }
      });
    });

    var expRows = [];
    var body = "<tbody>";
    rows.forEach(function (r) {
      var vals = codes.map(function (c) {
        var st = statsMap[c];
        return st ? r.get(st) : null;
      });
      expRows.push({ label: r.label, sub: r.sub || "", kind: r.kind, vals: vals });
      body += "<tr class=\"" + (r.emph ? "ba-emph" : "") + (r.base ? " ba-base" : "") + "\">";
      body += "<td>" + esc(r.label) + (r.sub ? "<span class=\"ba-sub\">" + esc(r.sub) + "</span>" : "") + "</td>";
      codes.forEach(function (c, vi) {
        var v = vals[vi];
        if (r.kind === "price") {
          body += "<td>" + fmtPrice(v) + "</td>";
        } else {
          body += "<td class=\"" + pctCls(v) + "\">" + fmtPct(v) + "</td>";
        }
      });
      body += "</tr>";
    });
    body += "</tbody>";

    /* ---- 覆盖说明（此处保留原文，HTML 注入处统一 esc，CSV 直接复用同一份）---- */
    var covParts = codes.map(function (c) {
      var st = statsMap[c];
      if (!st || !st.n) return (ctx.names[c] || c) + " 无数据";
      return (ctx.names[c] || c) + " " + st.n + " 天（" + st.first + " ~ " + st.anchor + "）";
    });

    var caveats = ["数据覆盖：" + covParts.join("　·　")];

    // 年度对比若某品种为部分年度，逐条点名（按品种，不按分组并集，避免掩盖）
    var partialLines = [];
    years.forEach(function (y) {
      var bad = [];
      codes.forEach(function (c) {
        var st = statsMap[c];
        if (!st || !st.yearRows) return;
        for (var i = 0; i < st.yearRows.length; i++) {
          var r = st.yearRows[i];
          if (r.year !== y) continue;
          var fullStart = r.first.substring(5, 7) === "01";
          var fullEnd = r.last.substring(5, 7) === "12";
          if (!(fullStart && fullEnd)) {
            bad.push(esc(ctx.names[c] || c) + " 仅 " + r.first + " ~ " + r.last + "（" + r.n + " 天）");
          }
        }
      });
      if (bad.length) partialLines.push(y + " 年：" + bad.join("；"));
    });
    if (partialLines.length) {
      caveats.push("⚠ 以下年度均值为部分年度口径，非完整年度，年度对比仅供参考 —— " + partialLines.join("　｜　"));
    }

    var anchorSkew = {};
    codes.forEach(function (c) {
      var st = statsMap[c];
      if (st && st.n) anchorSkew[st.anchor] = (anchorSkew[st.anchor] || 0) + 1;
    });
    var anchors = Object.keys(anchorSkew).sort();
    if (anchors.length > 1) {
      caveats.push("⚠ 各品种最新有值日不同（" + anchors.join(" / ") + "），原表此处亦不一致，已按品种各自锚定，未强行对齐。");
    }

    exportStore.push({
      group: cat.name,
      codes: codes,
      names: codes.map(function (c) { return ctx.names[c] || c; }),
      units: codes.map(function (c) { return ctx.units[c] || ctx.defaultUnit; }),
      rows: expRows,
      caveats: caveats,
      anchor: anchorGlobal
    });

    return "<div class=\"ba-card\">" +
      "<div class=\"ba-head\"><h3>" + esc("📈 " + cat.name + " 分析") + "</h3>" +
      (allSameUnit ? "<span class=\"ba-unit\">" + esc(unit) + "</span>" : "") +
      "<div class=\"ba-seg\" data-cat=\"" + esc(cat.name) + "\">" +
      RANGES.map(function (r) {
        return "<button type=\"button\" class=\"" + (r.key === rangeKey ? "active" : "") +
          "\" onclick=\"BoardAnalysis.setRange(" + idx + ",'" + r.key + "')\">" + r.label + "</button>";
      }).join("") +
      "</div>" +
      "<button type=\"button\" class=\"ba-btn\" title=\"导出本组分析表（CSV，Excel 可直接打开）\"" +
      " onclick=\"BoardAnalysis.exportCSV(" + idx + ")\">导出CSV</button>" +
      "</div>" +
      "<div class=\"ba-chart\"><canvas id=\"" + canvasId + "\"></canvas></div>" +
      "<div class=\"ba-chart-cap\" id=\"" + canvasId + "_cap\"></div>" +
      "<div class=\"ba-table-wrap\"><table class=\"ba-table\">" + head + body + "</table></div>" +
      buildSummary(codes, statsMap, ctx) +
      "<div class=\"ba-note\">" + caveats.map(esc).join("<br>") + "</div>" +
      "</div>";
  }

  /* ---------------------------------------------------------------- 入口 */
  function render(opts) {
    ensureStyle();
    var container = document.getElementById(opts.containerId);
    if (!container) return;
    exportStore = [];

    var dates = Object.keys(opts.data || {}).sort();
    if (!dates.length) {
      container.innerHTML = "<div class=\"ba-card ba-intro\"><div class=\"ba-empty\">暂无数据</div></div>";
      return;
    }

    var seriesMap = {};
    var allCodes = [];
    (opts.categories || []).forEach(function (cat) {
      cat.codes.forEach(function (c) {
        if (allCodes.indexOf(c) < 0) allCodes.push(c);
        seriesMap[c] = seriesOf(opts.data, dates, c);
      });
    });

    ctxRef = {
      data: opts.data, dates: dates, categories: opts.categories,
      names: opts.names || {}, units: opts.units || {}, sources: opts.sources || {},
      markets: opts.markets || {}, colors: opts.colors || ["#2563eb"],
      defaultUnit: opts.defaultUnit || "", allCodes: allCodes, seriesMap: seriesMap,
      fileBase: opts.fileBase || "分析表", anchorDate: dates[dates.length - 1]
    };

    var docRef = opts.docRef || "客户分析文档（工作表「原材料价格走势-周报」）";

    var intro = "<div class=\"ba-card ba-intro\">" +
      "<div class=\"ba-head\"><h3>📑 分组分析 · 统计口径</h3>" +
      "<button type=\"button\" class=\"ba-btn ba-export-all\" title=\"导出全部分组分析表（CSV）\"" +
      " onclick=\"BoardAnalysis.exportCSVAll()\">导出全部分析表 CSV</button>" +
      "</div>" +
      "<div class=\"ba-note\" style=\"margin-top:0\">" +
      "形态复刻自 " + esc(docRef) + "：每个分组 = 折线走势图 + 统计表 + 摘要。" +
      "<br>① <b>本周 / 上周</b>＝最近 5 个 / 前 5 个有值交易日（严格窗口，不足 5 天不计算）；" +
      "② <b>本月 / 上月</b>＝自然月内全部有值日均值；" +
      "③ <b>年度均价</b>＝该年 1 月 1 日至各品种最新有值日；" +
      "④ <b>涨幅</b>＝(本期 − 基期) ÷ 基期，2 位小数，红涨绿跌。" +
      "<br>口径已修正参考表缺陷：原表「周均价」窗口内多数只有 2 个交易日有值（实为 2 日均价）、部分「月均价」实为 10 日均价、且各板块数据截止日不一致。本页统一按各品种自身最新有值日锚定，未强行对齐。" +
      "<br>抓不到即留空显示 <b>-</b>，不推算、不沿用前值。每组卡片右上可导出本组 CSV，「统计口径」卡右上可导出全部分组。" +
      "</div></div>";

    var body = "";
    (opts.categories || []).forEach(function (cat, idx) {
      body += renderGroup(cat, ctxRef, idx);
    });
    container.innerHTML = intro + body;

    // 图表需在 DOM 插入后再实例化
    (opts.categories || []).forEach(function (cat, idx) {
      var canvasEl = document.getElementById("baChart_" + idx);
      var capEl = document.getElementById("baChart_" + idx + "_cap");
      if (canvasEl) renderChart(cat.name, cat.codes, canvasEl, capEl);
    });
  }

  function setRange(idx, rangeKey) {
    if (!ctxRef) return;
    var cat = ctxRef.categories[idx];
    if (!cat) return;
    state[cat.name] = rangeKey;
    // 只重画该分组
    var seg = document.querySelector(".ba-seg[data-cat=\"" + cat.name.replace(/"/g, "\\\"") + "\"]");
    if (seg) {
      Array.prototype.forEach.call(seg.querySelectorAll("button"), function (b) {
        b.classList.toggle("active", b.textContent === rkLabel(rangeKey));
      });
    }
    var canvasEl = document.getElementById("baChart_" + idx);
    var capEl = document.getElementById("baChart_" + idx + "_cap");
    if (canvasEl) renderChart(cat.name, cat.codes, canvasEl, capEl);
  }
  function rkLabel(key) {
    for (var i = 0; i < RANGES.length; i++) { if (RANGES[i].key === key) return RANGES[i].label; }
    return "";
  }

  /* ---------------------------------------------------------- CSV 导出 */
  /* 导出内容与屏幕表格同源（exportStore 快照），不重算，避免口径漂移 */
  function csvCell(v) {
    var s = (v === null || v === undefined) ? "" : String(v);
    if (/[",\r\n]/.test(s)) return "\"" + s.replace(/"/g, "\"\"") + "\"";
    return s;
  }
  function num2(v) {
    if (v == null || !isFinite(v)) return "";   // 无数据留空，不写 0、不沿用前值
    return (Math.round(v * 100) / 100).toFixed(2);
  }
  function stamp() {
    var d = new Date();
    return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate()) +
      " " + pad2(d.getHours()) + ":" + pad2(d.getMinutes());
  }
  function buildCSV(items) {
    var base = (ctxRef && ctxRef.fileBase) || "分析表";
    var anchor = (ctxRef && ctxRef.anchorDate) || "";
    var L = [];
    L.push(["# " + base + " · 分组分析表"]);
    L.push(["# 生成时间：" + stamp() + " ｜ 最新数据日：" + anchor]);
    L.push(["# 口径：本周/上周＝最近/前 " + WEEK_N + " 个有值交易日（不足 " + WEEK_N + " 天不计算）；" +
      "本月/上月＝自然月内全部有值日均值；年度均价＝该年 1 月 1 日至各品种最新有值日；" +
      "涨幅＝(本期 − 基期) ÷ 基期"]);
    L.push(["# 说明：价格与涨幅均为数值（涨幅 1.23 表示 +1.23%）；空格表示无数据，未做任何估算或沿用"]);
    items.forEach(function (g) {
      L.push([]);
      L.push(["# 分组：" + g.group]);
      var head = ["指标", "口径", "类型"];
      g.codes.forEach(function (c, i) { head.push(g.names[i] + "（" + g.units[i] + "）"); });
      L.push(head);
      g.rows.forEach(function (r) {
        var line = [r.label, r.sub, r.kind === "price" ? "价格" : "涨幅%"];
        r.vals.forEach(function (v) { line.push(num2(v)); });
        L.push(line);
      });
      L.push([]);
      g.caveats.forEach(function (t) { L.push([t]); });
    });
    return "\uFEFF" + L.map(function (row) {
      return row.map(csvCell).join(",");
    }).join("\r\n") + "\r\n";
  }
  function safeName(s) {
    return String(s).replace(/[\\/:*?"<>|\s]+/g, "_");
  }
  function saveFile(content, filename) {
    var blob = new Blob([content], { type: "text/csv;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1500);
  }
  function exportCSV(idx) {
    var g = exportStore[idx];
    if (!g) return;
    var base = (ctxRef && ctxRef.fileBase) || "分析表";
    saveFile(buildCSV([g]), safeName(base + "_分组分析_" + g.group) + ".csv");
  }
  function exportCSVAll() {
    if (!exportStore.length) return;
    var base = (ctxRef && ctxRef.fileBase) || "分析表";
    saveFile(buildCSV(exportStore), safeName(base + "_分组分析_全部") + ".csv");
  }

  global.BoardAnalysis = {
    render: render, setRange: setRange,
    exportCSV: exportCSV, exportCSVAll: exportCSVAll,
    RANGES: RANGES
  };

})(window);
