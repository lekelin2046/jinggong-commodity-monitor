# tools/ — 一次性工具与探针（不参与定时任务）

> ⚠️ 定时任务的入口脚本**必须留在仓库根目录**，因为 automation 配置写死了调用路径：
> `daily_update_all.py`（15:00）、`daily_check_missed.py`（17:00）、`backfill_lme_official.py`（9:00）、
> `mand_update.py`（15:35）、`jinggong_monitor/daily_plastic.py`（15:30）、`jinggong_monitor/daily_plastic_ext.py`（15:40）。
> 同一条链上的 `changelog.py`、`git_helper.py`、`export_excel_to_json.py` 也留在根目录（被 `sys.path.insert` 与 `subprocess` 引用）。

## probes/ — 数据源侦察脚本（用完即弃，保留备查）

| 脚本 | 侦察目标 | 产物 |
|---|---|---|
| `probe_smm_aluminum.py` | `hq.smm.cn/aluminum` 可用品种 | `data/smm_aluminum_probe.txt` |
| `probe_smm_price_history.py` | SMM 历史价站（`price.smm.cn` → `history.smm.cn`）权限与接口 | 终端 |
| `probe_steel_smm.py` | `steel.smm.cn` 铁矿石 / 冶金焦 | `screenshots/2026-07-16/` |
| `probe_lz_gate.py` | 隆众资讯文章的数据门槛 | 终端 |
| `probe_lz_login.py` | 隆众登录机制 | `data/probe_lz_login/` |
| `probe_dc_api.py` | 隆众价格中心（`dc.oilchem.net`）接口 | `data/probe_dc/` |
| `probe_dc_varieties.py` | 隆众目标品类 → `varietiesId` / `channelId` 映射 | `data/probe_dc/` |
| `probe_lme_official.py` | LME 官网官方价接口 | `data/lme_official_latest.json` |
| `probe_xlsx_history.py` | 诺博工作簿历史序列 ↔ `data.json` 逐点比对 | 终端 |
| `probe_sci99_table.py` | 卓创搜索页 DOM 结构 + 「品种编号」精确检索能力 | 终端 |
| `probe_mand_specs.py` | 曼德（拟）新增品种在**卓创 / 隆众**双源的收录情况 | 终端 |
| `probe_sci99_history.py` | 卓创**历史数据**入口枚举（候选历史页 + 站内 XHR） | 终端 |
| `probe_sci99_lines.py` | 卓创 `selectedlines/getlines.ashx` 曲线接口（请求体 + 响应 + 是否含日期序列） | `/tmp/sci99_lines.json` |
| `probe_sci99_product.py` | 卓创**品种页**（`product.aspx?ppid=`，即曼德所述「塑料→工程塑料→PA6」导航树）的历史能力 | `/tmp/sci99_product_xhr.json` |
| `verify_mand_varieties.py` | 曼德页渲染回归（27 项断言，含「按源报价日期归位」列位校验） | 终端 |
| `verify_mand_backfill.py` | 曼德历史回填验证（21 项断言：data.json 段结构/边界 + 页面逐列取值 + 趋势图点位） | 终端 |

**运行方式**：必须在**仓库根目录**执行——脚本内的 `data/`、`cookies/`、`sources/` 相对路径按 cwd 解析。

```bash
cd <仓库根>
python3 tools/probes/probe_dc_api.py
```

## board/ — 看板改造与测试

| 脚本 | 用途 |
|---|---|
| `patch_multi_trend.py` | 把「单品日趋势」卡片批量改造为「多指标价格曲线对比」（橡胶页 + 内外饰页；原子替换 + 命中断言） |
| `test_multi_trend.py` | 该卡片的 Playwright 功能测试（31 项断言 × 2 页） |

```bash
cd <仓库根>
python3 -m http.server 8731 --bind 127.0.0.1 &   # HTML 须走 HTTP，file:// 被 CORS 拦
python3 tools/board/test_multi_trend.py 8731
```

截图输出至 `output/`。
