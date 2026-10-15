#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sync_excel_mirror.py — 主表与客户原始表 → 私有镜像仓库（异地备份）

背景
----
`2026年有色金属市场价格.xlsx`（业务底稿，被 8 处常量引用）以及 `sources/` 下的
客户原始表，均被主仓库 `.gitignore` 的 `*.xlsx` 规则排除，**只存在于本机**。
此前唯一保障是 `backups/`（同一块硬盘），磁盘故障即同时消失、GitHub 上一份没有。

方案
----
复制到独立镜像仓库 `~/Desktop/AI/jinggong-commodity-backup`（remote 指向
`lekelin2046/jinggong-commodity-backup`，**私有**）后提交推送。该仓库与主仓库
完全隔离：不受主仓库 `.gitignore` 影响，也不会让公开的主仓库膨胀。

设计约束
--------
1. **绝不抛出**：本脚本由 15:00 生产主流程调用，任何异常只降级为告警，不得
   中断抓取与发布（对齐铁律 2「单源故障不得中止整轮」）。
2. **单向**：只从项目 → 镜像。不反向、不删除镜像中已有文件。
3. **低频 + 自愈**：距上次备份 ≥ `MIN_INTERVAL_DAYS`(7) 天才执行；某周主流程
   失败时下一次调用会自动补上（因为是按"距上次天数"判断，不依赖固定星期）。
4. **复制后校验**：逐文件比对 sha256，不一致即视为失败、不提交。
5. 落盘走 `safe_io.atomic_write_bytes`（铁律 9）；推送复用 `git_helper` 的
   代理探测与重试（直连 GitHub 是间歇性可用的，必须重试）。

用法
----
    python sync_excel_mirror.py              # 按周期判断，未到周期则跳过
    python sync_excel_mirror.py --force      # 忽略周期，立即备份
    python sync_excel_mirror.py --dry-run    # 只显示会做什么，不写盘不推送
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Tuple

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

# 镜像仓库位置（可用环境变量覆盖，便于换机或迁移）
MIRROR_DIR = Path(os.environ.get("JINGGONG_MIRROR_DIR")
                  or (Path.home() / "Desktop" / "AI" / "jinggong-commodity-backup"))

# 备份对象
MAIN_EXCEL = "2026年有色金属市场价格.xlsx"
SOURCE_DIRS = ("sources",)
EXTS = {".xlsx", ".xls", ".csv", ".tsv"}
# 不参与备份的目录（历史归档，非活数据）
EXCLUDE_PARTS = {"_legacy", "_archive", "__pycache__"}

MIN_INTERVAL_DAYS = 7


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _last_backup_date() -> Optional[date]:
    """镜像仓库最后一次提交的自然日；无仓库/无提交返回 None。"""
    if not (MIRROR_DIR / ".git").is_dir():
        return None
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%cd", "--date=short"],
            cwd=str(MIRROR_DIR), capture_output=True, text=True, timeout=20,
        )
        if r.returncode == 0 and r.stdout.strip():
            return datetime.strptime(r.stdout.strip(), "%Y-%m-%d").date()
    except Exception:
        pass
    return None


def _due(force: bool, min_days: int) -> Tuple[bool, str]:
    if force:
        return True, "强制备份"
    last = _last_backup_date()
    if last is None:
        return True, "镜像仓库尚无备份记录，首次执行"
    days = (date.today() - last).days
    if days >= min_days:
        return True, f"距上次备份 {days} 天（阈值 {min_days} 天）"
    return False, f"距上次备份 {days} 天未达阈值 {min_days} 天，本轮跳过"


# --------------------------------------------------------------------------
# 收集 / 复制
# --------------------------------------------------------------------------
def _collect() -> List[Tuple[Path, Path]]:
    """返回 [(源绝对路径, 镜像内相对路径), ...]，按相对路径排序。"""
    items: List[Tuple[Path, Path]] = []

    main = PROJECT_DIR / MAIN_EXCEL
    if main.is_file():
        items.append((main, Path(MAIN_EXCEL)))

    for d in SOURCE_DIRS:
        base = PROJECT_DIR / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix.lower() not in EXTS:
                continue
            # 跳过 Excel 打开时的锁文件、隐藏文件、归档目录
            if p.name.startswith("~$") or p.name.startswith("."):
                continue
            if EXCLUDE_PARTS & set(p.parts):
                continue
            items.append((p, p.relative_to(PROJECT_DIR)))

    items.sort(key=lambda x: str(x[1]))
    return items


def _mirror_one(src: Path, dst: Path, dry_run: bool) -> str:
    """复制单个文件，返回 'unchanged' | 'updated' | 'created'。"""
    if dst.is_file() and _sha256(src) == _sha256(dst):
        return "unchanged"

    status = "updated" if dst.is_file() else "created"
    if dry_run:
        return status

    from jinggong_monitor.safe_io import atomic_write_bytes  # noqa: E402

    # 原子写：镜像里的副本同样不允许被写坏
    atomic_write_bytes(dst, src.read_bytes())

    # 复制后校验，不一致即视为失败
    if _sha256(src) != _sha256(dst):
        raise IOError(f"复制后校验失败: {dst}")
    return status


def _has_remote_main() -> bool:
    """本地是否已存在 origin/main 引用（= 之前成功推过）。"""
    r = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "origin/main"],
                       cwd=str(MIRROR_DIR), capture_output=True, text=True,
                       timeout=20)
    return r.returncode == 0


def _needs_push() -> bool:
    """本地是否有尚未推送的提交（含「远程仍为空仓库」的首次场景）。

    ⚠️ 不能只看「本次有没有新变化」——上次推送失败时本地已有 commit，
    下一次运行时源文件无变化、暂存区为空，若直接判定「无需推送」，
    那个提交将永远滞留本地，异地副本静默停留在旧版本。
    """
    if not _has_remote_main():
        r = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "HEAD"],
                           cwd=str(MIRROR_DIR), capture_output=True, text=True,
                           timeout=20)
        return r.returncode == 0
    r = subprocess.run(["git", "rev-list", "--count", "origin/main..HEAD"],
                       cwd=str(MIRROR_DIR), capture_output=True, text=True,
                       timeout=20)
    return r.returncode == 0 and r.stdout.strip() not in ("", "0")


def _push() -> bool:
    """推送镜像仓库。

    ⚠️ 首次推送必须带 `-u`：远程还是空仓库时本地没有 `origin/main` 引用，
    `git_helper.ahead_count()` 的 `rev-list origin/main..HEAD` 会因
    "ambiguous argument" 报错并返回 0，导致 `publish_to_github()` 误判为
    「远程已是最新，无需推送」而静默跳过（首次执行时实测踩到）。
    """
    from git_helper import git_push, git_with_proxy  # noqa: E402

    if not _has_remote_main():
        code, out, err = git_with_proxy(
            ["-c", "http.lowSpeedLimit=10", "-c", "http.lowSpeedTime=45",
             "push", "-u", "origin", "main"],
            cwd=str(MIRROR_DIR), timeout=180,
        )
        if code == 0:
            print("  ✅ 首次推送成功（已设置上游）")
            return True
        tail = (err or out).strip().splitlines()
        print(f"  ⏳ 首次推送失败：{tail[-1][:110] if tail else '未知错误'}")

    # 日常路径：复用主项目的代理探测 + 重试（直连 GitHub 间歇性可用）
    return git_push(cwd=str(MIRROR_DIR))


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def sync(force: bool = False,
         dry_run: bool = False,
         min_interval_days: int = MIN_INTERVAL_DAYS) -> Tuple[bool, str]:
    """执行一次异地备份。**永不抛出异常**，返回 (ok, 摘要信息)。"""
    try:
        due, why = _due(force, min_interval_days)
        if not due:
            return True, why

        if not MIRROR_DIR.is_dir():
            return False, (f"镜像目录不存在：{MIRROR_DIR}"
                           "（请先 clone https://github.com/lekelin2046/"
                           "jinggong-commodity-backup）")

        items = _collect()
        if not items:
            return False, "未找到任何待备份文件"

        stats = {"created": 0, "updated": 0, "unchanged": 0}
        changed: List[str] = []
        for src, rel in items:
            st = _mirror_one(src, MIRROR_DIR / rel, dry_run)
            stats[st] += 1
            if st != "unchanged":
                changed.append(f"{st[0].upper()}:{rel}")

        total = len(items)
        brief = (f"{total} 个文件（新 {stats['created']} / 更新 {stats['updated']}"
                 f" / 未变 {stats['unchanged']}）")

        if dry_run:
            return True, f"[dry-run] {why}；将同步 {brief}"

        # 提交（add → commit）。⚠️ 无新变更 ≠ 无需推送：本地可能残留此前已提交
        # 但未推送的 commit（如上次推送失败），故下面另用 _needs_push() 核对。
        from git_helper import git_with_proxy  # noqa: E402

        today = date.today().isoformat()
        msg = (f"backup: {today} 主表与客户原始表\n\n"
               f"触发：{why}\n"
               f"同步 {total} 个文件（新 {stats['created']} / "
               f"更新 {stats['updated']}），明细：\n"
               + "\n".join(f"  - {c}" for c in changed[:20])
               + ("\n  ..." if len(changed) > 20 else ""))

        code, out, err = git_with_proxy(["add", "-A"],
                                        cwd=str(MIRROR_DIR), timeout=60)
        if code != 0:
            return False, f"git add 失败：{(err or out).strip()[:160]}"

        staged = git_with_proxy(["diff", "--cached", "--quiet"],
                                cwd=str(MIRROR_DIR), timeout=30)[0] != 0
        if staged:
            code, out, err = git_with_proxy(["commit", "-m", msg],
                                            cwd=str(MIRROR_DIR), timeout=60)
            if code != 0:
                return False, f"git commit 失败：{(err or out).strip()[:160]}"

        if not _needs_push():
            return True, f"{why}；{brief}，内容无变化，远程已是最新"

        if not _push():
            return False, f"{brief}，本地已提交，但推送失败（下次会自动重推）"

        return True, f"{why}；{brief} 已推送至私有备份仓库"

    except Exception as e:  # noqa: BLE001  生产主流程调用，必须吞掉一切异常
        return False, f"异常：{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description="主表与客户原始表 → 私有镜像仓库")
    ap.add_argument("--force", action="store_true", help="忽略周期判断，立即备份")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写盘不推送")
    ap.add_argument("--days", type=int, default=MIN_INTERVAL_DAYS,
                    help=f"备份间隔天数（默认 {MIN_INTERVAL_DAYS}）")
    args = ap.parse_args()

    ok, msg = sync(force=args.force, dry_run=args.dry_run,
                   min_interval_days=args.days)
    print(("✓ " if ok else "✗ ") + msg)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
