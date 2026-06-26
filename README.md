# 精工有色金属共享表自动化填写

> 每天自动抓取 **16 个有色金属/原油品种价格** 填入 Excel「2026年有色金属市场价格共享(2).xlsx」

[![status](https://img.shields.io/badge/status-6%2F26%E8%B7%91%E9%80%9A16%2F16-brightgreen)]()
[![python](https://img.shields.io/badge/python-3.13-blue)]()
[![platform](https://img.shields.io/badge/platform-macOS-lightgrey)]()

---

## 🎯 项目背景

长城汽车·长城保理公司**精工板块**每天下午需要把**长江现货、SMM、亚洲金属网、中钨在线、akshare** 等 5 个数据源的 16 个品种价格，填入一张 16 列的 Excel 共享表。

**之前**：纯人工 + Excel 操作员手工填表，每天 1-2 小时。
**现在**：阿奇（OpenClaw AI 助手）自动抓取 + 一次性写入 Excel，**主人在 Chrome 里保持 SMM/亚洲金属网登录态即可**，每天 < 10 分钟人工介入。

---

## 📊 16 个品种 × 5 个数据源

| Col | 品种 | 数据源 | 抓取方式 | 登录态 |
|:--:|------|--------|--------|:--:|
| 2 | 上海有色 ADC12 | SMM | CDP 页面价格表 | 需登录 |
| 3 | 上海有色 A380 | SMM | CDP 页面价格表 | 需登录 |
| 4 | 上海有色 AlSi9Cu3 | SMM | CDP 页面价格表 | 需登录 |
| 5 | 上海有色 A356 | SMM | CDP 页面价格表 | 需登录 |
| 6 | 长江现货 A00 铝 | **ccmn** | 公开 AJAX | 公开 ✅ |
| 7 | 长江现货 铜 | **ccmn** | 公开 AJAX | 公开 ✅ |
| 8 | 长江现货 金属硅中间价**441** | **ccmn** | `金属硅553#-331#` 的 **avgPrice** | 公开 ✅ |
| 9 | 长江现货 金属硅中间价**3303** | **ccmn** | `金属硅3303#-2202#` 的 **minPrice** | 公开 ✅ |
| 10 | 长江现货 镁 | **ccmn** | 公开 AJAX | 公开 ✅ |
| 11 | 长江现货 电解锰 | **ccmn** | 公开 AJAX | 公开 ✅ |
| 12 | 长江现货 金属硅中间价**331** | **ccmn** | `金属硅553#-331#` 的 **maxPrice** | 公开 ✅ |
| 13 | 亚洲金属网 闻喜镁锭 | 亚洲金属网 | CDP 文章抓取 | 需登录 |
| 14 | 上海有色 AM60B | SMM | CDP 页面价格表 | 需登录 |
| 15 | 上海有色 AZ91D | SMM | CDP 页面价格表 | 需登录 |
| 16 | 中钨在线 钨粉 | 中钨在线 | Playwright + 正则 | 公开 ✅ |
| 17 | WTI 原油 | akshare | realtime API | 公开 ✅ |

**登录依赖统计**：8 项公开（ccmn 7 + akshare 1）+ 8 项需登录（SMM 6 + 亚洲金属网 1 + 中钨在线 1）。

---

## 🚀 快速开始

### 1. 环境要求

- **macOS**（已验证 14.x）
- **Python 3.13**（workbuddy venv）
- **Google Chrome**（调试模式，端口 9223）
- **SMM + 亚洲金属网账号**（主人在调试 Chrome 里保持登录态）

### 2. 启动 Chrome 调试模式

```bash
open -na "Google Chrome" --args \
  --remote-debugging-port=9223 \
  --user-data-dir=/Users/siqi/chrome-debug-profile
```

主人在 Chrome 里登录 `hq.smm.cn` 和 `asianmetal.cn`，登录态会自动保持。

### 3. 一键跑

```bash
cd ~/Desktop/AI/jinggong-commodity-monitor

# 设置网络白名单（避免代理拦截）
export NO_PROXY="sci99.com,chinatungsten.com,51bxg.com,steelcn.cn,ccmn.cn,cnfeol.com,ctia.com.cn,smm.cn,asianmetal.cn,hq.smm.cn"

# 跑主流程
PYTHONPATH=. /Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/python3 fill_and_verify.py
```

### 4. 登录态过期

```bash
PYTHONPATH=. /Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/python3 relogin_assistant.py
```

`relogin_assistant.py` 会自动在 Chrome 里打开 SMM / 亚洲金属网登录页，主人完成登录后自动检测并跑主流程。

### 5. 每日 10:00 抓取长江有色日报

```bash
PYTHONPATH=. /Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/python3 capture_changjiang_daily.py
```

输出：
- `长城有色日价格查询/YYYY-MM-DD_长江有色.md`（项目目录）
- `~/Documents/Obsidian Vault/工作/大宗原材料监控/日报/YYYY-MM-DD-长江有色.md`（Obsidian 归档）

**自动 cron**：每个工作日 10:00（Asia/Shanghai）自动触发。

---

## 📁 项目结构

```
jinggong-commodity-monitor/
├── README.md                       ← 本文件
├── SKILL.md                        ← 流程定义（最新 6/26 跑通版，30 KB）
├── fill_and_verify.py              ← 主流程（填 Excel + 历史核查）
├── relogin_assistant.py            ← 登录态修复助手
├── capture_changjiang_daily.py     ← 每日 10:00 抓取长江有色
├── run.sh                          ← 一键运行脚本
├── 2026年有色金属市场价格共享(2).xlsx  ← Excel 共享表
├── jinggong_monitor/               ← 核心代码（18 个模块）
│   ├── base.py                     ← BaseFetcher + _parse_price_range 价格解析
│   ├── orchestrator.py             ← 多源调度
│   ├── fetcher_ccmn.py             ← 长江有色 AJAX（公开 ⭐）
│   ├── fetcher_akshare.py          ← WTI 原油
│   ├── fetcher_asianmetal.py       ← 闻喜镁锭（CDP 登录）
│   ├── fetcher_tungsten.py         ← 中钨在线
│   ├── excel_filler.py             ← openpyxl 写表
│   ├── validator.py                ← 数据校验
│   └── ...
├── config/
│   ├── varieties.yaml              ← 品种-数据源映射（17 个品种）
│   └── sources.yaml                ← 数据源配置
├── 长城有色日价格查询/             ← 每日长江有色 markdown 归档
│   └── 2026-06-26_长江有色.md
├── data/                           ← 历史数据
├── output/                         ← 临时输出
└── pipeline/                       ← pipeline 工具
```

---

## ⚠️ 关键经验（踩坑教训）

### 1. 金属硅中间价字段映射（2026-06-26 主人拍板 — 硬规则）

表头中的 "441 / 331 / 3303" 是**字段名后缀**，**不是 ccmn 上的硅牌号**。真实取值规则：

| Excel 表列名 | **ccmn 真实字段** | 取值 |
|---|---|---|
| 金属硅中间价**441** | `金属硅553#-331#` | **avgPrice**（均价）|
| 金属硅中间价**331** | `金属硅553#-331#` | **maxPrice**（最高价）|
| 金属硅中间价**3303** | `金属硅3303#-2202#` | **minPrice**（最低价）|

**反例**（❌ 不要再这样取）：
- ❌ 441#硅 的 avgPrice（H 列错取）
- ❌ 3303#硅 的 avgPrice（I 列错取）
- ❌ 553#硅 的 avgPrice（L 列错取）

### 2. Excel 写入工具：禁止 officecli（2026-06-26 主人拍板 — 硬规则）

**核心问题**：officecli 的 `set` 子命令会**触发 watch session 持久化进程**，多次 set 会互相覆盖（先写的值后写的会清空）。

**6/26 实战时间线**：
- 16:28 用 officecli set 14 项 → 写完发现 H/I/L 空
- 16:31 用 officecli set 补 H/I/L → 13 项又变空
- 16:33 用 officecli set 再补 → 又出问题
- 16:56 **改用 openpyxl 一次性写 16 项 → 稳了**

**硬规则**：
- ✅ **写入** Excel 一律用 **openpyxl 一次性写完整行**
- ❌ **禁用** `officecli set`（即使只改一个单元格也会触发 watch）
- ❌ 写完后**不要用 officecli get 验证**（get 也会开 watch session 持锁）
- ✅ **读取**可以用 officecli（只读），但要立即杀进程

**正确写法**：
```python
import openpyxl
from openpyxl.styles import PatternFill

wb = openpyxl.load_workbook(EXCEL_PATH)
ws = wb["日均价（2026年市场）"]
# 一次性写完整行
ws['B115'] = 23850
ws['C115'] = 25750
# ... 全部列一次写完
ws['P115'] = None  # 钨粉 当日无新文 留空
ws['P115'].fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
wb.save(EXCEL_PATH)

# 写完必跑清场
# pkill -9 -f officecli
```

### 3. ccmn AJAX 端点（关键发现）

**直接抓 ccmn 主页**（`https://www.ccmn.cn/cjxh.shtml`）拿不到价格表（JS 渲染），必须用 AJAX 端点：

```
POST https://www.ccmn.cn/shop/historyData/getCorpStmarketPriceList
Referer: https://www.ccmn.cn/cjxh.shtml
X-Requested-With: XMLHttpRequest

data:
  marketVmid=40288092327140f601327141c0560001  # 长江现货
  publishDate=YYYY-MM-DD
  flag=1
  productVmid=
```

**返回值**：JSON 含 36 个品种价格（每个含 min/max/avg/unit/trademark/publishTime）。

### 4. 登录态自动修复

SMM / 亚洲金属网登录态过期时，`relogin_assistant.py` 会：
1. 自动在 Chrome 调试模式里打开 SMM 登录页
2. 主人完成登录（输入账号密码）
3. 轮询检测登录态（每 5 秒，最长 5 分钟）
4. 检测到登录成功 → 自动开亚洲金属网登录页 → 同样检测
5. 两个站都登录后 → 自动跑 `fill_and_verify.py`

### 5. 价格区间中位值法

**封装**：`BaseFetcher._parse_price_range(raw)`（`jinggong_monitor/base.py`）

| 输入 | 输出 |
|------|------|
| `"16,050-16,150"` | `16100.0`（中位）|
| `"16,050–16,150"` | `16100.0`（支持长破折号）|
| `"16,150"` | `16150.0`（单值）|
| `""` / `"abc"` / <100 / >1,000,000 | `None`（过滤）|

所有 fetcher 都用这个解析价格范围。

---

## 🛠️ 关键技术方案

### ccmn AJAX 端点（公开 7 项 ⭐）

**实现**：`jinggong_monitor/fetcher_ccmn.py`

7 个公开品种（A00 铝 / 1#铜 / 1#镁 / 1#电解锰 / 3 个金属硅中间价）都能从这一个 AJAX 端点拉到。

### SMM 抓取（CDP 登录态 6 项）

**铝页** `https://hq.smm.cn/aluminum` 抓 4 项：
- `SMM铝合金ADC12`、`A380铝合金`、`AlSi9Cu3铝合金`、`A356铝合金`

**镁页** `https://hq.smm.cn/magnesium` 抓 2 项：
- `SMM镁合金AM60B出厂价`、`SMM镁合金AZ91D出厂价`

**重要**：所有价格都是「区间 + 均价」结构（如 `23700~24000	23850`），**取均价列**。

### 亚洲金属网抓取（CDP 登录态 1 项）

1. 列表页 `https://www.asianmetal.cn/product/data/mj/40/civilPrice/` 选「6月N日中国镁锭价格分区域」文章
2. 文章页 JS 提取「闻喜 + 镁锭 + 99.9%min」行
3. 解析 `16,000-16,100` → 中位值 `16,050`

### 中钨在线（公开 1 项，偶发无文）

**入口**：`http://news.chinatungsten.com/cn/tungsten-product-news.html`（**HTTP 不是 HTTPS**）

⚠️ **必须 HTTP，不能 HTTPS** — `https://news.chinatungsten.com` 会 `WRONG_VERSION_NUMBER`

**正则**：`r'钨粉价格\s*(\d+)\s*元[／/]\s*千克'`

**6/26 摸清规律**：
- ⚠️ 文章可能隔天发（6/25 文章标题里有 6/25 内容，但栏目页刷新可能滞后；6/26 抓到的是 6/25 文章，**正常现象**）
- ⚠️ 当日无新文时**保留空 + 标黄**（不动其他列）

### akshare WTI（公开 1 项）

```python
import akshare as ak
df = ak.futures_foreign_commodity_realtime(symbol="CL")
price = df.iloc[0]['最新价']  # 实时价（每日 15:00 时点）
```

---

## 📈 6/26 验收（16/16 全填 + 钨粉留空）

| Col | 品种 | 6/26 值 | 数据源 |
|:--:|------|------|------|
| B | ADC12 | 23,850 | SMM |
| C | A380 | 25,750 | SMM |
| D | AlSi9Cu3 | 24,750 | SMM |
| E | A356 | 23,100 | SMM |
| F | A00 铝 | 22,880 | ccmn |
| G | 铜 | 101,700 | ccmn |
| **H** | **金属硅441** | **10,000** | ccmn **新规则** |
| **I** | **金属硅3303** | **10,400** | ccmn **新规则** |
| J | 镁 | 17,700 | ccmn |
| K | 电解锰 | 19,200 | ccmn |
| **L** | **金属硅331** | **10,700** | ccmn **新规则** |
| M | 闻喜镁锭 | 16,050 | 亚洲金属网 |
| N | AM60B | 18,000 | SMM |
| O | AZ91D | 18,200 | SMM |
| P | 钨粉 | **空（标黄）** | 6/26 无新文 |
| Q | WTI 原油 | 69.41 | akshare |

---

## 🔄 自动化 Roadmap

| 阶段 | 状态 | 内容 |
|------|:--:|------|
| **6/25** | ✅ 跑通 | 16/16 全填（手工触发）|
| **6/26** | ✅ 跑通 | 金属硅新规则 + officecli 硬规则 + 6/26 数据 |
| **6/27+** | 🟡 进行中 | 每日 10:00 长江有色 cron 已上线（capture_changjiang_daily.py）|
| 7 月 | ⚪ 规划 | 每日 15:00 主流程 cron（fill_and_verify.py 自动化）|
| 7 月 | ⚪ 规划 | 邮件/Slack 通知：填表完成后自动发日报 |
| 8 月 | ⚪ 规划 | 历史回溯：ccmn AJAX 按 publishDate 回溯历史日期 |
| 长期 | ⚪ 规划 | 多 Excel 表支持（兄弟公司共享表）|

---

## 📚 相关文档

- **`SKILL.md`**（30 KB）— 流程定义完整版（最新 6/26 跑通版）
- **`Obsidian Vault/工作/大宗原材料监控/14-`** — 项目主页
- **`Obsidian Vault/工作/大宗原材料监控/16-2026-06-26 收尾总结`** — 6/26 收尾与流程迭代

---

## 🤝 致谢

- **长城有色金属网**（ccmn.cn）— 提供公开 AJAX 价格端点
- **上海有色网**（smm.cn）— 铝合金/镁合金实时价
- **亚洲金属网**（asianmetal.cn）— 镁锭分区域日报
- **akshare** — WTI 原油免费 API

---

## 📜 License

内部使用（长城保理公司·市场部）

---

_最后更新：2026-06-26 17:01_
