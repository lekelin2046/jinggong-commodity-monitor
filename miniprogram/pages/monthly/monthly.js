const { loadData } = require('../../utils/data.js');
const { VARIETY_NAMES, VARIETY_UNITS, DEFAULT_UNIT, VARIETY_SOURCES, CATEGORIES } = require('../../utils/constants.js');
const { computeMonthlyStats, fmtNum } = require('../../utils/stats.js');
const sheet = require('../../utils/sheet.js');

const page = {
  data: { months: [], table: [], latest: '', year: 2026, loading: true },
  onLoad() {
    loadData().then(json => {
      this.allData = json.data;
      const year = new Date().getFullYear();
      this.setData({ year });
      this.buildMonthly(year);
    });
  },
  buildMonthly(year) {
    const stats = computeMonthlyStats(this.allData, year);
    const months = Object.keys(stats).sort();
    if (months.length === 0) { this.setData({ loading: false, table: [] }); return; }
    const latest = months[months.length - 1];
    const table = CATEGORIES.map(cat => ({
      name: cat.name,
      items: cat.codes.map(code => {
        const cells = months.map(m => {
          const s = stats[m][code];
          const avg = s && s.avg != null ? Math.round(s.avg * 100) / 100 : null;
          return { v: fmtNum(avg), latest: m === latest };
        });
        let mom = '';
        const idx = months.indexOf(latest);
        if (idx > 0) {
          const prev = stats[months[idx - 1]][code];
          const cur = stats[latest][code];
          if (cur && cur.avg != null && prev && prev.avg != null) {
            const c = (cur.avg - prev.avg) / prev.avg * 100;
            mom = (c >= 0 ? '+' : '') + c.toFixed(1) + '%';
          }
        }
        return {
          code, name: VARIETY_NAMES[code], unit: VARIETY_UNITS[code] || DEFAULT_UNIT,
          source: VARIETY_SOURCES[code] || '', cells, mom,
          momUp: mom && mom[0] === '+'
        };
      })
    }));
    this.setData({ months, table, latest, loading: false });
  }
};

Page(Object.assign({}, sheet, page, { data: Object.assign({}, sheet.data, page.data) }));
