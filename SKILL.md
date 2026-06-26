---
name: 精工有色金属共享表自动化填写
description: 精工板块每日有色金属市场均价采集与Excel填写。覆盖16项品种，4类数据源(ccmn公开AJAX/SMM登录态/亚洲金属网登录态/akshare)。已验证6/25跑通16/16全填。流程标准化，每日15:00执行。
agent_created: true
version: 2.0
last_updated: 2026-06-25
---

# 精工有色金属共享表自动化填写

## 🎯 一句话总览

每天 15:00 自动抓 16 个品种价格填入 Excel。**ccmn + akshare 不需登录**，**SMM + 亚洲金属网需要主人在调试 Chrome 里保持登录态**。登录态过期时跑 `relogin_assistant.py` 自动引导主人重新登录。

## 📊 16 个品种 × 4 类数据源（6/25 跑通版）

| Col | 项目 | 数据源 | 抓取方式 | 登录态要求 |
|:--:|------|--------|--------|------|
| 2 | 上海有色 ADC12 | SMM | CDP 实测价格表 | **需登录** |
| 3 | 上海有色 A380 | SMM | CDP 实测价格表 | **需登录** |
| 4 | 上海有色 AlSi9Cu3 | SMM | CDP 实测价格表 | **需登录** |
| 5 | 上海有色 A356 | SMM | CDP 实测价格表 | **需登录** |
| 6 | 长江现货 A00 铝 | **ccmn AJAX** | requests POST | 公开 ✅ |
| 7 | 长江现货 铜 | **ccmn AJAX** | requests POST | 公开 ✅ |
| 8 | 长江现货 金属硅中间价441 | **ccmn AJAX** | `金属硅553#-331#` 的 **avgPrice**（非字面 441# 硅）| 公开 ✅ |
| 9 | 长江现货 金属硅中间价3303 | **ccmn AJAX** | `金属硅3303#-2202#` 的 **minPrice**（非字面 3303# 硅）| 公开 ✅ |
| 10 | 长江现货 镁 | **ccmn AJAX** | requests POST | 公开 ✅ |
| 11 | 长江现货 电解锰 | **ccmn AJAX** | requests POST | 公开 ✅ |
| 12 | 长江现货 金属硅中间价331 | **ccmn AJAX** | `金属硅553#-331#` 的 **maxPrice**（非字面 553# 硅）| 公开 ✅ |
| 13 | 亚洲金属网 闻喜镁锭 | 亚洲金属网 | CDP 文章抓取 | **需登录** |
| 14 | 上海有色 AM60B | SMM | CDP 实测价格表 | **需登录** |
| 15 | 上海有色 AZ91D | SMM | CDP 实测价格表 | **需登录** |
| 16 | 中钨在线 钨粉 | 中钨在线 | Playwright + 正则 | 公开 ✅ |
| 17 | 英为财情 WTI 原油 | akshare | `ak.futures_foreign_commodity_realtime('CL')` | 公开 ✅ |

**登录依赖统计**：8 项公开（ccmn 7 + akshare 1），8 项需登录（SMM 6 + 亚洲金属网 1 + 中钨在线 1）。

---

## 🐛 中钨在线"无新文"误判（6/26 主人纠正）

**错误认知**：之前以为 6/25 钨粉"无新文"是"作者没发"，保留空。

**真相**：文章是 6/25 发的，**只是发得晚**（下午晚些时候），15:00 抓取时还没挤进栏目页。6/26 早上再抓就有了（6/25 文章「钨价弱稳运行」钨粉 1200）。

**应对策略**：
- 钨粉抓取放在**次日上午**（不是当日 15:00）— 用前一日的文章填前一日 Row
- 或当日 15:00 抓空 → 次日 09:00 补抓 → 更新当日 Row
- 入口：`http://news.chinatungsten.com/cn/tungsten-product-news.html`（栏目页，**HTTP 不是 HTTPS**）
- 正则：`r'钨粉价格\s*(\d+)\s*元[／/]\s*千克'`

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

**本项目 Excel 文件（`2026年有色金属市场价格共享(2).xlsx`）一律用 openpyxl 一次性写入，禁止用 officecli 写入。**

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

### 每日 15:00 执行

```bash
cd ~/Desktop/AI/jinggong-commodity-monitor

# 1. 设置网络白名单（避免 GitHub 加速器拦截）
export NO_PROXY="sci99.com,chinatungsten.com,51bxg.com,steelcn.cn,ccmn.cn,cnfeol.com,ctia.com.cn,smm.cn,asianmetal.cn,hq.smm.cn,asianmetal.cn"

# 2. 启动 Chrome 调试模式（首次或被关闭时）
open -na "Google Chrome" --args --remote-debugging-port=9223 --user-data-dir=/Users/siqi/chrome-debug-profile

# 3. 检查调试 Chrome 是否有 SMM + 亚洲金属网登录态
PYTHONPATH=. /Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/python3 scripts/check_bsp_login.py

# 4. 跑主抓取流程
PYTHONPATH=. /Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/python3 fill_and_verify.py
```

### 登录态过期处理

如果检测到 SMM / 亚洲金属网未登录：

```bash
# 自动开登录页 + 轮询检测登录态
PYTHONPATH=. /Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/python3 relogin_assistant.py
```

脚本行为：
1. 自动开 SMM 登录页 → 主人在调试 Chrome 完成登录
2. 每 5 秒检测登录态（最长 5 分钟）
3. SMM 登录成功 → 自动开亚洲金属网登录页
4. 两个都登录后 → 自动跑 `fill_and_verify.py`

---

## 📁 项目文件结构

```
jinggong-commodity-monitor/
├── SKILL.md                          ← 本文件（流程定义）
├── fill_and_verify.py                ← 主流程（填 Sheet1 + Sheet2 + 历史核查）
├── relogin_assistant.py              ← 登录态修复助手
├── run.sh                            ← 一键运行脚本
├── 2026年有色金属市场价格共享(2).xlsx  ← Excel 数据源（每天更新）
├── jinggong_monitor/
│   ├── base.py                       ← BaseFetcher + _parse_price_range 价格解析
│   ├── orchestrator.py               ← 多源调度
│   ├── fetcher_akshare.py            ← akshare (WTI 实时)
│   ├── fetcher_ccmn.py               ← ccmn AJAX (长江现货 7 项) ⭐v2
│   ├── fetcher_smm.py                ← SMM (Col 2/3/4/5/14/15) ⭐6/25 新增
│   ├── fetcher_asianmetal.py         ← 亚洲金属网 (闻喜镁锭)
│   ├── fetcher_tungsten.py           ← 中钨在线 (钨粉)
│   └── ...
└── config/
    ├── varieties.yaml                ← 品种-数据源映射
    └── sources.yaml                  ← 数据源配置
```

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

## 🚧 已知限制 / 待优化

### 暂时性限制
1. **钨粉当日 15:00 抓不到**（中钨在线发文晚，栏目页还没刷新）。**应对**：放**次日上午**抓取
2. **电解锰正则偶发失败**（ccmn 页面布局变化时）。已用 AJAX 端点替代，无此问题
3. **Chrome CDP 不稳定**（调试 Chrome 关闭后需重启，详见「故障处置手册」）

### 未来自动化方向
1. **每日 cron 15:00 触发**：用 `openclaw cron` 加 `fill_and_verify.py`，自动跑
2. **登录态持续保持**：把 SMM/亚洲金属网登录态作为「主人日常」流程，每日开机自动登录
3. **登录态自动重试**：登录态过期时自动跑 `relogin_assistant.py` 引导主人重新登录
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
2. **登录态 → 引导助手**（relogin_assistant 自动开登录页 + 轮询）
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

## B.1 Chrome 调试浏览器问题

| 症状 | 根因 | 处置 |
|------|------|------|
| `connect ECONNREFUSED 127.0.0.1:9223` | 调试 Chrome 没开 | `open -na "Google Chrome" --args --remote-debugging-port=9223 --user-data-dir=/Users/siqi/chrome-debug-profile` |
| `Page.navigate: net::ERR_ABORTED` | 页面未完全加载被抢 | `await page.wait_for_load_state("networkidle", timeout=15000)` |
| CDP 连上但找不到元素 | 页面 SPA 路由跳转中 | `await page.wait_for_selector(selector, timeout=10000)` |
| CDP 超时 30s | 网络慢或页面有大型 JS | 加 `timeout=60000` |

**重启 Chrome 调试模式完整命令**：
```bash
# 关掉旧实例（保留 profile）
pkill -f "remote-debugging-port=9223" || true
sleep 2
open -na "Google Chrome" \
  --args \
  --remote-debugging-port=9223 \
  --user-data-dir=/Users/siqi/chrome-debug-profile
sleep 3
# 验证
curl -s http://localhost:9223/json/version | head -3
```

## B.2 SMM 未登录

| 症状 | 根因 | 处置 |
|------|------|------|
| 表格行显示「未登录」 | 登录态过期 | 跑 `relogin_assistant.py` 引导主人重新登录 |
| SMM 页跳转 `https://account.smm.cn/...` | 同上 | 同上 |
| 价格表为空 | 同上 | 同上 |

**手动登录**：
1. 调试 Chrome 打开 `https://hq.smm.cn/aluminum`
2. 未登录会跳 `https://account.smm.cn/...`
3. 主人完成登录（账号密码见附录 C）
4. 跑 `health_check_smm()` 验证（应返回 True）

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
| 文章页跳 `https://www.asianmetal.cn/login` | 登录态过期 | 调试 Chrome 完成登录 |
| `302 Found` 重定向到 login | 同上 | 同上 |

**手动登录**：调试 Chrome 打开 `https://www.asianmetal.cn/`，点右上角登录，输入账号密码。

## B.5 中钨在线

| 症状 | 根因 | 处置 |
|------|------|------|
| `WRONG_VERSION_NUMBER` 或 `000` 状态码 | 用 HTTPS（应为 HTTP） | 改 `http://` |
| 栏目页找到文章但抓不到钨粉价 | 文章不是钨价文 | 跳下一条 |
| 当日 15:00 抓空 | 文章发得晚，栏目页还没刷新 | **保留空 + 隔日 09:00 重抓** |
| 栏目页打不开（502/timeout） | 服务器问题 | 重试 3 次，3 次仍败标黄 |

**关键代码片段**（已修复 HTTPS bug）：
```python
import requests
# ⚠️ 必须是 HTTP
url = "http://news.chinatungsten.com/cn/tungsten-product-news.html"
resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 ..."})
soup = BeautifulSoup(resp.text, 'html.parser')
# 找最新文章
articles = soup.select('a[href*="/tungsten-product-news/"]')[:3]
# 进文章抓 钨粉价格
for a in articles:
    article_resp = requests.get("http://news.chinatungsten.com" + a['href'], timeout=15)
    m = re.search(r'钨粉价格\s*(\d+)\s*元[／/]\s*千克', article_resp.text)
    if m:
        return float(m.group(1))
```

## B.6 akshare WTI 失败

| 症状 | 根因 | 处置 |
|------|------|------|
| `ak.futures_foreign_commodity_realtime('CL')` 超时 | 网络或英为财情 API 限流 | 重试 3 次；3 次仍败用 `ak.futures_foreign_hist(symbol='CL')` 取最后一行收盘价 |
| 返回空 DataFrame | 同上 | 同上 |
| 数据滞后 1 天 | realtime 限流，fallback 到 hist | 在备注里写「15:00 实时价，超时用收盘价兜底」 |

---

# 📎 附录 C：入口密码本（账号 / 路径 / 端口）

> **用途**：别的 AI 拿 SKILL 接手时，**不用问主人就能找到所需环境**。

## C.1 账号信息（参考 TOOLS.md 同源）

| 服务 | 账号 | 密码 | 用途 |
|------|------|------|------|
| 启信宝 | `13512903125@139.com` | `Lt_091788` | 调 qixin_server.py 备查（**本项目不用**，仅记录）|
| SMM（上海有色）| `135***03125` | 主人口令 | SMM 登录态 |
| 亚洲金属网 | 主人账户 | 主人口令 | 亚洲金属网登录态 |
| 中钨在线 | 公开 | 公开 | **无需登录** |
| 长江有色 ccmn | 公开 | 公开 | **无需登录** |
| 英为财情 / akshare | 公开 | 公开 | **无需登录** |

> ⚠️ **SMM 和亚洲金属网密码未写明** — 主人按需在调试 Chrome 自己输，**不要硬编码**（安全考量）。如果自动化 cron 需要密码，请主人手动补到 `.env` 文件并 `.gitignore`。

## C.2 关键路径

```
/Users/siqi/Desktop/AI/jinggong-commodity-monitor/   ← 项目根
├── SKILL.md                                          ← 本文件
├── fill_and_verify.py                                ← 主流程
├── relogin_assistant.py                              ← 登录态修复
├── run.sh                                            ← 一键运行
├── 2026年有色金属市场价格共享(2).xlsx                ← 主表
├── 2026年有色金属市场价格共享.xlsx                    ← 旧表（已废弃，保留备查）
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

**为什么不硬编码到代码里** — 防止代码换机器跑时环境变量缺失导致无网络。主人按需塞 `~/.zshrc` 或 `run.sh`。

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

# 📎 附录 D：项目状态与下一步（截至 2026-06-26）

## D.1 当前可自动化情况

| 数据源 | 自动化程度 | 限制 |
|------|:--:|------|
| ccmn AJAX | ✅ 100% | 端点稳定，公开 |
| akshare WTI | ✅ 100% | 实时 API 偶发超时 |
| 中钨在线 钨粉 | 🟡 次日补抓 | 6/26 确认：当日 15:00 抓不到，发得晚 |
| SMM 6 项 | 🟡 90% | 依赖调试 Chrome 登录态，**登录态过期需主人手动重登** |
| 亚洲金属网 1 项 | 🟡 90% | 同上 |

**结论**：**8 项公开全自动 + 8 项半自动（需主人保持 SMM + 亚洲金属网登录态）**。

## D.2 仍待做（按优先级）

### P0 — 立刻
- [ ] **修复 fetcher_tungsten.py**：HTTPS → HTTP，入口改为栏目页
- [ ] 把 fill_and_verify.py 重构为「每个 fetcher 独立 + orchestrator 调度」

### P1 — 7/1 前
- [ ] **每日 cron 15:00 触发**（中钨粉 9:00 补抓）
- [ ] 登录态自动重试（relogin_assistant.py 接到 orchestrator）

### P2 — 7-8 月
- [ ] 邮件/Slack 通知
- [ ] 历史回溯
- [ ] 多 Excel 表支持

## D.3 业务复用建议（别的 AI 接手时怎么用）

1. **新接手的 AI 第一步**：读「🎯 一句话总览」+「接口契约表 附录 A」
2. **遇到问题**：不 debug 直接查「故障处置手册 附录 B」
3. **缺环境信息**：查「入口密码本 附录 C」
4. **要知道项目在哪一步**：看「项目状态 附录 D」+ 相关 Obsidian 笔记（[[工作/大宗原材料监控/14-...]]）

**复用前提**：
- 必须有 `~/.workbuddy/binaries/python/envs/jinggong/` venv
- 必须有 Chrome 调试 profile + SMM/亚洲金属网已登录
- 必须有本 SKILL.md + jinggong_monitor/ 代码

**不满足前提时**：先看 Obsidian 笔记「03-项目背景与需求总结」了解业务背景，再决定要不要单独搭环境。
