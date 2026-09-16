#!/usr/bin/env python3
"""
5PM 补抓检查 — 检查今日全品种（25项）是否填全，缺则补抓

用法: python3 daily_check_missed.py

说明：
- 仅工作日运行；周末/法定节假日市场休市，直接退出，不误触发补抓。
- 覆盖 Excel 列 2-26（25 个品种）。
- 第 27 列 LME 铝不参与「缺失」判定：2026-09-16 起该列由次日 9:00 的
  backfill_lme_official.py 按「官方数据日」回填，当日为空属预期。
  本脚本另做一道零成本兜底：若上一数据行该列仍为空，则触发 backfill_lme_official.py。
"""

import sys, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

# 工作日 / 法定节假日判定（与主抓取共用同一交易日历）
from jinggong_monitor.trading_calendar import is_trading_day, skip_reason

try:
    import openpyxl
except ImportError:
    print("ERROR: openpyxl not installed", file=sys.stderr)
    sys.exit(1)

EXCEL_PATH = SCRIPT_DIR / "2026年有色金属市场价格.xlsx"
SHEET_NAME = "日均价（2026年市场）"
SMM_COLS = [2,3,4,5,14,15,13]  # SMM: 2-5, 13-15
CCMN_COLS = [6,7,8,9,10,11,12]  # CCMN: 6-12
TOTAL = 25  # 15:00 抓取的品种数（列 2-26）
ALL_COLS = list(range(2, 27))  # 2-26（25 品种）
LME_COL = 27  # LME 铝：次日 9:00 回填，不参与缺失判定

today = datetime.date.today()

# ===== 周末及法定节假日跳过 =====
# 非交易日市场休市，Excel 无当日行属正常，不应误判为"缺失"而触发补抓。
if not is_trading_day(today):
    print(f"⏸️  今日为{skip_reason(today)}（{today}），市场休市，跳过补抓检查。")
    sys.exit(0)

wb = openpyxl.load_workbook(EXCEL_PATH)
ws = wb[SHEET_NAME]

# ===== LME 铝兜底（2026-09-16 新增）=====
# 主回填在次日 9:00（backfill_lme_official.py）。官方接口只提供「最新一个数据日」，
# 若 9:00 那次失败（休眠/断网/CF 拦截），该官方价将永久取不回 → 这里加一道 17:00 保险。
# 零成本预检：上一数据行该列已有值则直接跳过，不启动 Playwright。
prev_row = None
for _r in range(2, ws.max_row + 1):
    _v = ws.cell(_r, 1).value
    if isinstance(_v, datetime.datetime) and _v.date() < today:
        prev_row = _r
if prev_row is not None:
    _prev_val = ws.cell(prev_row, LME_COL).value
    if _prev_val is not None:
        print(f"✓ LME 铝：上一数据行 #{prev_row} 已回填（{_prev_val}），无需兜底")
    else:
        print(f"→ LME 铝：上一数据行 #{prev_row} 仍为空（次日 9:00 回填未成功？），触发兜底")
        import subprocess
        subprocess.run([sys.executable, str(SCRIPT_DIR / "backfill_lme_official.py")],
                       cwd=str(SCRIPT_DIR))

# 找今天行
target_row = None
for r in range(2, ws.max_row + 1):
    v = ws.cell(r, 1).value
    if isinstance(v, datetime.datetime) and v.date() == today:
        target_row = r
        break

if not target_row:
    print(f"→ 今天 ({today}) 无数据行，触发全品种补抓")
    import subprocess
    subprocess.run([sys.executable, str(SCRIPT_DIR / "daily_update_all.py")], cwd=str(SCRIPT_DIR))
    sys.exit()

# 检查
missing = [c for c in ALL_COLS if ws.cell(target_row, c).value is None]
if not missing:
    print(f"✓ 今日 #{target_row} 行 {TOTAL}/{TOTAL} 品种已全部填全，无需补抓")
    sys.exit(0)

missing_labels = {2:"ADC12",3:"A380",4:"AlSi9Cu3",5:"A356",
    6:"A00_AL",7:"CU",8:"SI_441",9:"SI_3303",10:"MG",11:"MN",
    12:"SI_331",13:"Wenxi_MG",14:"AM60B",15:"AZ91D",16:"W",17:"WTI",
    18:"IRON_ORE",19:"COKE",20:"SS_304",21:"SS_409",22:"SS_439",
    23:"SS_441",24:"NICKEL_IRON",25:"HIGH_CARBON_FECR",26:"ADC12_JAPAN_CIF",
    27:"LME_AL"}

missing_names = [missing_labels.get(c, f"col{c}") for c in missing]
print(f"→ 今日 #{target_row} 行缺 {len(missing)}/{TOTAL} 品种: {', '.join(missing_names)}，触发补抓")
import subprocess
subprocess.run([sys.executable, str(SCRIPT_DIR / "daily_update_all.py")], cwd=str(SCRIPT_DIR))
