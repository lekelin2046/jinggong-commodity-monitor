#!/bin/bash
# 精工板块大宗原材料监控 - 运行脚本
# 用法: bash run.sh [subcommand]
#   bash run.sh daily      # 17:00 主流程（默认）：抓 16 品种 + 填表 + 截图（WTI 由 15:00 cron 单独填）
#   bash run.sh wti        # 15:00 单跑 WTI（写 sheet2）
#   bash run.sh tungsten   # 21:00 钨粉补查
#   bash run.sh manual     # 手动跑历史回溯（6/23+6/24 等历史日期）
#   bash run.sh health     # 健康检查
#   bash run.sh board      # 生成/更新 HTML 看板（独立，不碰 Excel，无截图）
#   bash run.sh deploy     # 部署看板到 CloudStudio（给同事公开链接）
#
# 2026-07-02 改造：
#   - 直接调 fill_and_verify.py（不再走 jinggong_monitor 模块化层）
#   - SMM/亚洲金属网自动登录（去掉对 Chrome 9223 调试端口的依赖）
#   - 支持三个 cron 时间点的子命令
#
# 注意: GitHub 加速器等系统代理会影响国内站点访问。
# 脚本自动对 commodity 相关域名禁用代理。

set -e

VENV_PYTHON="/Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/python3"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 绕过代理：国内大宗商品站点直连
export NO_PROXY="51bxg.com,sci99.com,chinatungsten.com,steelcn.cn,zgw.com,ccmn.cn,cnfeol.com,ctia.com.cn,100ppi.com,mysteel.com,cls.cn,smm.cn,qqthj.com,asianmetal.cn,www.asianmetal.cn,user.smm.cn,hq.smm.cn,${NO_PROXY}"
export no_proxy="$NO_PROXY"

cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"

SUBCMD="${1:-daily}"

case "$SUBCMD" in
  daily)
    # 17:00 主流程：抓 16 品种 + 填 sheet1 + 截图（skip_wti=True，不覆盖 15:00 写的 WTI）
    export JINGGONG_RUN_MODE=daily
    exec "$VENV_PYTHON" fill_and_verify.py
    ;;
  wti)
    # 15:00 单跑 WTI（写 sheet2 的 WTI 列）
    exec "$VENV_PYTHON" -c "
import sys, openpyxl
from datetime import datetime
from pathlib import Path
sys.path.insert(0, '$PROJECT_DIR')
import akshare as ak

EXCEL_PATH = Path('$PROJECT_DIR') / '2026年有色金属市场价格共享(2).xlsx'
today = datetime.now().strftime('%Y-%m-%d')
print(f'[WTI cron] {today} 抓取 WTI 15:00 时点价...')

# akshare 实时
df = ak.futures_foreign_commodity_realtime(symbol='CL')
price = round(float(df.iloc[0]['最新价']), 2)
print(f'[WTI cron] WTI = {price} USD/bbl')

wb = openpyxl.load_workbook(str(EXCEL_PATH))
sheet_name = '日均价（中钨在线 原油）'
if sheet_name not in wb.sheetnames:
    print(f'[WTI cron] ⚠️ sheet 不存在: {sheet_name}')
    sys.exit(1)
ws = wb[sheet_name]

# 找今日行，没有就新建
target_row = None
for r in range(3, ws.max_row + 2):
    v = ws.cell(row=r, column=6).value  # F 列是 WTI 日期
    if v and isinstance(v, datetime) and v.strftime('%Y-%m-%d') == today:
        target_row = r
        break
if target_row is None:
    target_row = ws.max_row + 1
    ws.cell(row=target_row, column=6, value=datetime.now()).font = __import__('openpyxl.styles', fromlist=['Font']).Font(name='微软雅黑', size=11)
    ws.cell(row=target_row, column=5, value='WTI原油').font = __import__('openpyxl.styles', fromlist=['Font']).Font(name='微软雅黑', size=11)

ws.cell(row=target_row, column=7, value=price).font = __import__('openpyxl.styles', fromlist=['Font']).Font(name='微软雅黑', size=11)
wb.save(str(EXCEL_PATH))
wb.close()
print(f'[WTI cron] ✅ 写入 {sheet_name} row {target_row} col G = {price}')
"
    ;;
  tungsten)
    # 21:00 钨粉补查：单独跑中钨在线
    exec "$VENV_PYTHON" -c "
import sys, openpyxl
from datetime import datetime
from pathlib import Path
sys.path.insert(0, '$PROJECT_DIR')

EXCEL_PATH = Path('$PROJECT_DIR') / '2026年有色金属市场价格共享(2).xlsx'
today = datetime.now().strftime('%Y-%m-%d')
print(f'[钨粉补查] {today}')

from jinggong_monitor.fetcher_tungsten import ChinatungstenFetcher
fetcher = ChinatungstenFetcher()
results = fetcher.fetch()
if not results:
    print('[钨粉补查] 未抓到钨粉，下次再试')
    sys.exit(1)

w_price = results.get('W')
print(f'[钨粉补查] 钨粉 = {w_price} 元/千克')

# 写 sheet1 P 列
wb = openpyxl.load_workbook(str(EXCEL_PATH))
ws = wb['日均价（2026年市场）']
target_row = None
for r in range(2, ws.max_row + 2):
    v = ws.cell(row=r, column=1).value
    if v and str(v)[:10] == today:
        target_row = r
        break
if target_row is None:
    print(f'[钨粉补查] ⚠️ 今日 row 不存在，先跑 daily 主流程')
    sys.exit(1)

from openpyxl.styles import Font, PatternFill
cell = ws.cell(row=target_row, column=16, value=w_price)
cell.font = Font(name='微软雅黑', size=11)
# 如果原来是黄底（标黄未填），清掉
cell.fill = PatternFill(fill_type=None)
wb.save(str(EXCEL_PATH))
wb.close()
print(f'[钨粉补查] ✅ 写入 sheet1 row {target_row} col P = {w_price}')
"
    ;;
  manual)
    # 手动跑历史回溯（6/23+6/24）
    export JINGGONG_RUN_MODE=manual
    exec "$VENV_PYTHON" fill_and_verify.py
    ;;
  health)
    # 健康检查
    exec "$VENV_PYTHON" -c "
import sys
sys.path.insert(0, '$PROJECT_DIR')
from jinggong_monitor.fetcher_ccmn import CcmnFetcher
from jinggong_monitor.fetcher_tungsten import ChinatungstenFetcher
import akshare as ak

print('=== 健康检查 ===')
# ccmn
try:
    f = CcmnFetcher()
    ok = f.health_check()
    print(f'ccmn AJAX: {\"✅\" if ok else \"❌\"} ')
except Exception as e:
    print(f'ccmn AJAX: ❌ {e}')

# 中钨
try:
    f = ChinatungstenFetcher()
    ok = f.health_check()
    print(f'中钨在线: {\"✅\" if ok else \"❌\"}')
except Exception as e:
    print(f'中钨在线: ❌ {e}')

# akshare WTI
try:
    df = ak.futures_foreign_commodity_realtime(symbol='CL')
    print(f'akshare WTI: ✅ {df.iloc[0][\"最新价\"]}')
except Exception as e:
    print(f'akshare WTI: ❌ {e}')
"
    ;;
  *)
    echo "未知子命令: $SUBCMD"
    echo "用法: bash run.sh [daily|wti|tungsten|manual|health]"
    exit 1
    ;;
esac
