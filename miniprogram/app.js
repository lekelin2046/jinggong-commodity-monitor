const config = require('./config.js');

App({
  globalData: {
    allData: null,   // { data: {...}, last_updated, total_days }
    meta: null
  },
  onLaunch() {
    if (config.USE_CLOUD && config.CLOUD_ENV) {
      if (!wx.cloud) {
        console.error('当前基础库不支持云开发，请升级微信开发者工具基础库到 2.2.3 以上');
      } else {
        wx.cloud.init({ env: config.CLOUD_ENV, traceUser: true });
      }
    }
  }
});
