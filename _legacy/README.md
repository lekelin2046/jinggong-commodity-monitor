# 已废弃文件（2026-09-17 归档）

> ⚠️ 这里的文件**都不要再使用、也不要用它们排障**。保留仅为可回溯，随时可整体删除。

| 文件 | 曾经的用途 | 为什么废弃 |
| --- | --- | --- |
| `fill_and_verify.py` | 2026-07 之前的主流程（采集 + 填表 + 校验 + 截图） | 已拆分为 `daily_update_all.py`（主抓）+ `daily_check_missed.py`（补抓）+ `jinggong_monitor/` 下的独立 fetcher。**已无任何调用方** |
| `excel_to_web.py` | 线下改完 Excel 后手动推看板 | 由 `export_excel_to_json.py` 取代 |
| `run.sh` | 一键运行（daily / wti / tungsten 子命令） | 调用的正是 `fill_and_verify.py`；定时已迁移到**平台自动化** |
| `setup_launchd.sh` | 安装 macOS LaunchAgent 三个定时任务 | launchd 方案已废弃（任务当前**未加载**）；且其中引用的 Excel 文件名 `2026年有色金属市场价格共享(2).xlsx` 已不存在 |
| `核查报告_2026-06-16_to_22.md` | 6 月一次性数据核查报告 | 一次性产物，结论已并入项目文档 |

## 现在的正确入口

| 时间 | 脚本 |
| :-: | --- |
| 15:00 | `daily_update_all.py` |
| 17:00 | `daily_check_missed.py` |
| 次日 09:00 | `backfill_lme_official.py` |
| 15:30 / 15:40 | `daily_plastic.py` / `daily_plastic_ext.py`（诺博） |
| 15:35 | `mand_update.py`（曼德） |

## 相关

- 排障请看 `SKILL.md` 附录 B
- 三板块全貌见 Obsidian `raw/工作/大宗原材料监控/`
