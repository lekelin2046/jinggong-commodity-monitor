---
name: 精工有色金属共享表自动化填写
description: 精工板块每日有色金属市场均价采集与 Excel 填写。覆盖 26 项品种（Excel 列 2–27）、7 类数据源（ccmn 公开 AJAX / SMM 登录态 / 亚洲金属网登录态 / 卓创 Cookie / akshare / 中钨在线 OCR / LME 官方价）。每日 15:00 主抓 + 17:00 补抓 + 次日 09:00 LME 回填，均由平台定时任务触发。
agent_created: true
version: 3.3
last_updated: 2026-09-17
changelog:
  v3.3 (2026-09-17 夜):
    - + **分组分析模块** `docs/board-analysis.js`（仅接 `docs/rubber/`）：复刻《诺博橡胶大宗物料价格走势-2026.xlsx》工作表「原材料价格走势-周报」的形态——每组=折线图+统计表+自动摘要；指标行＝本周/上周均价、本周/上月均价、年度均价、较上周/较上月/较各历史年均价涨幅
    - 隆众 15 项历史**回溯到 2020-07-01**（`backfill_plastic_ext --from 2020-07-01`，+14508 点），data.json 现 **1552 个交易日**，年度对比行才跑得满
    - ⚠️ `backfill_plastic.py` **不带 `--only` 是全量重建**，会覆盖 data.json 并丢失隆众长历史 / 桥接品种 / 煤焦油 —— 已写入脚本 docstring 警示
    - 口径修正（未照搬原表缺陷）：原表「周均价」窗口内多数只有 2 个交易日有值、「月均价」部分为 10 日均价、各板块截止日不一致（8/18 vs 6/12）
  v3.2 (2026-09-17 晚):
    - 诺博板块**拆页面·共用数据**：新增 `docs/rubber/`（诺博橡胶 21 项），`docs/plastic/` 收敛为诺博内外饰 13 牌号；两者共用 `docs/plastic/data.json`
    - + `jinggong_monitor/bridge_jinggong.py`：精工→诺博数据接续（原油每日；`--history` 借同源 SMM 铝历史）
    - 历史回填扩至一年：隆众 15 项 249 个交易日、中塑 13 牌号回溯至 2025-09-17（源站为**滚动一年窗口**）
    - 修：前端 KPI「今日更新品种/月均价环比」按本页 CATEGORIES 过滤（共用 data.json 会串算对方品种）
    - 修：`backfill_plastic.py` 增量模式丢失扩品类品种表的问题；`MAX_PAGES` 30→36
  v3.1 (2026-09-17):
    - + 附录 E：塑料/橡胶模块（13 牌号、docs/plastic/ 看板、backfill --only）——此前 SKILL 完全未覆盖
    - + 附录 E.2：5 个候选源的可行性实测结论（SMM 扩品类 / 百川免登录 / 隆众 dc 结构化 API 需登录 / 同花顺无外盘 / 生意社口径差异）
    - 注：附录 E.2 的隆众结论当日两次更新——文章正文确为会员墙，但 `dc.oilchem.net` 结构化价格库可用；同日取得账号实登后**已验证 13 牌号全部取到真实价**（权限分品种、cookie 直连、免浏览器）
    - + 已验证替代路径（新浪外盘 hf_OIL）
    - 注：正文「16 品种」已过时，主线实为 26 品种 × 7 源
  v3.0 (2026-06-29):
    - + 21:00 钨粉晚点补查 cron
    - + 价格校验机制（偏差 >50% 标黄不写）
    - + Excel 字体格式统一（微软雅黑 11）
    - + 截图按数据源整页截（ccmn 改 full_page）
    - + 闻喜镁锭只走亚洲金属网（去掉 SMM 备源）
    - + 钨粉 fetcher 改遍历前 5 篇
    - + sheet2 自动创建（历史上共享(2).xlsx 删过那个 sheet）
  v2.0 (2026-06-29):
    - + 17:00 主流程 cron
    - + 截图保存到 screenshots/YYYY-MM-DD/
    - + 中钨在线 HTML 证据
  v1.0 (2026-06-25):
    - 首次跑通 16/16 全填
---

# 精工有色金属共享表自动化填写

## 🎯 一句话总览

每天 **15:00** 全品种自动抓价格填入 Excel（`daily_update_all.py`）→ **17:00** 补抓漏项（`daily_check_missed.py`）→ **次日 09:00** LME 铝按官方数据日回填（`backfill_lme_official.py`）。**ccmn + akshare + 中钨在线 + LME 不需登录**，**SMM + 亚洲金属网需登录，卓创需 Cookie**——登录态过期时抓取脚本会自动重登（内置于 `jinggong_monitor/fetcher_smm.py`）。截图/证据保存到 `screenshots/{日期}/` 供后期追溯。

> 本 SKILL 只覆盖**精工板块**。另两个板块见项目内 `docs/rubber/`（诺博**橡胶**：铝/化工/三元乙丙/炭黑/天然橡胶/合成橡胶/助剂 21 项）、`docs/plastic/`（诺博**内外饰**：PC/ABS/PP/POE/PA6 共 13 牌号）、`docs/mand/`（曼德），说明文档见 Obsidian `raw/工作/大宗原材料监控/`。
> ⚠️ `docs/rubber/` 与 `docs/plastic/` **共用同一份 `docs/plastic/data.json`**（抓取与推送仍各一次，故障面不增加）。两边前端各自只用 `CATEGORIES` 声明自己的品种，**页面是分开的、链接可以分别发人**。

## 📊 26 个品种 × 7 类数据源（Excel 列 2–27）

| Col | 项目 | 数据源 | 登录态要求 |
|:--:|------|--------|------|
| 2–5 | 上海有色 ADC12 / A380 / AlSi9Cu3 / A356 | SMM | **需登录** |
| 6 | 长江现货 A00 铝 | ccmn AJAX | 公开 ✅ |
| 7 | 长江现货 铜 | ccmn AJAX | 公开 ✅ |
| 8 | 长江现货 金属硅中间价441 | ccmn AJAX — `金属硅553#-331#` 的 **avgPrice**（非字面 441# 硅） | 公开 ✅ |
| 9 | 长江现货 金属硅中间价3303 | ccmn AJAX — `金属硅3303#-2202#` 的 **minPrice**（非字面 3303# 硅） | 公开 ✅ |
| 10 | 长江现货 镁 | ccmn AJAX | 公开 ✅ |
| 11 | 长江现货 电解锰 | ccmn AJAX | 公开 ✅ |
| 12 | 长江现货 金属硅中间价331 | ccmn AJAX — `金属硅553#-331#` 的 **maxPrice**（非字面 553# 硅） | 公开 ✅ |
| 13 | 亚洲金属网 闻喜镁锭 | 亚洲金属网 | **需登录** |
| 14–15 | 上海有色 AM60B / AZ91D | SMM | **需登录** |
| 16 | 中钨在线 钨粉 | 中钨在线（报价表**已图片化**，走多窗口 OCR） | 公开 ✅ |
| 17 | WTI 原油 | akshare `futures_foreign_commodity_realtime('CL')` | 公开 ✅ |
| 18 | 铁矿石 卡粉65%京唐港 | SMM 钢铁 | **需登录** |
| 19 | 一级冶金焦 MT<7 全国均价 | SMM 钢铁 | **需登录** |
| 20–25 | 304 / 409 / 439 / 441 不锈钢板材、镍铁、高碳铬铁 | 卓创资讯 | **需 Cookie** |
| 26 | ADC12 日本 CIF | SMM | **需登录** |
| 27 | LME 铝 | LME 官网官方价（Cash Ask，**次日 09:00 回填**） | 公开 ✅ |

**登录依赖统计**：10 项公开（ccmn 7 + akshare 1 + 中钨在线 1 + LME 1），16 项需凭据（SMM 9 + 亚洲金属网 1 + 卓创 6）。

> ⚠️ **列映射三处必须同步**：`daily_update_all.py` 的 `COL_MAP`、`export_excel_to_json.py` 的 `COLUMN_MAP`、`sync_from_web.py` 的 `COLUMN_MAP`。漏任一处的列在「发布」或「线上编辑回写」环节会失效。

---

## 🌐 数据源详解

### 1️⃣ ccmn AJAX 端点（公开，无需登录）⭐ 6/25 接入

**核心发现**：主人提示看 `https://www.ccmn.cn/cjxh.shtml`（查询入口页），JS 动态加载价格。

**抓取端点**：
```
POST https://www.ccmn.cn/shop/historyData/getCorpStmarketPriceList
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
Referer: https://www.ccmn.cn/cjxh.shtml
X-Requested-With: XMLHttpRequest

data:
  marketVmid=40288092327140f601327141c0560001  # 长江现货
  publishDate=YYYY-MM-DD
  flag=1
  productVmid=
```

**返回值**：JSON 含 36 个品种价格，每个品种含 `productSortName` / `avgPrice` / `minPrice` / `maxPrice` / `publishTime`。

## ⚠️ 金属硅中间价字段映射规则（2026-06-26 主人拍板 — 硬规则）

**重要**：表头中的 "441 / 331 / 3303" 是**字段名后缀**，**不是 ccmn 上的牌号**。真实取值规则如下：

| 表列名 | Excel Col | **ccmn 真实字段** | 取值 |
|---|---|---|---|
| 长江现货金属硅中间价441 | H | `金属硅553#-331#` | **avgPrice**（均价）|
| 长江现货金属硅中间价331 | L | `金属硅553#-331#` | **maxPrice**（最高价）|
| 长江现货金属硅中间价3303 | I | `金属硅3303#-2202#` | **minPrice**（最低价）|

**反例（❌ 不要再这样取）**：
- ❌ 441#硅 的 avgPrice（H 列错取）
- ❌ 3303#硅 的 avgPrice（I 列错取）
- ❌ 553#硅 的 avgPrice（L 列错取）

**6/25 实际数据**（主人 15:18 核实，ccmn 真实值）：

| 字段 | min | max | avg |
|---|---|---|---|
| `金属硅553#-331#` | 9300 | 10700 | 10000 |
| `金属硅3303#-2202#` | 10400 | 14400 | 12400 |

→ 所以 6/25 H114（441）= **10000**、I114（3303）= **10400**、L114（331）= **10700**

**目标品种映射**（6/26 修正后版本）：

| ccmn 品种名 | 标准 ID | 6/25 值 | Excel Col |
|------|------|------|:--:|
| `A00铝` | A00_AL | 22,850 | 6 |
| `1#铜` | CU | 101,180 | 7 |
| `金属硅553#-331#` | SI_553_331_AVG | 10,000 | 8（H 列，中间价441）|
| `金属硅3303#-2202#` | SI_3303_2202_MIN | 10,400 | 9（I 列，中间价3303）|
| `1#镁` | MG | 17,800 | 10 |
| `1#电解锰` | MN | 19,200 | 11 |
| `金属硅553#-331#` | SI_553_331_MAX | 10,700 | 12（L 列，中间价331）|
| `1#电解锰` | MN | 19,200 | 11 |
| `铝合金ADC12` | ADC12（备选） | 23,500 | - |
| `铸造铝合金锭(A356.2)` | A356（备选） | 23,500 | - |

## ⚠️ Excel 写入工具选择（2026-06-26 主人拍板 — 硬规则）

**本项目 Excel 文件（`2026年有色金属市场价格.xlsx`）一律用 openpyxl 一次性写入，禁止用 officecli 写入。**

**原因**：officecli 的 `set` 子命令会触发 watch session 持久化进程（持文件 + 后台监听）：
- 第一次 `set` 写完 H115=10000，watch session 留着不释放
- 第二次 `set` 写 B115=23850 时，**新 watch session 触发重写**，把第一次的 H115 覆盖成空
- 第三次再 `set` 又触发，**前面写的全空**
- 最终效果：**只有最后一次 set 的单元格有值，其他全空**

**6/26 实战踩坑**：
- ❌ 用 officecli 写 14 项 → 写完验证 H/I/L 全空
- ❌ 再用 officecli 补 H/I/L → 13 项又被清空
- ✅ 最后用 openpyxl 一次性写 16 项 → 全稳

**正确写法**（参考）：
```python
import openpyxl
from openpyxl.styles import PatternFill

wb = openpyxl.load_workbook(EXCEL_PATH)
ws = wb["日均价（2026年市场）"]
# 一次性写完整行
ws['B115'] = 23850
ws['C115'] = 25750
# ... 一次性写完所有列
ws['P115'] = None  # 钨粉 留空
ws['P115'].fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
wb.save(EXCEL_PATH)
```

**禁止事项**：
- ❌ `officecli set <file> /Sheet!Cell --prop value=X`（即使只改一项）
- ❌ `officecli get <file>`（get 也会开 watch session）
- ❌ 写完后用 officecli 验证（先杀进程再单独跑 get 也不行，会重复持锁）

**读取**可以用 officecli（只读不持锁），但要确保写完后立即杀光所有 officecli 进程。
| `铸造铝合金锭(A380）` | A380（备选） | 25,600 | - |

**实现**：`jinggong_monitor/fetcher_ccmn.py`（v2 已重写）

### 2️⃣ SMM 上海有色网（CDP 登录态）

**访问方式**：CDP 连调试 Chrome（端口 9223），**必须已登录 SMM**。

**铝页** `https://hq.smm.cn/aluminum` 价格表结构：

| 品种 | SMM 名 | 6/25 值 |
|------|------|------|
| ADC12 | `SMM铝合金ADC12` 或 `华东ADC12` | 23,850（23700-24000 中位）|
| A380 | `A380铝合金` | 25,750（25500-26000 中位）|
| AlSi9Cu3 | `AlSi9Cu3铝合金` | 24,750（24500-25000 中位）|
| A356 | `A356铝合金` | 23,100（22900-23300 中位）|

**镁页** `https://hq.smm.cn/magnesium` 价格表结构：

| 品种 | SMM 名 | 6/25 值 |
|------|------|------|
| AM60B | `SMM镁合金AM60B出厂价` | 18,050（18000-18100 中位）|
| AZ91D | `SMM镁合金AZ91D出厂价` | 18,250（18200-18300 中位）|

**重要事实**：SMM 价格都是「价格范围 + 均价」结构（如 `23700~24000	23850`），**全部取均价列**（已用 `BaseFetcher._parse_price_range` 中位值法核对）。

**实现**：`jinggong_monitor/fetcher_smm.py`（如需新增）

### 3️⃣ 亚洲金属网（CDP 登录态）

**列表页**：`https://www.asianmetal.cn/product/data/mj/40/civilPrice/`
**文章页**：今日镁锭分区域文章（如 6/25 是 `/news/2969853/`）
**抓取逻辑**：
1. 列表页选「6月25日中国镁锭价格分区域」文章
2. 文章表格 JS 提取「闻喜 + 镁锭 + 99.9%min」行
3. 解析价格列（`16,050-16,150` → 中位值 `16,100`）

**6/25 验证**：闻喜镁锭 99.9%min = **16,100 元/吨**（区间 16,050-16,150）

**实现**：`jinggong_monitor/fetcher_asianmetal.py`

### 4️⃣ akshare（公开 API，无需登录）

**WTI 原油**（主人 6/25 确认要 15:00 时点价）：
```python
import akshare as ak
df = ak.futures_foreign_commodity_realtime(symbol="CL")
price = df.iloc[0]['最新价']  # 15:00 时点的实时价
```

**6/25 验证**：15:12 实时价 = **69.86 美元/桶**（与英为财情 69.83 一致）

### 5️⃣ 中钨在线（公开，但偶发无文）

**抓取逻辑**：
1. 访问 `http://news.chinatungsten.com/cn/tungsten-product-news/`
2. 找最新「钨」开头的文章（跳过钼）
3. 文章正文正则 `r'钨粉价格\s*(\d+)\s*元[／/]\s*千克'`

**6/25 验证**：**6/25 无钨粉新文章**，最新是 6/24「钨市议价承压」（钨粉 1230 元/千克）。

**应对策略**：**保留为空**，主人手动填或次日文章发布后补。

---

## ⚙️ 标准执行流程

### 定时任务（全部走平台自动化，周一至周五）

| 时间 | 脚本 | 跑什么 |
|:--:|------|------|
| **15:00** | `daily_update_all.py` | 主抓 25 项（LME 铝延后），写 Excel |
| **17:00** | `daily_check_missed.py` | 补抓列 2–26 的漏项 + LME 兜底 |
| **次日 09:00** | `backfill_lme_official.py` | LME 铝按官方数据日回填（写上一数据日那一行） |

```bash
cd ~/Desktop/AI/jinggong-commodity-monitor
unset NODE_OPTIONS                      # 跑 Playwright 前必须

PYTHONPATH=. /Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/python3 daily_update_all.py
```

> ⚠️ 项目里曾有 `run.sh` + `setup_launchd.sh` 的 launchd 方案（`fill_and_verify.py` 主流程）。**已废弃**：launchd 任务当前未加载，`fill_and_verify.py` 已无任何调用方。这些文件已移入 `_legacy/`，不要再依据它们排障。

> **WTI 为什么单独讲时点**：akshare `futures_foreign_commodity_realtime` 是实时 API，取值即调用时点价。主人明确要 **15:00 时点价**，所以主流程排在 15:00。

> **钨粉为什么容易空**：中钨在线报价表**已图片化**，须 OCR（见 B.5）。当日抓不到就留空，绝不沿用前值；可用 `manual_fill_tungsten.py <价>` 人工兜底。

### 登录态过期处理（已自动化，无需人工）

抓取脚本检测到 SMM / 亚洲金属网未登录（抓到零结果）时，会自动完成重登，无需手动跑任何脚本。

内置逻辑（`jinggong_monitor/fetcher_smm.py` 的 `_login_and_save_cookies`）：
1. 检测到抓取零结果 → 判定登录态失效
2. Playwright headless 自动打开登录页并提交账号密码（凭据取自 `.env`）
3. 登录成功后刷新并保存 Cookie 到 `data/`
4. 重试抓取 → 拿到当日数据（全程约 5 秒）

---

## 📸 现场截图与证据保存（6/29 主人拍板）

**目的**：每天 17:00 跑完主流程后，**自动把每个数据源当时的网页截图保存**到项目下的 `screenshots/{日期}/` 文件夹，供后期追溯「这个价是哪个页面什么时候抓的」。

### 截图目录结构

```
jinggong-commodity-monitor/
└── screenshots/
    ├── 2026-06-29/
    │   ├── ccmn_长江现货_170003.png          ← ccmn 首页整页（1280×4026，含页面标题+日期+表格）
    │   ├── smm_铝页_170015.png               ← SMM 铝页价格表（700×932 表格区）
    │   ├── smm_镁页_170022.png               ← SMM 镁页价格表（700×932 表格区）
    │   ├── asianmetal_闻喜镁錠_170038.png   ← 亚洲金属网文章全页（2400×3502）
    │   ├── chinatungsten_钨粉原文_170045.html ← 中钨在线原文 HTML（requests 抓的不是浏览器，用 HTML 作证据）
    │   └── (如某项抓取失败) ❌_xxx_时间戳.png  ← 现场截图，文件名带 ❌ 前缀
    ├── 2026-06-30/
    └── ...
```

### 截图策略（6/29 实战验证）

| 数据源 | 截图方式 | 原因 |
|------|------|------|
| **ccmn 首页** | **整页截图**（1280×4026） | 6/29 主人拍板："**长江现货你截整个表格含日期和标题**"——整页含页面标题+日期+表格区 |
| **SMM 铝/镁页** | 表格区域裁剪 | SMM 价格表是 `<table>`，表格裁剪后最紧凑且含日期列 |
| **亚洲金属网文章页** | 全页截图（~2400×3502） | 文章页无 `<table>`（用 div/ul/li 布局），全页才能看到日期+正文+数据区 |
| **中钨在线** | 保存 HTML 原文 | 该站用 requests 抓取（非浏览器），不能截图。**HTML 是唯一证据** |

### 重要原则：一张图 = 一个数据源页面（不按品种拆）

6/29 主人原话："**不要一个单品就截一个，如果那个页面里涉及多个，就整个表截一个图就行**"

- ccmn 一张图覆盖 7 品种（A00铝/铜/硅441/硅3303/镁/锰/硅331）
- SMM 铝页一张图覆盖 4 品种（ADC12/A380/AlSi9Cu3/A356）
- SMM 镁页一张图覆盖 2 品种（AM60B/AZ91D）
- 亚洲金属网一张图覆盖 1 品种（闻喜镁锭）
- 中钨在线一个 HTML 证据覆盖 1 品种（钨粉）

### 截图保存周期清理

每个 `screenshots/YYYY-MM-DD/` 目录**只保留当天最后一次跑出的 5 个文件**，其他跑测累积文件移到 `~/.Trash/jinggong-shots-HHMM/`（可恢复）。

### 抓取失败也截图

**硬规则**：任何数据源抓取失败时，**也必须截一张现场图**（标 ❌），便于后期排查「当时页面是登录页还是其他异常」。

示例：
- `❌_asianmetal_未登录_170038.png` — 亚洲金属网未登录的登录页
- `❌_smm_未登录_xxx.png` — SMM 跳转到 account.smm.cn 的现场

### 运行结束后会给主人发总结

主流程跑完后会在终端打印类似这样的汇总：

```
==========================================================
📊 运行总结
==========================================================
📅 日期: 2026-06-29
📁 截图目录: screenshots/2026-06-29
📸 截图/证据: 5 项
   ✅ 成功: 4 | ❌ 失败/部分: 1
   ✅ ccmn/长江现货: 2026-06-29/ccmn_长江现货_170003.png
   ✅ smm/铝页: 2026-06-29/smm_铝页_170015.png
   ✅ smm/镁页: 2026-06-29/smm_镁页_170022.png
   ✅ 亚洲金属网/闻喜镁錠: 2026-06-29/asianmetal_闻喜镁錠_170038.png
   ⚠️ 中钨在线/钨粉: 未匹配到钨粉价格正则（可能今日未发文）
📊 Excel 保存: OK
==========================================================
```

**退出码**：0 = 全部成功，1 = 有失败项。cron 接管脚本能据此判断。

---

## 📁 项目文件结构

```
jinggong-commodity-monitor/
├── SKILL.md                          ← 本文件（排障与接口契约）
├── daily_update_all.py               ← 15:00 主抓 25 项
├── daily_check_missed.py             ← 17:00 补抓 + LME 兜底
├── backfill_lme_official.py          ← 次日 09:00 LME 铝回填
├── 2026年有色金属市场价格.xlsx        ← Excel 底稿（唯一，每天更新；gitignore）
├── screenshots/{日期}/                ← 抓取现场截图/证据（gitignore）
├── jinggong_monitor/
│   ├── base.py                       ← BaseFetcher + 价格区间解析
│   ├── orchestrator.py               ← 多源调度
│   ├── trading_calendar.py           ← 交易日历（三板块共用）
│   ├── fetcher_ccmn.py               ← ccmn AJAX（长江现货 7 项）⭐
│   ├── fetcher_smm.py                ← SMM（精工/诺博/曼德共用）
│   ├── fetcher_asianmetal.py         ← 亚洲金属网（闻喜镁锭）
│   ├── fetcher_sci99.py              ← 卓创（Cookie）
│   ├── fetcher_steel.py              ← SMM 钢铁
│   ├── fetcher_tungsten.py           ← 中钨在线（多窗口 OCR）
│   ├── fetcher_akshare.py            ← akshare WTI 实时
│   ├── fetcher_lme.py                ← LME 官方价
│   ├── lz_price_center.py            ← 隆众结构化价格库（诺博）
│   └── ...
├── config/{varieties,sources}.yaml   ← 品种-数据源映射
├── _legacy/                          ← 已废弃脚本（勿用，见其 README）
└── docs/                             ← GitHub Pages 发布目录
```

> 完整目录（含三个板块的全部脚本）见 `README.md`。

---

## 🎯 价格区间通用规则（关键）

**封装位置**：`jinggong_monitor/base.py` → `BaseFetcher._parse_price_range(raw)`

| 输入 | 输出 | 说明 |
|------|------|------|
| `"16,050-16,150"` | `16100.0` | 中位值 = (low+high)/2 |
| `"16,050–16,150"` | `16100.0` | 支持长破折号 `–` |
| `"16,050~16,150"` | `16100.0` | 支持波浪号 `~` |
| `"16,150"` | `16150.0` | 单值原样返回 |
| `""` / `"abc"` / <100 / >1,000,000 | `None` | 过滤 |

**适用**：所有 fetcher 都用这个解析价格范围。

---

## 🔍 6/25 验证数据（基准）

| Col | 6/25 值 | 数据源 | 备注 |
|:--:|------|------|------|
| 2 | 23,850 | SMM | 华东ADC12 区间 23700-24000 中位 |
| 3 | 25,750 | SMM | A380 区间 25500-26000 中位 |
| 4 | 24,750 | SMM | AlSi9Cu3 区间 24500-25000 中位 |
| 5 | 23,100 | SMM | A356 区间 22900-23300 中位 |
| 6 | 22,850 | ccmn | A00铝均价 |
| 7 | 101,180 | ccmn | 1#铜均价 |
| 8 | 9,700 | ccmn | 441#硅均价 |
| 9 | 10,400 | ccmn | 3303#硅均价 |
| 10 | 17,800 | ccmn | 1#镁均价 |
| 11 | 19,200 | ccmn | 1#电解锰均价 |
| 12 | 10,100 | ccmn | 金属硅553#-331#均价 |
| 13 | 16,100 | 亚洲金属网 | 闻喜镁锭 99.9%min 区间 16,050-16,150 中位 |
| 14 | 18,050 | SMM | AM60B 区间 18000-18100 中位 |
| 15 | 18,250 | SMM | AZ91D 区间 18200-18300 中位 |
| 16 | 1200 | 中钨在线 | 「钨粉价格 1200 元/千克」（6/25 文章「钨价弱稳运行」6/26 补填）|
| 17 | 69.83 | akshare | WTI 15:12 实时价 |

**结果**：16/16 已填全。钨粉为 6/26 早晨补填（详见「中钨在线时间差」段）。

---

## 🛡️ 价格校验机制（6/29 主人拍板 — 硬规则）

**背景**：6/29 17:00 cron 跑到 ccmn 1#电解锰时，**ccmn 临时返回 MN=6**（采集异常，正常值 19,200），脚本没校验直接写入，主人看出错误。

**硬规则**：写入 Excel 前，**新价与历史 5 天均价对比，偏差 >50% 视为采集错误 → 标黄不写**（不覆盖现有数据）。

```python
def historical_avg(ws, col, current_row):
    """拿历史上 5 个有效日的均价（用于偏差校验）。
    关键：不能包含 current_row（今天），避免自污染。
    """
    vals = []
    for r in range(max(2, current_row-30), current_row):  # 严格 < current_row
        v = ws.cell(row=r, column=col).value
        if v and isinstance(v, (int, float)) and v > 100:  # 过滤 0/None/异常小值
            vals.append(v)
            if len(vals) >= 5: break
    if not vals: return None
    return sum(vals) / len(vals)

# 写入前校验
if price and price > 0:
    hist_avg = historical_avg(ws, col, row_num)
    if hist_avg and abs(price - hist_avg) / hist_avg > 0.5:
        cell = ws.cell(row=row_num, column=col)
        cell.fill = YELLOW_FILL
        diff_pct = abs(price - hist_avg) / hist_avg * 100
        reason = f"{date_str}: {variety}={price} 与历史均价{hist_avg:.0f} 偏离 {diff_pct:.1f}%，可能采集错误，标黄不写"
        remarks.append(reason)
        logger.warning(reason)
    else:
        ws.cell(row=row_num, column=col, value=price)
```

**实现位置**：`daily_update_all.py` 的写入循环内。

**实战验证（6/29 17:33）**：
- 抓到 MN=6 → 跟历史 19,380 偏离 100% → 标黄不写
- log 输出：「2026-06-29: MN=6 与历史均价19380 偏离 100.0%，可能采集错误，标黄不写」

**手动修正**：6/29 Row118 K118 改为 19,200（ccmn 6/29 实际返回的正确值）。

**阈值 50%**（不是 10%）：ccmn 价格波动小，太严会误伤；SMM 波动大可单独调阈值。

---

## 🛡️ Excel 字体格式统一（6/29 主人拍板 — 硬规则）

**问题**：主人原话"**注意填入表格字体格式的统一**"——脚本默认 openpyxl 写入用 Calibri 11，跟原表微软雅黑 11 不一致。

**硬规则**：填入 Excel 单元格时**强制用原表字体**：

```python
from openpyxl.styles import Font

# 6/29 主人拍板：填表字体与原表统一
DATA_FONT = Font(name='微软雅黑', size=11, bold=False)  # 数据行用 微软雅黑 11
HEADER_FONT = Font(name='微软雅黑', size=10, bold=True)  # 标题行用 微软雅黑 10
DATE_FONT = Font(name='微软雅黑', size=11, bold=False)
```

**实现位置**：`daily_update_all.py` 顶部常量 + 写入时 `cell.font = DATA_FONT`。

**验证**：写完后 6/29 Row118 全部 17 列字体 = 微软雅黑 11。

---

## 🛡️ 闻喜镁锭主业要求（6/29 主人拍板 — 硬规则）

**主人原话**：「**闻喜的镁锭必须用亚洲金属网，主业要求的**」

**硬规则**：闻喜镁锭（Wenxi_MG）**只从亚洲金属网抓取，不走 SMM 备源**。如果亚洲金属网未登录 / 未抓取到，**标黄不写**（不降级到 SMM）。

**反例（6/29 修前）**：
```python
elif source == "ASIANMETAL":
    # 亚洲金属网优先，降级 SMM  ← 这个降级逻辑要删
    price = asianmetal.get(variety)
    if price is None:
        price = smm.get(variety)  # ❌ 不要降级到 SMM
```

**正例（6/29 修后）**：
```python
elif source == "ASIANMETAL":
    # 6/29 主人拍板：闻喜镁锭必须用亚洲金属网，不走 SMM 备源
    price = asianmetal.get(variety)
    if price is None:
        # 标黄不写（不降级到 SMM）
        cell.fill = YELLOW_FILL
        reason = f"{date_str}: {variety} - 亚洲金属网未获取（主业要求用亚洲金属网，标黄不写）"
```

---

## 🚧 已知限制 / 待优化

### 暂时性限制
1. **钨粉当日 15:00 抓不到**（中钨在线发文晚，栏目页还没刷新）。**应对**：放**次日上午**抓取
2. **电解锰正则偶发失败**（ccmn 页面布局变化时）。已用 AJAX 端点替代，无此问题
3. **Chrome CDP 不稳定**（调试 Chrome 关闭后需重启，详见「故障处置手册」）

### 未来自动化方向
1. **每日 15:00 触发**：由平台定时任务跑 `daily_update_all.py`，自动执行
2. **登录态持续保持**：把 SMM/亚洲金属网登录态作为「主人日常」流程，每日开机自动登录
3. ~~**登录态自动重试**~~：✅ 已实现——抓取脚本内置自动重登（`fetcher_smm.py`）
4. **邮件/Slack 通知**：填表完成后自动发主人日报

### 历史回溯限制
- SMM 只提供当日实时价，**无法回溯历史日期**
- ccmn AJAX 可按 `publishDate` 回溯历史（已支持）
- 亚洲金属网文章按日期归档，可回溯
- akshare `futures_foreign_hist` 可回溯

---

## 📜 关键经验（踩坑教训）

### ✅ 经验
1. **多页抓取 → 找 AJAX 端点**（ccmn 首页 vs cjxh.shtml vs AJAX 端点）
2. **登录态 → 内置自动重登**（`fetcher_smm.py` 检测零结果即自动登录，无需人工）
3. **价格区间 → 中位值法**（所有 fetcher 都用 `_parse_price_range`）
4. **多数据源对比**（akshare vs 英为财情 WTI = 69.83 vs 69.86 几乎一致）
5. **黄底蓝字标注替代数据**（保证数据来源可追溯）

### ⚠️ 教训
1. **先查 AJAX 端点再写正则**（ccmn 首页正则不稳，AJAX 端点稳定 36 品种一次性）
2. **登录态过期被踢回首页**（URL 变成 `index.shtml?s=1&r=/...` 是关键标志）
3. **SMM 「未登录」占位**（表格行显示「未登录」不是空，是已登录失败）
4. **日期列当价格抓**（06-25 这种 5-6 位连续数字可能误判为价格）
5. **WTI 要「下午 3 点时点价」而非日 K 收盘**（akshare `realtime` 才对，`hist` 收盘价是次日 4:00 数据）

---

## 📚 相关笔记

- [[工作/大宗原材料监控/13-2026-06-25 625最终状态]] — 6/25 试跑总结
- [[工作/大宗原材料监控/10-2026-06-25 亚洲金属网接入与625查询清单]]
- [[工作/大宗原材料监控/11-2026-06-25 625首轮试跑报告]]
- [[工作/大宗原材料监控/12-2026-06-25 625第二轮回填方案]]
- [[工作/大宗原材料监控/14-精工大宗价格监控-项目主页与流程总结]] — 项目主页
- [[工作/大宗原材料监控/09-2026-06-25 CDP突破与全表覆盖]]

---

# 📎 附录 A：接口契约表（Col N ↔ 品种 ↔ fetcher ↔ 异常处理）

> **用途**：别的 AI 拿 SKILL 接活时，对着这张表能直接知道「Col N 该填什么 / 用哪个 fetcher / 抓失败怎么办」

## A.1 Excel 填表映射（Sheet「日均价（2026年市场）」）

| Col | 品种名 | 单位 | fetcher | 登录态 | 异常 fallback |
|:--:|------|:--:|------|:--:|------|
| 2 | 上海有色 ADC12 | 元/吨 | `fetcher_smm.fetch_AlSi_alloy('ADC12')` | 需登录 | 标黄 + 备注「SMM 未登录」 |
| 3 | 上海有色 A380 | 元/吨 | `fetcher_smm.fetch_AlSi_alloy('A380')` | 需登录 | 标黄 + 备注「SMM 未登录」 |
| 4 | 上海有色 AlSi9Cu3 | 元/吨 | `fetcher_smm.fetch_AlSi_alloy('AlSi9Cu3')` | 需登录 | 标黄 + 备注「SMM 未登录」 |
| 5 | 上海有色 A356 | 元/吨 | `fetcher_smm.fetch_AlSi_alloy('A356')` | 需登录 | 标黄 + 备注「SMM 未登录」 |
| 6 | 长江现货 A00 铝 | 元/吨 | `fetcher_ccmn.fetch('A00_AL')` | 公开 | 重试 3 次；3 次仍败标黄 + 「ccmn AJAX 失败」 |
| 7 | 长江现货 1# 铜 | 元/吨 | `fetcher_ccmn.fetch('CU')` | 公开 | 同上 |
| 8 | 长江现货 金属硅中间价441 | 元/吨 | `fetcher_ccmn.fetch('SI_553_331_AVG')` | 公开 | **取值：`金属硅553#-331#` 的 avgPrice**（不是 441# 硅均价）|
| 9 | 长江现货 金属硅中间价3303 | 元/吨 | `fetcher_ccmn.fetch('SI_3303_2202_MIN')` | 公开 | **取值：`金属硅3303#-2202#` 的 minPrice**（不是 3303# 硅均价）|
| 10 | 长江现货 1# 镁 | 元/吨 | `fetcher_ccmn.fetch('MG')` | 公开 | 同上 |
| 11 | 长江现货 1# 电解锰 | 元/吨 | `fetcher_ccmn.fetch('MN')` | 公开 | 同上 |
| 12 | 长江现货 金属硅中间价331 | 元/吨 | `fetcher_ccmn.fetch('SI_553_331_MAX')` | 公开 | **取值：`金属硅553#-331#` 的 maxPrice**（不是 553# 硅均价）|
| 13 | 亚洲金属网 闻喜镁锭 99.9%min | 元/吨 | `fetcher_asianmetal.fetch('闻喜+镁锭+99.9')` | 需登录 | 标黄 + 「亚洲金属网 未登录」 |
| 14 | 上海有色 AM60B | 元/吨 | `fetcher_smm.fetch_magnesium('AM60B')` | 需登录 | 标黄 + 备注「SMM 未登录」 |
| 15 | 上海有色 AZ91D | 元/吨 | `fetcher_smm.fetch_magnesium('AZ91D')` | 需登录 | 标黄 + 备注「SMM 未登录」 |
| 16 | 中钨在线 钨粉 | 元/千克 | `fetcher_tungsten.fetch()` | 公开 | **保留空 + 备注「中钨在线未发或发得晚」**，隔日重抓 |
| 17 | 英为财情 WTI 原油 | 美元/桶 | `fetcher_akshare.fetch_WTI()` | 公开 | 重试 3 次；仍败标黄 + 「akshare realtime 超时」 |

**Date 列 (Col 1)**：手动 `datetime(YYYY, M, D)` 写入（不是 fetcher 负责的）。

## A.2 fetcher 函数签名规范

```python
class BaseFetcher:
    def fetch(self, target_date: Optional[str] = None) -> dict[str, float]:
        """返回 {variety_id: price} 字典
        失败时调用 self._raise(error_msg) 不返回
        """
        ...

    def health_check(self) -> bool:
        """快速可达性检查（不依赖登录态）"""
        ...
```

**关键约定**：
- **返回 None ≠ 失败**（仅代表该品种没数据）；失败是 raise `FetchError`
- **价格区间** 都走 `self._parse_price_range(raw)`，不在 fetcher 内自己解析
- **黄底标注重试机制**：重试 3 次间隔 5s；3 次仍败才标黄

---

# 📎 附录 B：故障处置手册（按症状查）

> **用途**：现场抓取报错时，**对症状找处置**。不要从头 debug。

## B.1 浏览器 / Playwright 问题

| 症状 | 根因 | 处置 |
|------|------|------|
| Playwright 启动异常 / Node 相关报错 | 沙箱注入了 `NODE_OPTIONS` | **跑前 `unset NODE_OPTIONS`** |
| `FileExistsError: [Errno 17] EEXIST`，且报错**伪装成「CF 拦截 3 次失败」** | `PROFILE_DIR.parent.mkdir(exist_ok=True)` 在受限环境抛 `EEXIST` | 所有 Playwright 环节一律「不存在才 mkdir」+ `OSError` 容错 |
| `Page.navigate: net::ERR_ABORTED` | 页面未加载完被抢 | `wait_for_load_state(timeout=15000)` |
| 连上但找不到元素 | SPA 路由跳转中 | `wait_for_selector(selector, timeout=10000)` |
| 超时 | 网络慢或页面 JS 大 | 加 `timeout=60000` |
| **读到空文本 → 被判定「未登录」** | SSR 慢，不是真的掉登录 | **不要急着重导 cookie**：按品种正则轮询就绪 + 外层超时 260s |

```bash
unset NODE_OPTIONS          # 每次跑 Playwright 前
```

> ⚠️ 旧的「Chrome 9223 调试 profile」方案**已废弃**，不要再按它排障。现统一用 **Playwright + `cookies/` 持久化登录态**（SMM / 亚洲金属网 / 卓创 / 隆众）。

## B.2 SMM 未登录

| 症状 | 根因 | 处置 |
|------|------|------|
| 表格行显示「未登录」 | 登录态过期 | 抓取脚本自动重登（`fetcher_smm.py`）；若仍失败，检查 `.env` 凭据 |
| SMM 页跳转 `https://account.smm.cn/...` | 同上 | 同上 |
| **12 个键全空** | ⚠️ **常是误判**——SSR 慢读到空文本 | **先跑 `refetch_smm_fill.py` 定向补抓**，不要急着重导 cookie |

**手动重登**（仅在自动重登连续失败时）：
1. Playwright 打开 `https://hq.smm.cn/aluminum`，未登录会跳 `https://account.smm.cn/...`
2. 输入账号密码（见附录 C）
3. ⚠️ 点 `#user_account_password_login_button` 之后**还须再点** `button:has-text('同意并登录')`——只点第一下不算登录
4. cookies 落到 `data/smm_cookies.json`

## B.3 ccmn AJAX 失败

| 症状 | 根因 | 处置 |
|------|------|------|
| `JSONDecodeError` | 端点被改或返回 HTML | `curl -X POST ... ` 手动验证，看返回是 JSON 还是 HTML |
| 502 / 504 | ccmn 服务器临时挂 | 重试 3 次（间隔 10s）；3 次仍败标黄 |
| 36 品种全空 | 端点 marketVmid 失效 | 查 JS：F12 抓 `getCorpStmarketPriceList` 最新 marketVmid |

**手动验证命令**：
```bash
curl -X POST "https://www.ccmn.cn/shop/historyData/getCorpStmarketPriceList" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "Referer: https://www.ccmn.cn/cjxh.shtml" \
  -H "X-Requested-With: XMLHttpRequest" \
  -d "marketVmid=40288092327140f601327141c0560001&publishDate=2026-06-25&flag=1&productVmid=" \
  | python3 -m json.tool | head -20
```

## B.4 亚洲金属网未登录

| 症状 | 根因 | 处置 |
|------|------|------|
| 文章页跳 `https://www.asianmetal.cn/login` | 登录态过期 | 手动重登（下） |
| `302 Found` 重定向到 login | 同上 | 同上 |

**手动重登**：走**顶部弹窗**，字段 `cnopenloginname` / `cnopenloginpwd` / `openloginbutn`。
已登录时页面显示「账号在线中」，此时点 `#outlinebutn` 继续，不要再输密码。

## B.5 中钨在线（钨粉）

> 报价表**已图片化**（`tungsten-price-YYYYMMDD.jpg`），HTML 里没有文本价格。**旧的「抓文章正文正则」方案已失效，不要再用**。

| 症状 | 根因 | 处置 |
|------|------|------|
| `WRONG_VERSION_NUMBER` | 用 HTTPS（应为 HTTP） | 改 `http://` |
| OCR 结果离谱（如 26.0，历史区间 ~920–925） | 裁剪高度差 1px 即全盘乱码 | 必须走**多窗口扫描 + 投票**，不要单窗裁剪 |
| 抓不到 / 全乱码 | 当日图未发或站点限流 | 当日留空；`>20 次/分` 会 Connection refused，需降频 |
| 需要人工兜底 | — | `manual_fill_tungsten.py <价格>` |

**OCR 参数**（`_extract_w_from_image()`）：y 0.42~0.56 步进 0.01 × 窗高 0.055/0.06/0.065 × 微扰 ±2 → 放大 3 倍 → 二值化 → tesseract(chi_sim+eng)。
锚点 `2-10…[muμm]`，取价区间 200–5000；同值 ≥2 票才采用，否则取最靠上单票；含「碳化」的窗口排除。

> ⚠️ 临时 PNG 放 `jinggong_monitor/`（`/tmp` 受限）。**勿删 tesseract**。
> 历史上还踩过两个坑，已修：① `_find_candidate_article_urls` 未去重导致真报价文被挤出；② `_PRICE_PATTERNS["W"]` 含钨精矿/APT 兜底正则，把「万元/吨」当钨粉（差 35 倍）。**现在 W 只认报价表 OCR 值。**

## B.6 akshare WTI 失败

| 症状 | 根因 | 处置 |
|------|------|------|
| `ak.futures_foreign_commodity_realtime('CL')` 超时 | 网络或英为财情 API 限流 | 重试 3 次；3 次仍败用 `ak.futures_foreign_hist(symbol='CL')` 取最后一行收盘价 |
| 返回空 DataFrame | 同上 | 同上 |
| 数据滞后 1 天 | realtime 限流，fallback 到 hist | 在备注里写「15:00 实时价，超时用收盘价兜底」 |

---

# 📎 附录 C：入口密码本（账号 / 路径 / 端口）

> **用途**：别的 AI 拿 SKILL 接手时，**不用问主人就能找到所需环境**。

## C.1 账号信息

| 服务 | 账号 | 密码 | 用途 |
|------|------|------|------|
| SMM（上海有色）| 见 `.env` | 见 `.env` | SMM 登录态（7 品种价格）|
| 亚洲金属网 | 见 `.env` | 见 `.env` | 亚洲金属网登录态（闻喜镁锭）|
| 中钨在线 | 公开 | 公开 | **无需登录** |
| 长江有色 ccmn | 公开 | 公开 | **无需登录** |
| 英为财情 / akshare | 公开 | 公开 | **无需登录** |

> ⚠️ **SMM 和亚洲金属网密码已移至 `.env` 文件**（不入 git）。
> 首次使用请 `cp .env.example .env` 并填入凭据。
> 代码中不保留任何明文密码，统一通过 `jinggong_monitor.credentials` 模块读取。

## C.2 关键路径

```
/Users/siqi/Desktop/AI/jinggong-commodity-monitor/   ← 项目根
├── SKILL.md                                          ← 本文件
├── daily_update_all.py                               ← 15:00 主抓（当前主入口）
├── daily_update_all.py                               ← 每日 3PM 全品种抓取主入口
├── daily_check_missed.py                             ← 17:00 补抓
├── 2026年有色金属市场价格.xlsx                        ← 唯一数据源 Excel
├── jinggong_monitor/                                 ← 代码目录
│   ├── base.py                                       ← BaseFetcher
│   ├── orchestrator.py                               ← 调度
│   ├── fetcher_akshare.py                            ← WTI
│   ├── fetcher_ccmn.py                               ← ccmn 7 项 ⭐
│   ├── fetcher_smm.py                                ← SMM 6 项
│   ├── fetcher_asianmetal.py                         ← 亚洲金属网 1 项
│   └── fetcher_tungsten.py                           ← 中钨在线 1 项
├── config/
│   ├── varieties.yaml                                ← 品种-数据源
│   └── sources.yaml                                  ← 数据源配置
├── data/                                             ← 输出
└── output/                                           ← 历史日报

/Users/siqi/chrome-debug-profile/                     ← Chrome 调试 profile（保留登录态）
/Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/python3  ← venv Python
```

## C.3 端口 & 服务

| 端口 | 服务 | 启动命令 |
|:--:|------|------|
| 9223 | Chrome 调试模式 | `open -na "Google Chrome" --args --remote-debugging-port=9223 --user-data-dir=/Users/siqi/chrome-debug-profile` |
| 8787 | 启信宝 qixin_server | `cd ~/.openclaw/workspace/qixin_tool && python3 qixin_server.py`（**本项目不用**）|

## C.4 环境变量

```bash
# 必设：避免 GitHub 加速器拦截国内站点
export NO_PROXY="sci99.com,chinatungsten.com,51bxg.com,steelcn.cn,ccmn.cn,cnfeol.com,ctia.com.cn,smm.cn,asianmetal.cn,hq.smm.cn,${NO_PROXY}"
export no_proxy="$NO_PROXY"
```

**为什么不硬编码到代码里** — 防止代码换机器跑时环境变量缺失导致无网络。主人按需塞 `~/.zshrc`。

### 🔴 git push 被代理变量拦截（2026-09-17 定位根因）

WorkBuddy 沙箱会注入**透明代理环境变量** `HTTP_PROXY` / `HTTPS_PROXY` / `http_proxy` / `https_proxy`（指向内部代理，如 `127.0.0.1:57474`）。

`git push` 会**继承**这些变量，而 `-c http.proxy=`（空值）**覆盖不掉环境变量**，表现为：

```
fatal: unable to access '…': Empty reply from server
fatal: … Operation too slow. Less than 10 bytes/sec transferred the last 45 seconds
fatal: Failed to connect to github.com port 443 after 75002 ms
```

**两个条件缺一不可** —— ① 清代理，② 重试（**清代理 ≠ 能推成功**）：

```bash
# ① 清变量；② 循环重试（直连 GitHub 是间歇性的，实测 8 次里第 2 次才成功）
for i in 1 2 3 4 5 6; do
  env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy \
    git -c http.lowSpeedLimit=10 -c http.lowSpeedTime=45 push origin main && break
  sleep 4
done
```

诊断当前是否可达：

```bash
curl --noproxy '*' -o /dev/null -w "%{http_code}\n" \
  https://github.com/<owner>/<repo>.git/info/refs?service=git-receive-pack   # 000 = 不可达，等窗口
```

✅ **已根治**：`git_helper.py` 三处已修 —— `_detect_proxy()` 不再盲信环境变量（任何代理都必须 `_probe()` 实测能通 GitHub 才采用）、`_git_env()` 先清代理变量（不分大小写）、`git_push()` 自动重试 6 次。**走该模块的定时任务无需再手工处理。**

⚠️ 此前记录的「可用路径每日翻转」**已作废** —— 真正的变量是①沙箱代理变量干扰 + ②直连本身间歇，与"路径"无关。收尾仍须核 `git rev-list --left-right --count HEAD...origin/main` 为 `0 0`。

## C.5 Python 依赖

```
akshare>=1.12.0
openpyxl>=3.1.0
playwright>=1.40.0
requests>=2.31.0
beautifulsoup4>=4.12.0
pyyaml>=6.0
```

安装命令：
```bash
/Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/pip install -r requirements.txt
# 首次运行 playwright 还要：
/Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/playwright install chromium
```

---

# 📎 附录 D：项目现状与接手指引（2026-09-17 更新）

## D.1 当前自动化程度

| 数据源 | 自动化 | 限制 |
|------|:--:|------|
| ccmn AJAX（7 项） | ✅ 100% | 公开，端点稳定 |
| akshare WTI | ✅ 100% | 实时 API 偶发超时 |
| LME 官网（1 项） | ✅ 100% | 次日 09:00 按官方数据日回填 |
| SMM（9 项） | ✅ 接近全自动 | cookies 复用；仅 cookie 真失效时才需重登 |
| 亚洲金属网（1 项） | ✅ 接近全自动 | 同上；失败由 SMM Wenxi_MG 兜底 |
| 卓创（6 项） | 🟡 半自动 | 有滑块验证，**cookie 过期需人工重导** |
| 中钨在线（1 项） | 🟡 半自动 | 报价表图片化，OCR 多窗口投票；失败可人工兜底 |

**结论**：26 项中 25 项可无人值守，卓创与中钨在线偶需人工介入。

## D.2 接手须知

1. **先读**：「🎯 一句话总览」→「附录 A 接口契约表」
2. **遇故障**：不 debug，直接查「附录 B 故障处置手册」按症状定位
3. **缺环境信息**：查「附录 C 入口密码本」
4. **要了解业务背景与三板块全貌**：读 Obsidian `raw/工作/大宗原材料监控/`（总览 + `章节/` + `板块/`）

**复用前提**：
- venv：`~/.workbuddy/binaries/python/envs/jinggong/`
- 登录态：`cookies/`（SMM / 亚洲金属网 / 卓创 / 隆众），全部 gitignore
- 跑 Playwright 前必须 `unset NODE_OPTIONS`

> ⚠️ **旧版附录 D（截至 2026-06-26）已删除**，其中的 P0/P1/P2 待办均已完结或作废：
> fetcher_tungsten 已重写、主流程已拆为独立 fetcher + orchestrator、定时任务已迁移到平台自动化、登录态已自动重试。
> 另：旧「Chrome 9223 调试 profile」这条依赖已废弃，现统一用 Playwright + cookies。

---

## 附录 E. 塑料/橡胶模块（2026-09-17 补充，此前 SKILL 未覆盖）

> 本节补记项目自 2026-06 起新增、但一直未写入本 SKILL 的「塑料/橡胶」支线。原正文「16 品种」描述已过时——
> 有色金属主线现为 **26 品种 × 7 源**，另有独立看板 `docs/plastic/`。

### E.1 现有资产

| 文件 | 作用 |
|---|---|
| `jinggong_monitor/fetcher_21cp.py` | 中塑在线（`intl.21cp.com`）牌号级行情；`TARGETS` 为抓取清单 |
| `jinggong_monitor/daily_plastic.py` | 工作日 15:30 增量抓 13 牌号 → 追加 `docs/plastic/data.json`（幂等） |
| `jinggong_monitor/backfill_plastic.py` | 历史回填；`--only <KEY>` 增量合并单牌号（约 40s vs 全量 10+min）|
| `docs/plastic/data.json` | `{日期:{牌号:价}}` 内层为 dict 非数组；`total_days`/`last_updated` 在顶层 |
| `docs/plastic/index.html` | **诺博内外饰**看板（13 牌号）。Chart.js；**CATEGORIES / VARIETY_NAMES / UNITS / SOURCES / COLORS 全部硬编码，不读 data.json**。但 `allCodes` 由 `CATEGORIES.flatMap()` 动态派生 → **只需改常量，KPI 卡/多选器/下拉框自动跟随** |
| `docs/rubber/index.html` | **诺博橡胶**看板（21 项）。由 plastic 页复制而来，差异仅：标题、`CATEGORIES`(8 组 21 项)、`KPI_KEY_CODES`、`VARIETY_UNITS`(原油=美元/桶)、数据路径 `../plastic/data.json`。**已接入 `../board-analysis.js` 分组分析模块**（在 `renderAll()` 末尾调 `renderAnalysis()`；分析卡插在「日维度」之后、「月维度」之前） |
| `docs/board-analysis.js` | **分组分析模块（周报形态）**，复刻自诺博橡胶 Excel「原材料价格走势-周报」。入口 `BoardAnalysis.render({containerId,categories,data,names,units,sources,markets,colors,defaultUnit})`。每组渲染折线图＋统计表＋自动摘要＋覆盖说明。⚠️ **画布 ID 必须用分组下标**——分组名全是中文，做正则转义后会全塌成 `_` 而互相撞车（Chart.js 会报 "Canvas is already in use"）。⚠️ `renderAll()` 里的 `destroyCharts()` 会销毁**全部** Chart 实例，所以必须由 `renderAll()` 末尾重建，不能只在 DOMContentLoaded 里渲染一次 |
| `jinggong_monitor/bridge_jinggong.py` | 精工→诺博**数据接续**（原油每日；`--history` 借 SMM 铝历史）。**只接同源同口径**，默认幂等只补空 |
| `jinggong_monitor/daily_plastic_ext.py` | 工作日 15:40 增量抓**扩品类 20 项**（SMM 铝 4 / 百川煤焦油 1 / 隆众 15）→ 写同一 data.json，末尾自动调 `bridge_jinggong.sync()` 接上原油。⚠️ **必须与 daily_plastic.py 错开运行**（同文件并写会互相覆盖） |
| `jinggong_monitor/lz_price_center.py` | 隆众 `dc.oilchem.net` 结构化价格库封装（cookie 直连），详见 E.2 |
| `jinggong_monitor/backfill_plastic_ext.py` | 扩品类**历史回填**（隆众 15 项，走 `getSingleCurve` 曲线接口）。`--from 2025-09-17 [--to] [--only KEY] [--dry-run] [--refresh]`；默认幂等只补空缺。**长历史用 `--from 2020-07-01`**（2026-09-17 实测隆众能回溯到该日，6950C 拿到 1468 点；这是「较2025/2024/…/2020年均价涨幅」几行的数据基础，只用一年数据这几行会空掉）。SMM 铝 4 项 / 百川煤焦油 1 项源站无免费历史，**不在范围**（铝改由 `bridge_jinggong --history` 借精工同源历史）|
| `jinggong_monitor/fetcher_baiinfo.py` | 百川盈孚煤焦油抓取（免登录 SSR） |

- **data.json 现共 34 品种 = 塑料 13 + 扩品类 20 + 原油 1**（2026-09-17 扩充并上线），**1552 个交易日（2020-07-01 ~ 2026-09-17）**。塑料 13（PC×3、ABS×3、PP×5、POE×1、PA6×1）口径＝余姚中国塑料城市场参考价（元/吨），受源站**滚动一年窗口**限制只能回溯到 2025-09-17；扩品类 20 的源与口径见 E.2。
- ⚠️ **`backfill_plastic.py` 不带 `--only` ＝ 全量重建，会覆盖 data.json**，并丢失：① 隆众 15 项 2020 起的长历史 ② 桥接的 WTI/A380/AlSi9Cu3 ③ 百川煤焦油。补救顺序：`backfill_plastic_ext --from 2020-07-01` → `bridge_jinggong --history`。**日常更新只用 `daily_plastic.py` / `daily_plastic_ext.py`（按日期 merge、幂等、安全）。**
- **两页拆分（2026-09-17）**：`docs/plastic/`＝内外饰（13 牌号，4 组）；`docs/rubber/`＝橡胶（21 项，8 组）。**共用 data.json**。⚠️ 前端 KPI 的「今日更新品种」「月均价环比」必须按**本页** `CATEGORIES` 过滤——data.json 是共用的，不过滤会把对方品种算进来（曾出现「33 / 21」这种计数）。
- 反爬：全站 SafeLine WAF，普通 UA 一律 468；**Googlebot UA 对 `/market/detail/` 放行**，须低频（每日 1 次、间隔 ≥2s）。
- ⚠️ 同名陷阱：`K8003` 同名牌号极多，必须用 `dushanzi`/`独山子` 过滤。
- ⚠️ 中塑对**部分牌号发布不同步**，同一天可能出现多个日期，属正常，勿强行拉平。

### E.2 扩品类时的源可行性（2026-09-17 实测，供下次直接复用）

| 源 | 结论 | 关键要点 |
|---|---|---|
| **SMM `hq.smm.cn/aluminum`** | ✅ 免新账号 | 复用 `data/smm_cookies.json`。页面另含 **A00铝 / ZLD104铝合金**（`fetch_smm` 现仅取 A380/AlSi9Cu3/ADC12/A356）。匹配「低碳ZLD104铝合金」需防误命中。<br>　⚠️ **现货历史不可免费取**（2026-09-17 实测）：hq 页 XHR 只有**期货**行情（`platform.smm.cn/quotecenter/...`），现货价是**当日 SSR 文本**（所以只能靠页面解析）；历史在独立站 `history.smm.cn`（入口 `price.smm.cn`），接口 `{base}/v31/settlement/history/categories` 与 `/v31/settlement/history/prices_excel`（POST，参数 `token/product_ids/start_date/end_date`）**需 token 且受「权限时长」限制**，页面元素标 `premium` / `--guest` / `--no-permission`。→ **结论：SMM 铝 4 项无法回填历史**。 |
| **百川盈孚 `baiinfo.com`** | ✅ 免登录 | 品种页如 `/meijiaohua/gaowenmeijiaoyou`。价格是 SSR 内嵌的**「百川盈孚提示」句**：`YYYY年M月D日，<品种>市场均价 NNNN元/吨，相较于上一工作日上调/下调 N 元/吨`。同页另有 CCTX 指数。<br>　⚠️ **无免费历史序列**（2026-09-17 实测）：品种页的 Nuxt payload 只含**当日提示句 + 新闻列表**（页面里那些 `2026-07-xx` 日期出自新闻标题，**不是价格序列**），历史价格需会员。→ **结论：高温煤焦油无法回填历史**。 |
| **隆众资讯** | ✅ **已验证可抓**（2026-09-17 实登实测，13 牌号全取到真实价） | ⚠️ 分两层，别只测一层就下结论：<br>① **文章正文**（`www.oilchem.net/xx-xxxx-…html`）＝会员墙，正文被整体替换为「注册为会员可获得相关产品 15 天的免费浏览权…400-658-1688」，`元/吨` 命中 0（9/9 抽样：日评/周评/月评/早间提示/价格一览表）。标题/发布时间仍公开。<br>② **结构化价格库**（`dc.oilchem.net/page/`）＝真正的入口。`POST https://dc.oilchem.net/ndc/price/list/queryPricePage`，body `{"varietiesId":<id>,"businessType":"2\|3\|4","twoLevelBusinessType":<int>,"timeType":0,"pageNum":1,"pageSize":100}`，头需 `Referer: https://dc.oilchem.net/page/`+`Origin`+`Content-Type: application/json`。<br>　⚠️ `twoLevelBusinessType` 必须是**数字** `0`（字符串校验不过）；⚠️ **pageSize 上限 100**，超限报「pageSize数值超限」且**静默无行**（易误判无数据）。<br>　**登录门槛在后端数据层**：未登录也返 200 + 完整行结构（行=市场+规格，列=日期），但价格值被替换为 `"请登录"`，并带 `pricePowerBO={see:false}` → **登录后服务端自动回填真实价，解析代码无需改**。<br>　`businessType`：2=企业价 3=市场价 4=国际价。原油(110)无市场价只能走 bt=4（tlbt 22=期货/23=国际市场/27=现货/28=远期现货）。<br>　品种 id：原油110、乙烯196、丙烯116、高温煤焦油133、炭黑242、**干胶259（＝天然橡胶，库里不叫"天然橡胶"）**、顺丁267、丁苯266、防老剂282、促进剂281、三元乙丙275。<br>　登录＝`POST passport.oilchem.net/member/login/`（password 前端 MD5）+ 网易易盾 → 走**人工登录 + 持久化 profile**（同 `cookies/lme_official_profile`，已稳定 9 天）。<br>　封装模块：`jinggong_monitor/lz_price_center.py`（`VARIETY_MAP`；cookie 直连为默认路径，Playwright 降为回退）、`lz_login_setup.py`（自动填表+提交+验证码检测+权限体检）。<br>　**登录实测（2026-09-17）**：全自动登录**未触发网易易盾**，一次通过。cookie 落 `cookies/lz.json`（`.gitignore:56` 已忽略，**严禁入 git**）；核心 `_member_user_tonken_` **有效期约 30 天**，到期需重登。取数**不必启动浏览器**——urllib 带 Cookie 头即可，11 品种全通。<br>　🔴 **权限是「分品种」的，不是账号级开关**——同一账号实测 `see=true`：乙烯/丙烯/炭黑/**干胶(天胶)**/顺丁/丁苯/防老剂/促进剂/三元乙丙；`see=false`：柴油/原油/高温煤焦油。<br>　**三态判据（排障必用）**：价格值＝`"请登录"` → 匿名；＝`"无权限"` → 登录有效但该品种无订阅；＝真实数值 且 `see=true` → 正常。**判定账号权限必须逐品种扫，单点外推会得出错误结论**（曾只测柴油差点误判整账号无权限）。<br>　⚠️ 牌号匹配必须**精确**：促进剂同 vid(281) 下 DM/M/TMTD 混排，包含匹配时 `M` 会误命中 TMTD 与 DM；丁苯需兼容 `1712`/`SBR1712` 两种写法。<br>　⚠️ **取价格式：一个日期的 `price` 字典有三种形态**（2026-09-17 实测，`pick_price()` 已按优先级处理）——① 只有 `主流价`（乙烯/SCRWF/RSS3）；② 只有 `最低价`+`最高价`（丙烯/炭黑N550/促进剂/防老剂）；③ 三键齐全（顺丁/丁苯/三元乙丙）。**必须显式按 `主流价 > 最低价 > 最高价` 取值**：早期实现按 dict 首键取，遇到第③类会取到**区间下沿**（顺丁取 15300 而主流价是 15400，EPDM 13561C 取 25800 而主流价 26000）。**区间型品种（第②类）列表接口只给最低/最高价**，但**曲线接口给官方 `middlePrice`**（丙烯山东 09-17＝9785＝区间中值、炭黑 N550＝12000）→ 看板一律以 `middlePrice` 为准。<br>　⚠️ **隆众当日价在盘中被修订**：同一交易日不同时点取值可能不同（实测丙烯山东 09-17 早间 9800 → 午后 9750/9820）。看板默认**不覆盖**已有日期（幂等），要刷成最新口径须显式 `--refresh`。<br>　✅ **历史可回溯（2026-09-17 实测）**：`queryPricePage` 的日期列**固定 5 个**（以 `queryEndDate` 为锚向前取；`pageNum>1` 报 `A0425 未查询到指标`，**不可翻页**）→ 只能取最新一期。要历史必须换 **`POST /ndc/price/curve/getSingleCurve`**：body `{"businessId":<行id>,"businessType":3,"twoLevelBusinessType":0,"indexPriceType":0,"timeType":0,"queryStartDate":"2026-07-01","queryEndDate":"2026-09-17"}` → 返回 `priceDataList` **整段日序列**（每条带 `lowPrice/highPrice/**middlePrice**`）。`businessId`＝「品种×市场×规格」行 id，用 `queryPricePage` 枚举行取得（`resolve_business_row()` 按 specs/markets/strict 口径选行）。<br>　　封装：`fetch_curve_raw()/curve_series()/resolve_business_row()/fetch_variety_curve()`；回填脚本 `jinggong_monitor/backfill_plastic_ext.py --from 2026-07-01 [--refresh]`。实测 15 品种各 **57 个交易日**（7/1~9/17）一次拿全。`timeType`：0/2=日 1=周 3=月 4=季 5=年。权限侧 `pricePowerBO.powerStartTime`＝2020-07-01（`status:9` 只是「订阅起始日」标记，**不是无权限**，别据此误判）。<br>　⚠️ 同一牌号多地区报价语义有差异（如 SCRWF 昆明 18100 / 上海 18450 / 山东 18250），取值口径由 `VARIETY_MAP[*]["markets"]` 决定，实际取值市场回写在 `source` 字段。<br>　**`strict` 语义（2026-09-17 新增）**：`strict=True` = 只在 `markets` 内取，取不到即留空，**绝不跨市场兜底**。理由：否则指定市场缺报时会静默滑到别处，看板只显示数字、看不出市场已漂移 —— 比留空更危险。主人指定口径的 7 项用 True；未指定的（RSS3/顺丁/丁苯/防老剂/乙烯/EPDM）保持 False 以免整体断档。<br>　**主人指定口径（2026-09-17）**：SCRWF→**昆明**｜丙烯→**山东**（隆众无「华北」市场名，其「华北地区」只含河北/山西/天津，山东被单列「山东省」）｜炭黑 N550→**山东**｜促进剂 DM/CZ→**山东**（25,000/28,000）、M/TMTD→**衡水**（各 21,500；⚠️ 山东只有 D/DZ/NS/CZ/DM 五规格，**没有 M 和 TMTD**） |
| **同花顺 `10jqka.com.cn`** | ❌ 无外盘 | `goodsfu` 期货页为 JS 渲染 SPA + GBK 编码，HTML 内无任何外盘/布伦特字符串；`q.10jqka.com.cn/global/` 301；外盘接口 404 |
| **生意社 `www.100ppi.com`** | ⚠️ 可用但口径不同 | 首次响应含 JS 校验，读 `HW_CHECK=<md5>` 写入 cookie 后重取即 200。分品种页 `mprice/plist-1-<id>-1.html`：天胶56/顺丁371/丁苯930/炭黑398/防老剂2315/乙烯51/丙烯362/促进剂M=15657/TMTD=3555。**但"报价中心"＝企业贸易商挂牌价，非市场均价**；且**无三元乙丙** |

**替代路径（已验证）**
- 原油（布伦特）：`https://hq.sinajs.cn/list=hf_OIL,hf_CL`，需 `Referer: finance.sina.com.cn`，响应 GBK。实测 `hf_OIL=105.644`（布伦特）、`hf_CL=97.395`（纽约原油）。布伦特值与当日新闻披露的 105.60 吻合。⚠️ `hf_CL` 与项目 akshare WTI 存在差值，若启用需先交叉校验，勿直接混用。

**探针脚本**：`probe_smm_aluminum.py`（落盘 `data/smm_aluminum_probe.txt`）、`probe_lz_gate.py`（判定门槛标记 + 正文是否真含价格）、`probe_smm_price_history.py`（判 SMM 历史站权限与接口，2026-09-17）、`probe_dc_api.py`/`probe_dc_varieties.py`（隆众接口与品种枚举）。

---

# 📎 附录 F：工作记忆库结构（2026-09-17 建立）

**背景**：`.workbuddy/memory/MEMORY.md` 曾膨胀到 **13.9 千字**，**超出平台注入上限被静默截断**（截到「并发与事故」就断了）——即新会话里我看不到后半截内容却不自知。已做拆分。

## F.1 文件布局（`.workbuddy/memory/`）

| 文件 | 是否自动注入 | 内容 |
|---|---|---|
| `MEMORY.md` | ✅ **是**（唯一） | 只留每次都用得上的：铁律 / 数据源 / 推送 / 项目骨架速查 / 拆不拆结论。**约 6 千字** |
| `board-jinggong.md` | ❌ 否 | 中钨在线 OCR 参数、LME 铝回填、交易日历、Excel 与 changelog、并发事故规程 |
| `board-plastic.md` | ❌ 否 | 扩品类口径（昆明/山东/衡水）、隆众两条取数路径、13 牌号中塑 |
| `board-mand.md` | ❌ 否 | 曼德 13 品种 SPEC、fetcher 复用映射（`SMM_KEY_MAP` 坑） |
| `YYYY-MM-DD.md` | ❌ 否 | 按日工作日志，**只追加**；>30 天归纳进上述文件后删除 |

## F.2 铁律（写记忆时遵守）

1. **只有 `MEMORY.md` 会自动进上下文**——把内容挪到 `board-*.md` ＝ 以后不再自动出现在眼前，须主动 Read。所以：高频必用的留在 `MEMORY.md`，低频备查的才挪走。
2. **`MEMORY.md` 必须保持在注入上限内**（经验值 <8 千字安全）。新增知识优先写当日日志；确认有长期价值再考虑上移，且上移前先看是否该进 `board-*.md`。
3. **未决事项不得因整理而删除**（如 09-10/09-11/09-14 的 LME 待定值、调休补班日方案 A/B、炭黑 N550 九月初跳涨）。

## F.3 拆不拆独立项目（结论，2026-09-17）

**单仓库、单 Pages、单次推送。** 精工 / 塑料 / 曼德共享 `trading_calendar`、`git_helper`、fetcher、`export_excel_to_json`、Chart.js vendor：
- 拆仓库 → **推送故障面 ×3**（推送是本项目最高频故障）；SMM fetcher 内部键是精工命名 `A380`/`ADC12`、曼德靠 `SMM_KEY_MAP` 映射，拆库必然产生两份漂移。
- 现在已是**逻辑分家**：`docs/plastic/`（内外饰）、`docs/rubber/`（橡胶）、`docs/mand/` 独立子目录 + 独立前端常量 + 独立定时任务（15:30 / 15:35 / 15:40；**橡胶与内外饰共用同一份数据，不需要新定时任务**）。
  · **2026-09-17 新增「拆页面·共用数据」的实践**：客户方要分开看（诺博橡胶 vs 诺博内外饰），拆的是**页面**不是数据层——抓取 1 次、推送 1 次，故障面不增加；两个链接可分别发人。
- **唯一该拆的信号**：要给不同人不同权限（如曼德只给曼德同事看）——那时拆的是**发布通道**，不是代码。

**另**：第三方/客户提供的原始图表与报告统一放仓库根 `references/`（已加入 `.gitignore`），**严禁入 git**——含对方业务数据，与 `screenshots/`、`*.pdf`、`长城有色日价格查询/` 同属不外传一类。

## F.4 人类可读文档在哪（2026-09-17 建立）

本 SKILL.md 面向**排障与接口契约**（机器/AI 视角）。**业务与架构全貌**另有一份 Obsidian 文档：

```
Obsidian Vault/raw/工作/大宗原材料监控/
├── 大宗原材料监控-总览.md      ← MOC：三板块对照 + 数据流 + 双链索引
├── 章节/                       ← 跨板块通用内容
│   ├── 01-架构与数据流.md
│   ├── 02-通用组件.md          ← 交易日历 / git_helper / fetcher 复用矩阵（双链枢纽）
│   ├── 03-数据源与登录态.md
│   ├── 04-发布与推送.md
│   └── 05-运维与故障处置.md    ← 定时任务 ID / 故障表 / 并发规程
├── 板块/                       ← 各板块品种清单与口径
│   ├── 精工.md   诺博.md   曼德.md
├── 日报/                       ← 历史日报（6/10 ~ 8/11）
└── _archive/                   ← 旧项目笔记与早期设计稿
```

**三者分工**：SKILL.md ＝ 排障手册；Obsidian ＝ 架构与业务说明书；`.workbuddy/memory/` ＝ 我的工作记忆。

## F.5 废弃代码

已废弃的主流程（`fill_and_verify.py` / `excel_to_web.py` / `run.sh` / `setup_launchd.sh`）已移入 **`_legacy/`**，附有说明 `_legacy/README.md`。**不要依据它们排障**——launchd 方案已废弃且任务未加载。


