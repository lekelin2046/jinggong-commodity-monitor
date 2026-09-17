#!/bin/bash
# ============================================================
# 精工有色金属监控 - macOS LaunchAgent 定时任务安装脚本
# ============================================================
# macOS 上 cron 被 SIP 限制，改用 LaunchAgent（macOS 推荐方式）
#
# 用法（只需执行一次）：
#   bash setup_launchd.sh install    # 安装三个定时任务
#   bash setup_launchd.sh uninstall  # 卸载
#   bash setup_launchd.sh status     # 查看状态
# ============================================================

set -e

LAUNCH_DIR="$HOME/Library/LaunchAgents"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"

# 三个 plist 文件
PLIST_WTI="$LAUNCH_DIR/com.jinggong.wti.plist"
PLIST_DAILY="$LAUNCH_DIR/com.jinggong.daily.plist"
PLIST_TUNGSTEN="$LAUNCH_DIR/com.jinggong.tungsten.plist"

CMD="${1:-install}"

case "$CMD" in
  install)
    echo "=== 安装精工监控 LaunchAgent ==="
    echo ""

    # 先卸载旧的（如果已加载）
    for plist in "$PLIST_WTI" "$PLIST_DAILY" "$PLIST_TUNGSTEN"; do
      if launchctl list "$(basename "$plist" .plist)" &>/dev/null; then
        launchctl unload "$plist" 2>/dev/null || true
      fi
    done

    # 加载新的
    for plist in "$PLIST_WTI" "$PLIST_DAILY" "$PLIST_TUNGSTEN"; do
      if [ ! -f "$plist" ]; then
        echo "✗ plist 文件不存在: $plist"
        echo "  请确保 plist 文件已生成"
        exit 1
      fi
      launchctl load "$plist"
      echo "✓ 已加载: $(basename "$plist" .plist)"
    done

    echo ""
    echo "=== 定时任务已安装 ==="
    echo "  15:00 周一至周五  → WTI 时点价      (com.jinggong.wti)"
    echo "  17:00 周一至周五  → 主流程 16 品种  (com.jinggong.daily)"
    echo "  21:00 周一至周五  → 钨粉补查        (com.jinggong.tungsten)"
    echo ""
    echo "日志: $LOG_DIR/launchd_*.log"
    echo ""
    echo "查看状态: bash setup_launchd.sh status"
    ;;

  uninstall)
    echo "=== 卸载精工监控 LaunchAgent ==="
    for plist in "$PLIST_WTI" "$PLIST_DAILY" "$PLIST_TUNGSTEN"; do
      if [ -f "$plist" ]; then
        launchctl unload "$plist" 2>/dev/null || true
        echo "✓ 已卸载: $(basename "$plist" .plist)"
      fi
    done
    echo ""
    echo "定时任务已全部卸载（plist 文件保留，可重新 install）"
    ;;

  status)
    echo "=== LaunchAgent 状态 ==="
    for name in com.jinggong.wti com.jinggong.daily com.jinggong.tungsten; do
      if launchctl list "$name" &>/dev/null; then
        pid=$(launchctl list "$name" | grep "PID" | awk '{print $3}')
        echo "  ✓ $name — 已加载 (PID: ${pid:-未运行})"
      else
        echo "  ✗ $name — 未加载"
      fi
    done
    echo ""
    echo "=== plist 文件 ==="
    ls -la "$PLIST_WTI" "$PLIST_DAILY" "$PLIST_TUNGSTEN" 2>/dev/null || echo "  (无 plist 文件)"
    ;;

  *)
    echo "用法: bash setup_launchd.sh [install|uninstall|status]"
    exit 1
    ;;
esac
