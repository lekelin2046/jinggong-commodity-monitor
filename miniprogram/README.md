# 精工有色金属价格监控 · 微信小程序

把现有 Web 看板（`docs/`）搬进微信小程序，手机上随时查看 25 个品种的有色金属价格，点击品种名可看数据来源。

## 目录结构

```
miniprogram/
├── app.js / app.json / app.wxss      # 工程入口与全局样式
├── project.config.json               # 开发者工具工程配置
├── config.js                         # 运行配置（云环境开关）
├── push_to_cloud.py                  # 把 data.json 推送到云存储（或刷新本地副本）
├── data/
│   └── mock.js                       # 离线预览数据副本（自动生成）
├── utils/
│   ├── constants.js                  # 品种名/单位/来源/分类映射
│   ├── stats.js                      # 月度统计、工作日判断
│   ├── data.js                       # 数据加载（云存储优先，mock 回退）
│   └── sheet.js                      # 点击显来源弹层
└── pages/
    ├── index/                        # 概览 KPI
    ├── daily/                        # 日价格明细表
    └── monthly/                      # 月均价明细表
```

## 快速预览（无需任何云端配置）

1. 用**微信开发者工具**打开本项目根目录（`jinggong-commodity-monitor/`），导入类型选「小程序」。
2. `project.config.json` 里 `appid` 默认是 `touristappid`（游客模式），可直接预览。
3. 编译后底部三个 Tab：概览 / 日价格 / 月均价。日价格、月均价页**点击品种名**会弹出数据来源。

> 游客模式只能本地预览，且无法使用云开发；正式给同事用请按下方步骤配置。

## 生产部署（云开发，同事可见）

1. 在微信公众平台注册小程序，拿到 **AppID**，填进 `project.config.json` 的 `appid`。
2. 开发者工具里点「云开发」，开通环境，复制**环境 ID**。
3. 编辑 `miniprogram/config.js`：
   ```js
   module.exports = { USE_CLOUD: true, CLOUD_ENV: '你的环境ID', CLOUD_FILE_PATH: 'data/data.json' };
   ```
4. 上传数据：
   ```bash
   npm i -g @cloudbase/cli && tcb login        # 首次需扫码
   export CLOUD_ENV=你的环境ID
   python3 push_to_cloud.py                     # 把 docs/data.json 推到云存储
   ```
5. 在云开发控制台「存储」里确认 `data/data.json` 已存在。小程序启动即从云存储拉取最新数据。
6. 真机预览 / 上传体验版给同事（体验成员无需审核）。若要上架，需按「金融数据」类目补充资质。

## 数据流水线（不变）

原有 Python 抓取管线（`daily_update_all.py` 等）照常每天跑，生成 `docs/data.json`。
上线小程序后，只需在管线末尾加一步调用 `push_to_cloud.py`（或定时任务），即可把最新价格推到云存储，小程序自动读取。

## 与本仓库 Web 看板的差异

- 悬停 tooltip → 改为**点击品种名弹底部来源层**（移动端无 hover）。
- 趋势图（ECharts）暂未移植，后续可用 `ec-canvas` 组件补充。
- 数据来源、分类、单位、涨跌幅着色规则与 Web 版完全一致。
