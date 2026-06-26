#!/bin/bash
# 精工板块大宗原材料监控 - 运行脚本
# 用法: bash run.sh [subcommand]
#   bash run.sh fetch      # 拉取数据
#   bash run.sh report     # 生成日报
#   bash run.sh fill       # 填充Excel
#   bash run.sh all        # 全流程
#   bash run.sh health     # 健康检查
#
# 注意: GitHub 加速器等系统代理会影响国内站点访问。
# 脚本自动对 commodity 相关域名禁用代理。

VENV_PYTHON="/Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/python3"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 绕过代理：国内大宗商品站点直连
export NO_PROXY="51bxg.com,sci99.com,chinatungsten.com,steelcn.cn,zgw.com,ccmn.cn,cnfeol.com,ctia.com.cn,100ppi.com,mysteel.com,cls.cn,smm.cn,qqthj.com,${NO_PROXY}"
export no_proxy="$NO_PROXY"

cd "$PROJECT_DIR"
PYTHONPATH="$PROJECT_DIR" exec "$VENV_PYTHON" -m jinggong_monitor.main "${@:-all}"
