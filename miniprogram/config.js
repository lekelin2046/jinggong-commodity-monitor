// 小程序运行配置
// 生产环境：把 USE_CLOUD 改为 true，并填入你的云开发环境 ID（在微信开发者工具「云开发」控制台查看）
// 离线预览：保持 USE_CLOUD=false，使用 miniprogram/data/mock.js 内置数据
module.exports = {
  USE_CLOUD: false,
  CLOUD_ENV: '',                 // 例如 'jinggong-xxxx'
  CLOUD_FILE_PATH: 'data/data.json'  // 云存储中 data.json 的对象路径
};
