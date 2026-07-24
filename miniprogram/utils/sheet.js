// 点击品种名 -> 底部弹层显示数据来源（替代 web 版的 hover tooltip）
// 用法：页面 Page(Object.assign({}, sheet, pageDef, { data: Object.assign({}, sheet.data, pageDef.data) }))
module.exports = {
  data: {
    sheet: { show: false, name: '', source: '', unit: '' }
  },
  onTapVariety(e) {
    const ds = e.currentTarget.dataset;
    this.setData({
      sheet: { show: true, name: ds.name, source: ds.source || '未知', unit: ds.unit || '' }
    });
  },
  closeSheet() {
    this.setData({ 'sheet.show': false });
  }
};
