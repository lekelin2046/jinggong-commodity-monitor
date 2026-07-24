const { loadData } = require('../../utils/data.js');
const { VARIETY_NAMES, VARIETY_UNITS, DEFAULT_UNIT, CATEGORIES } = require('../../utils/constants.js');
const { computeMonthlyStats, formatDate } = require('../../utils/stats.js');
const sheet = require('../../utils/sheet.js');

function chg(cur, prev) {
  if (cur == null || prev == null) return '';
  const c = (cur - prev) / prev * 100;
  return (c >= 0 ? '+' : '') + c.toFixed(1) + '%';
}
function fmt(v) {
  if (v == null) return '—';
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

const page = {
  data: { cards: [], updated: '', latest: '', totalDays: 0, loading: true },
  onLoad() { this.refresh(); },
  onPullDownRefresh() { this.refresh(() => wx.stopPullDownRefresh()); },
  refresh(cb) {
    loadData().then(json => {
      const allData = json.data;
      const datesAll = Object.keys(allData).sort();
      const latestDate = datesAll[datesAll.length - 1];
      const latestVal = allData[latestDate] || {};
      const prevDate = datesAll.length >= 2 ? datesAll[datesAll.length - 2] : null;
      const prevVal = prevDate ? allData[prevDate] : {};

      const todayStr = formatDate(new Date());
      const todayData = allData[todayStr] || {};
      const varietyCount = Object.keys(todayData).filter(k => todayData[k] != null).length;

      const now = new Date();
      const mKey = String(now.getMonth() + 1).padStart(2, '0');
      const pmKey = String(now.getMonth()).padStart(2, '0');
      const stats = computeMonthlyStats(allData, now.getFullYear());
      const md = stats[mKey] || {};
      const pmd = stats[pmKey] || {};
      let moms = [];
      Object.keys(md).forEach(code => {
        if (md[code] && md[code].avg != null && pmd[code] && pmd[code].avg != null) {
          moms.push((md[code].avg - pmd[code].avg) / pmd[code].avg * 100);
        }
      });
      const avgMom = moms.length ? moms.reduce((a, b) => a + b, 0) / moms.length : 0;

      const cards = [
        { label: '今日更新品种', value: String(varietyCount), unit: '/ ' + CATEGORIES.flatMap(c => c.codes).length, sub: todayStr + ' · 最新 ' + latestDate, up: null },
        { label: '铜 CU · 最新', value: fmt(latestVal.CU), unit: '元/吨', sub: '日 ' + chg(latestVal.CU, prevVal.CU) + ' · 月均 ' + fmt(md.CU ? md.CU.avg : null), up: latestVal.CU != null && prevVal.CU != null ? latestVal.CU >= prevVal.CU : null },
        { label: 'A00铝 · 最新', value: fmt(latestVal.A00_AL), unit: '元/吨', sub: '日 ' + chg(latestVal.A00_AL, prevVal.A00_AL) + ' · 月均 ' + fmt(md.A00_AL ? md.A00_AL.avg : null), up: latestVal.A00_AL != null && prevVal.A00_AL != null ? latestVal.A00_AL >= prevVal.A00_AL : null },
        { label: 'ADC12 · 最新', value: fmt(latestVal.ADC12), unit: '元/吨', sub: '日 ' + chg(latestVal.ADC12, prevVal.ADC12) + ' · 月均 ' + fmt(md.ADC12 ? md.ADC12.avg : null), up: latestVal.ADC12 != null && prevVal.ADC12 != null ? latestVal.ADC12 >= prevVal.ADC12 : null },
        { label: '月均价环比', value: (avgMom >= 0 ? '+' : '') + avgMom.toFixed(1), unit: '%', sub: '全品种均值 · 较上月', up: avgMom >= 0 }
      ];
      this.setData({
        cards, updated: json.last_updated || '', latest: latestDate,
        totalDays: json.total_days || 0, loading: false
      });
      if (cb) cb();
    });
  }
};

Page(Object.assign({}, sheet, page, { data: Object.assign({}, sheet.data, page.data) }));
