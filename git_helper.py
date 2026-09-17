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

# 所有可能承载代理的环境变量（大小写都要清）
_PROXY_ENV_KEYS = ("http_proxy", "https_proxy", "all_proxy")


def _clean_proxy_env() -> dict:
    """返回一份**清除了全部代理变量**的环境副本

    ⚠️ 为什么必须清：WorkBuddy 等沙箱会注入透明代理
    （`HTTP_PROXY=http://127.0.0.1:57474`），该代理通常只通国内站点、
    **不通 GitHub**。不清掉则 git 所有网络操作必然失败，且报错具有欺骗性
    （`Empty reply from server` / `Operation too slow` / `Failed to connect …443`）。
    """
    import os
    return {k: v for k, v in os.environ.items()
            if k.lower() not in _PROXY_ENV_KEYS}


def _probe(proxy: Optional[str] = None, timeout: int = 6,
           url: str = "https://github.com") -> bool:
    """实测某条出口能否访问 url

    proxy=None 表示**直连**（显式禁用代理 —— 关键：urllib 默认会读环境变量，
    不显式禁用的话「测直连」其实走了代理，测出来的结果是假的）。
    """
    import ssl
    import urllib.request
    handler = (urllib.request.ProxyHandler({"http": proxy, "https": proxy})
               if proxy else urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(handler)
    try:
        resp = opener.open(
            urllib.request.Request(url, headers={"User-Agent": "git-helper/1.0"}),
            timeout=timeout, context=ssl.create_default_context())
        resp.close()
        return True
    except Exception:
        return False


def _detect_proxy() -> Optional[str]:
    """检测可用出口，返回代理 URL；返回 "" 表示**直连**

    顺序：① 直连 → ② 环境变量里的代理（**必须实测能通 GitHub**）→ ③ 常见本地端口

    ⚠️ 2026-09-17 修复：原实现**盲信环境变量**，直接把沙箱注入的
    `127.0.0.1:57474` 当可用代理返回，导致所有走本模块的推送全部失败
    （即此前记录的「_detect_proxy 会误判」的真正原因）。现在任何代理
    都必须先通过 `_probe()` 实测，不再盲信。
    """
    global _detected_proxy
    if _detected_proxy is not None:
        return _detected_proxy

    import os

    # 1. 直连优先（显式禁用代理，否则测的是代理）
    if _probe():
        _detected_proxy = ""
        return ""

    # 2. 环境变量里的代理 —— 验证通过才采用
    for key in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
        val = (os.environ.get(key) or "").strip()
        if val and _probe(proxy=val):
            _detected_proxy = val
            return val

    # 3. 逐个试常见本地代理端口
    for port in _COMMON_PORTS:
        proxy = f"http://127.0.0.1:{port}"
        if _probe(proxy=proxy):
            _detected_proxy = proxy
            return proxy

    _detected_proxy = ""
    return ""


def _git_env():
    """构建 git 子进程环境：**先清掉继承的代理变量**，再按检测结果注入

    旧的 `os.environ.copy()` 会把沙箱代理原样传给 git —— 即使
    `_detect_proxy()` 判定直连，大写 `HTTP_PROXY` 仍会被 libcurl 读取。
    """
    env = _clean_proxy_env()
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


def git_push(cwd=None, retries: int = 6) -> bool:
    """git push（自动清代理 + 网络间歇时重试）

    ⚠️ 直连 GitHub 是**间歇性可用**的 —— 实测同一命令连续 8 次里第 2 次才成功，
    因此**必须重试**，不能一次失败就放弃（这是历史「推送失败」的主因之一）。
    同时对慢速连接放宽容忍（lowSpeedLimit=10 + 45s），慢速直连常比快速失败更有效。

    不重试的情形：被拒（fetch first / non-fast-forward）—— 那是本地状态问题。
    """
    import time

    last = ""
    for i in range(1, retries + 1):
        code, out, err = git_with_proxy(
            ["-c", "http.lowSpeedLimit=10", "-c", "http.lowSpeedTime=45", "push"],
            cwd=cwd, timeout=150,
        )
        if code == 0:
            print("  ✅ push 成功" + (f"（第 {i} 次尝试）" if i > 1 else ""))
            return True

        last = (err or out).strip()
        low = last.lower()
        if "fetch first" in low or "non-fast-forward" in low:
            print("  ❌ 推送被拒（远程有新提交）—— 需先 pull --rebase，不重试")
            return False

        tail = last.splitlines()[-1][:110] if last else "未知错误"
        print(f"  ⏳ 第 {i}/{retries} 次失败：{tail}")
        if i < retries:
            time.sleep(4)

    print(f"  ❌ push 失败（已重试 {retries} 次）")
    return False


def ahead_count(cwd=None) -> int:
    """本地领先 origin/main 的提交数。

    这是判断「是否真的需要推送」的唯一依据 —— 只看本次有没有产生新 commit
    是不够的：本地可能残留历史未推送的 commit（见 publish_to_github 的说明）。
    """
    code, out, err = git_with_proxy(
        ["rev-list", "--count", "origin/main..HEAD"], cwd=cwd, timeout=15,
    )
    if code != 0:
        return 0
    try:
        return int((out or "0").strip())
    except ValueError:
        return 0


def publish_to_github(files, commit_msg, cwd=None):
    """一站式发布：add → commit → pull --rebase → push

    Args:
        files: 要 add 的文件列表（相对于 cwd 的路径）
        commit_msg: commit message
        cwd: 工作目录（默认项目根目录）

    Returns:
        True 成功（且确认无未推送残留）, False 失败

    ⚠️ 历史缺陷（2026-09-17 修复）：原实现在「本次无新变化」时直接 return True，
       不检查本地是否残留**此前已提交但未推送**的 commit。后果是调用方拿到 True
       并打印「已推送」，而远程其实没更新 —— 数据静默丢失、看板不更新，
       且难以察觉（因为脚本一切"正常"）。
       现改为：无新提交也要核对 ahead，落后即照常走 pull --rebase + push。
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
    has_staged = git_with_proxy(
        ["diff", "--cached", "--quiet"], cwd=cwd, timeout=10,
    )[0] != 0

    if has_staged:
        code, out, err = git_with_proxy(
            ["commit", "-m", commit_msg], cwd=cwd, timeout=30,
        )
        if code != 0:
            msg = out + err
            if "nothing to commit" not in msg.lower():
                print(f"  ❌ git commit 失败: {msg[:200]}")
                return False
            print("  (无变化，跳过提交)")
    else:
        print("  (无新增变更，跳过提交)")

    # 2.5 无新提交 ≠ 无需推送：核对是否残留未推送提交
    ahead = ahead_count(cwd)
    if ahead == 0:
        print("  ✅ 远程已是最新，无需推送")
        return True
    print(f"  → 本地待推送 {ahead} 个提交")

    # 3. pull --rebase（冲突自动 abort）
    if not git_pull_rebase(cwd):
        print("  ⚠️ pull 失败或冲突，跳过 push（commit 已在本地，下次会重试）")
        return False

    # 4. push
    return git_push(cwd)


if __name__ == "__main__":
    # 快速测试代理检测
    proxy = _detect_proxy()
    print(f"代理检测结果: {proxy or '直连'}")
    code, out, err = git_with_proxy(["status", "--short"], timeout=10)
    print(f"git status: {out or '(clean)'}")
