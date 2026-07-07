#!/usr/bin/env python3
"""
Excel 手动更新 → 自动同步网页

当用户手动填写 Excel 后，运行此脚本：
1. 导出 docs/data.json
2. 推送到 GitHub Pages

用法: python3 excel_to_web.py
"""

import sys
import os
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

def export_json():
    """运行 export_excel_to_json.py"""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "export_excel_to_json.py")],
        cwd=str(SCRIPT_DIR),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: 导出失败: {result.stderr}", file=sys.stderr)
        return False
    print(result.stdout.strip())
    return True


def git_push(commit_msg: str):
    """推送 docs/data.json 到 GitHub Pages（含代理 + 冲突处理）"""
    from git_helper import publish_to_github
    return publish_to_github(
        files=["docs/data.json"],
        commit_msg=commit_msg,
        cwd=str(SCRIPT_DIR),
    )


def main():
    import datetime
    today = datetime.date.today().isoformat()

    print(f"=== Excel → 网页同步 {today} ===")

    # 1. 导出 JSON
    print("\n[1/2] 导出 data.json...")
    if not export_json():
        sys.exit(1)

    # 2. 推送 GitHub Pages
    print("\n[2/2] 推送到 GitHub Pages...")
    ok = git_push(f"手动更新 {today}")
    if ok:
        print(f"\n✅ 完成！网页已更新: https://lekelin2046.github.io/jinggong-commodity-monitor/")
    else:
        print("\n⚠️ 推送失败，请检查 git 状态")


if __name__ == "__main__":
    main()
