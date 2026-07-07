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
    """推送 docs/data.json 到 GitHub Pages
    
    2026-07-07 修复：先 commit 再 pull --rebase，正确处理远程在线编辑
    流程：add → commit → pull --rebase → push
    - 如果远程有新提交（在线编辑），rebase 会把本地 commit 叠加到远程之上
    - data.json 冲突时，提醒用户手动解决（本地 Excel vs 远程在线编辑）
    """
    # 先检查是否有变化
    r = subprocess.run(["git", "diff", "--quiet", "docs/data.json"], cwd=str(SCRIPT_DIR))
    if r.returncode == 0:
        print("  (data.json 无变化，跳过推送)")
        return True

    # 1. add + commit（本地先存档）
    for cmd in [["git", "add", "docs/data.json"], ["git", "commit", "-m", commit_msg]]:
        result = subprocess.run(cmd, cwd=str(SCRIPT_DIR), capture_output=True, text=True)
        if result.returncode != 0:
            err = result.stderr.strip()
            if "nothing to commit" in err.lower():
                print("  (无变化，跳过)")
                return True
            print(f"WARN: git {' '.join(cmd[:2])} failed: {err}", file=sys.stderr)
            return False

    # 2. pull --rebase（把远程在线编辑合并进来，本地 commit 叠加到远程之上）
    print("  → git pull --rebase origin main ...")
    pull = subprocess.run(
        ["git", "pull", "--rebase", "origin", "main"],
        cwd=str(SCRIPT_DIR), capture_output=True, text=True,
    )
    if pull.returncode != 0:
        err = pull.stderr.strip() + " " + pull.stdout.strip()
        if "conflict" in err.lower() or "CONFLICT" in err:
            print(f"❌ data.json 冲突！远程有在线编辑，本地 Excel 也有修改", file=sys.stderr)
            print(f"   请手动解决冲突后运行: git rebase --continue && git push", file=sys.stderr)
            print(f"   或放弃本地: git rebase --abort && python3 sync_from_web.py", file=sys.stderr)
            # 不自动 abort，让用户看到冲突文件
            return False
        # 网络问题：尝试继续 push（可能远程无新提交）
        print(f"  ⚠️ pull 网络失败（继续尝试 push）: {err}")

    # 3. push
    push = subprocess.run(["git", "push"], cwd=str(SCRIPT_DIR), capture_output=True, text=True)
    if push.returncode != 0:
        err = push.stderr.strip()
        if "fetch first" in err.lower() or "non-fast-forward" in err.lower():
            print(f"❌ 推送被拒（远程有新提交），请重试或手动 sync", file=sys.stderr)
            return False
        print(f"  git push failed: {err}", file=sys.stderr)
        return False
    print("  ✅ 推送成功")
    return True


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
