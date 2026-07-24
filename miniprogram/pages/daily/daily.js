const { loadData } = require('../../utils/data.js');
const { VARIETY_NAMES, VARIETY_UNITS, DEFAULT_UNIT, VARIETY_SOURCES, CATEGORIES } = require('../../utils/constants.js');
const { formatDate, getMonthDays, isWorkingDay, fmtNum, computeMonthlyStats } = require('../../utils/stats.js');
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
  data: {
    cards: [], updated: '', latest: '', totalDays: 0,
    monthValue: '', headers: [], table: [], todayIdx: -1, monthLabel: '', empty: false, loading: true, scrollTo: ''
  },
  onLoad() { this.refresh(); },
  refresh() {
    loadData().then(json => {
      const allData = json.data;
      this.allData = allData;
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

      const [y, m] = latestDate.split('-');
      this.setData({ monthValue: `${y}-${m}` });
      this.buildTable(Number(y), Number(m));
    });
  },
  onMonthChange(e) {
    const val = e.detail.value;
    const [y, m] = val.split('-');
    this.setData({ monthValue: val });
    this.buildTable(Number(y), Number(m));
  },
  buildTable(year, month) {
    const allData = this.allData;
    const days = getMonthDays(year, month);
    const activeDays = days.filter(d => {
      if (!isWorkingDay(d)) return false;
      const row = allData[formatDate(d)];
      return row && Object.values(row).some(v => v != null);
    });
    if (activeDays.length === 0) { this.setData({ empty: true, loading: false }); return; }

    const todayStr = formatDate(new Date());
    const todayIdx = activeDays.findIndex(d => formatDate(d) === todayStr);
    const headers = activeDays.map(d => `${d.getMonth() + 1}/${d.getDate()}`);
    const table = CATEGORIES.map((cat, idx) => ({
      name: cat.name,
      cls: 'cat-' + idx,
      items: cat.codes.map(code => {
        let sum = 0, cnt = 0;
        const cells = activeDays.map((d, i) => {
          const v = allData[formatDate(d)] ? allData[formatDate(d)][code] : null;
          if (v != null) { sum += v; cnt++; return { v: fmtNum(v), today: i === todayIdx }; }
          return { v: '—', empty: true, today: i === todayIdx };
        });
        const avg = cnt > 0 ? Math.round(sum / cnt * 100) / 100 : null;
        return {
          code, name: VARIETY_NAMES[code], unit: VARIETY_UNITS[code] || DEFAULT_UNIT,
          source: VARIETY_SOURCES[code] || '', cells, avg: fmtNum(avg)
        };
      })
    }));
    this.setData({ headers, table, todayIdx, monthLabel: `${year}年${month}月`, empty: false, loading: false }, () => {
      // 默认滚到最右：最新两天 + 月均价可见，更早日期横拉（左滑）查看
      const self = this;
      this.setData({ scrollTo: '' });
      setTimeout(() => self.setData({ scrollTo: 'lastCol' }), 60);
    });
  }
};

Page(Object.assign({}, sheet, page, { data: Object.assign({}, sheet.data, page.data) }));
