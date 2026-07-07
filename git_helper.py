#!/usr/bin/env python3
"""Git 操作辅助工具

为 fill_and_verify.py / sync_from_web.py / excel_to_web.py 提供统一的：
1. 代理自动检测（127.0.0.1:7890 / 1087 / 7897 / 8888 / 6152）
2. rebase 冲突自动 abort（避免仓库卡在脏状态）
3. commit + pull --rebase + push 一站式发布

用法:
    from git_helper import git_with_proxy, publish_to_github
"""

import subprocess
import sys
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(__file__).parent

# 常见代理端口（Clash/V2Ray/快连等）
_COMMON_PORTS = [7890, 1087, 7897, 8888, 6152]

_detected_proxy = None


def _detect_proxy() -> Optional[str]:
    """检测可用的本地代理，返回 http://127.0.0.1:PORT 或 None"""
    global _detected_proxy
    if _detected_proxy is not None:
        return _detected_proxy

    import os
    # 优先用环境变量
    for key in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
        val = os.environ.get(key, "")
        if val:
            _detected_proxy = val
            return val

    # 探测网络连通性：先试直连，再试代理
    import urllib.request
    import ssl

    # 1. 试直连（仅一次）
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(
            "https://github.com",
            headers={"User-Agent": "git-helper/1.0"},
        )
        urllib.request.urlopen(req, timeout=5, context=ctx)
        _detected_proxy = ""
        return ""
    except Exception:
        pass

    # 2. 直连不通，逐个试代理端口
    for port in _COMMON_PORTS:
        proxy = f"http://127.0.0.1:{port}"
        try:
            handler = urllib.request.ProxyHandler({"https": proxy, "http": proxy})
            opener = urllib.request.build_opener(handler)
            ctx = ssl.create_default_context()
            req = urllib.request.Request(
                "https://github.com",
                headers={"User-Agent": "git-helper/1.0"},
            )
            resp = opener.open(req, timeout=3)
            resp.close()
            _detected_proxy = proxy
            return proxy
        except Exception:
            continue

    _detected_proxy = ""
    return ""


def _git_env():
    """构建 git 子进程的环境变量（含代理）"""
    import os
    env = os.environ.copy()
    proxy = _detect_proxy()
    if proxy:
        env["http_proxy"] = proxy
        env["https_proxy"] = proxy
    return env


def git_with_proxy(args, cwd=None, timeout=60):
    """运行 git 命令，自动注入代理，统一超时和输出格式

    Returns:
        (returncode, stdout, stderr)
    """
    if cwd is None:
        cwd = str(PROJECT_DIR)
    r = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_git_env(),
    )
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def git_pull_rebase(cwd=None) -> bool:
    """git pull --rebase origin main

    自动处理冲突：冲突时 abort 并返回 False，不会让仓库卡在脏状态。
    """
    code, out, err = git_with_proxy(
        ["pull", "--rebase", "origin", "main"], cwd=cwd, timeout=60,
    )
    combined = out + err
    if code != 0:
        if "conflict" in combined.lower() or "CONFLICT" in combined:
            print("  ⚠️ rebase 冲突，自动 abort 恢复仓库状态")
            git_with_proxy(["rebase", "--abort"], cwd=cwd, timeout=30)
            return False
        # 网络问题（常见：代理不可用 / GitHub 超时）
        return False
    return True


def git_push(cwd=None) -> bool:
    """git push（含代理）"""
    code, out, err = git_with_proxy(["push"], cwd=cwd, timeout=60)
    if code != 0:
        err_msg = err or out
        if "fetch first" in err_msg.lower() or "non-fast-forward" in err_msg.lower():
            print(f"  ❌ 推送被拒（远程有新提交），请重试")
        else:
            print(f"  ❌ push 失败: {err_msg[:200]}")
        return False
    print("  ✅ push 成功")
    return True


def publish_to_github(files, commit_msg, cwd=None):
    """一站式发布：add → commit → pull --rebase → push

    Args:
        files: 要 add 的文件列表（相对于 cwd 的路径）
        commit_msg: commit message
        cwd: 工作目录（默认项目根目录）

    Returns:
        True 成功, False 失败
    """
    if cwd is None:
        cwd = str(PROJECT_DIR)

    proxy = _detect_proxy()
    proxy_info = f"（代理 {proxy}）" if proxy else "（直连）"
    print(f"  → 发布中 {proxy_info} ...")

    # 1. git add
    code, out, err = git_with_proxy(["add"] + files, cwd=cwd, timeout=30)
    if code != 0:
        print(f"  ❌ git add 失败: {err[:200]}")
        return False

    # 2. git commit（检查是否真的有变化）
    code, out, err = git_with_proxy(["diff", "--cached", "--quiet"], cwd=cwd, timeout=10)
    if code == 0:
        print("  (无变化，跳过提交)")
        return True

    code, out, err = git_with_proxy(
        ["commit", "-m", commit_msg], cwd=cwd, timeout=30,
    )
    if code != 0:
        msg = out + err
        if "nothing to commit" in msg.lower():
            print("  (无变化，跳过提交)")
            return True
        print(f"  ❌ git commit 失败: {(out+err)[:200]}")
        return False

    # 3. pull --rebase（冲突自动 abort）
    if not git_pull_rebase(cwd):
        print("  ⚠️ pull 失败或冲突，跳过 push（commit 已在本地）")
        return False

    # 4. push
    return git_push(cwd)


if __name__ == "__main__":
    # 快速测试代理检测
    proxy = _detect_proxy()
    print(f"代理检测结果: {proxy or '直连'}")
    code, out, err = git_with_proxy(["status", "--short"], timeout=10)
    print(f"git status: {out or '(clean)'}")
