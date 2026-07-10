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
    """推送 docs/data.json + changelog.json 到 GitHub Pages（含代理 + 冲突处理）"""
    from git_helper import publish_to_github
    return publish_to_github(
        files=["docs/data.json", "docs/changelog.json"],
        commit_msg=commit_msg,
        cwd=str(SCRIPT_DIR),
    )


def record_manual_changes():
    """对比 HEAD 版 data.json 与当前导出版，记录手动变更到 changelog

    线下流程：用户改 Excel → 运行本脚本导出 → 推送。
    此处导出后用 git HEAD 版作为「变更前」，当前文件作为「变更后」，
    计算 diff 并追加留痕（source=manual_xlsx，编辑者不记具体人）。
    """
    import json
    from changelog import compute_dict_diff, record_changes, SOURCE_MANUAL_XLSX, current_commit_sha

    # 变更前：git HEAD 版 data.json
    before_data = {}
    try:
        from git_helper import git_with_proxy
        code, out, err = git_with_proxy(
            ["show", "HEAD:docs/data.json"], cwd=str(SCRIPT_DIR), timeout=30,
        )
        if code == 0 and out:
            before_data = json.loads(out).get("data", {})
    except Exception:
        before_data = {}

    # 变更后：当前已导出的 data.json
    after_path = SCRIPT_DIR / "docs" / "data.json"
    if not after_path.exists():
        return
    after_data = json.loads(after_path.read_text(encoding="utf-8")).get("data", {})

    # 首次启用（HEAD 无基准）跳过，避免把整表历史误记为一次变更
    if not before_data:
        return

    diffs = compute_dict_diff(before_data, after_data)
    if diffs:
        sha = current_commit_sha(str(SCRIPT_DIR))
        n = record_changes(diffs, source=SOURCE_MANUAL_XLSX, editor="—", commit=sha)
        print(f"  📝 变更留痕 {n} 条（manual_xlsx）")


def main():
    import datetime
    today = datetime.date.today().isoformat()

    print(f"=== Excel → 网页同步 {today} ===")

    # 1. 导出 JSON
    print("\n[1/2] 导出 data.json...")
    if not export_json():
        sys.exit(1)

    # 1.5 记录手动变更（导出后、推送前）
    record_manual_changes()

    # 2. 推送 GitHub Pages
    print("\n[2/2] 推送到 GitHub Pages...")
    ok = git_push(f"手动更新 {today}")
    if ok:
        print(f"\n✅ 完成！网页已更新: https://lekelin2046.github.io/jinggong-commodity-monitor/")
    else:
        print("\n⚠️ 推送失败，请检查 git 状态")


if __name__ == "__main__":
    main()
