const { HOLIDAYS_2026 } = require('./constants.js');

// 本地日期格式化为 YYYY-MM-DD（避免 UTC 跨天）
function formatDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

// 取某月所有日期（Date 对象数组）
function getMonthDays(year, month) {
  const days = [];
  const d = new Date(year, month - 1, 1);
  while (d.getMonth() === month - 1) {
    days.push(new Date(d));
    d.setDate(d.getDate() + 1);
  }
  return days;
}

// 是否工作日（跳过周末与 2026 法定节假日）
function isWorkingDay(d) {
  const ds = formatDate(d);
  if (HOLIDAYS_2026.has(ds)) return false;
  const dow = d.getDay();
  if (dow === 0 || dow === 6) return false;
  return true;
}

// 按年聚合月度统计：stats[month][code] = { sum, count, min, max, avg }
function computeMonthlyStats(allData, year) {
  const stats = {};
  Object.keys(allData)
    .filter(d => d.startsWith(String(year)))
    .sort()
    .forEach(ds => {
      const month = ds.substring(5, 7);
      if (!stats[month]) stats[month] = {};
      const prices = allData[ds];
      Object.keys(prices).forEach(code => {
        const v = prices[code];
        if (v == null) return;
        if (!stats[month][code]) stats[month][code] = { sum: 0, count: 0, min: Infinity, max: -Infinity };
        const s = stats[month][code];
        s.sum += v; s.count++;
        if (v < s.min) s.min = v;
        if (v > s.max) s.max = v;
      });
    });
  Object.keys(stats).forEach(month => {
    Object.keys(stats[month]).forEach(code => {
      const s = stats[month][code];
      s.avg = s.count > 0 ? s.sum / s.count : null;
    });
  });
  return stats;
}

// 数字格式化：整数原样，小数保留两位
function fmtNum(v) {
  if (v == null) return '—';
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

module.exports = { formatDate, getMonthDays, isWorkingDay, computeMonthlyStats, fmtNum };
