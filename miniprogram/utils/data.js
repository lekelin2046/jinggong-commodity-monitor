const config = require('../config.js');
const mock = require('../data/mock.js');

// 加载数据：优先云存储，未配置时回退内置 mock（离线可直接预览）
function loadData() {
  return new Promise((resolve) => {
    if (config.USE_CLOUD && config.CLOUD_ENV && typeof wx !== 'undefined' && wx.cloud) {
      const fileID = `cloud://${config.CLOUD_ENV}/${config.CLOUD_FILE_PATH}`;
      wx.cloud.downloadFile({ fileID })
        .then(res => {
          const fs = wx.getFileSystemManager();
          fs.readFile({
            filePath: res.tempFilePath,
            encoding: 'utf-8',
            success: r => {
              try { resolve(JSON.parse(r.data)); }
              catch (e) { resolve(mock); }
            },
            fail: () => resolve(mock)
          });
        })
        .catch(() => resolve(mock));
    } else {
      resolve(mock);
    }
  });
}

module.exports = { loadData };
