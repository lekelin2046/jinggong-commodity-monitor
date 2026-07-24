const { loadData } = require('../../utils/data.js');
const { VARIETY_NAMES, VARIETY_UNITS, DEFAULT_UNIT, VARIETY_SOURCES, CATEGORIES } = require('../../utils/constants.js');
const { formatDate, getMonthDays, isWorkingDay, fmtNum } = require('../../utils/stats.js');
const sheet = require('../../utils/sheet.js');

const page = {
  data: { monthValue: '', headers: [], table: [], todayIdx: -1, monthLabel: '', empty: false, loading: true },
  onLoad() {
    loadData().then(json => {
      this.allData = json.data;
      const dates = Object.keys(this.allData).sort();
      const latest = dates[dates.length - 1];
      const [y, m] = latest.split('-');
      this.setData({ monthValue: `${y}-${m}`, loading: false });
      this.buildTable(Number(y), Number(m));
    });
  },
  onMonthChange(e) {
    const val = e.detail.value; // 'YYYY-MM'
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
    const table = CATEGORIES.map(cat => ({
      name: cat.name,
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
    this.setData({ headers, table, todayIdx, monthLabel: `${year}年${month}月`, empty: false, loading: false });
  }
};

Page(Object.assign({}, sheet, page, { data: Object.assign({}, sheet.data, page.data) }));
