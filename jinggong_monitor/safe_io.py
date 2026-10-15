#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""safe_io.py — 数据落盘安全层（原子写 + 写前备份）
====================================================================

为什么需要
------------------------------------------------------------------
本项目生产路径上的落盘点原先都是「直接覆盖写」：
`open(path, "w")` + `json.dump`、`Path.write_text(...)`、openpyxl 的 `wb.save(path)`。

这三种写法都会**先把目标文件截断到 0 字节，再逐块写入**。若进程在
「已截断、未写满」之间被杀（前台超时 / 断电 / Ctrl-C / OOM），目标文件就变成
截断的半个文件 —— JSON 不可解析、xlsx 是损坏的压缩包，看板当场白屏，
且没有可用的回滚点。xlsx 尤为脆弱：它是 zip 容器，损坏后 Excel 直接拒绝打开。

本模块把写入改为三步：
  1. 写入**同目录**的临时文件（必须同文件系统，第 3 步才是原子操作）
  2. `flush()` + `os.fsync()` 确保内容真正落盘，而不是停留在页缓存
  3. `os.replace()` 原子替换 —— POSIX 保证同文件系统内 rename 的原子性，
     替换瞬时完成，**不存在「半截文件」的中间态**

失败时原文件保持完好，只是多了一个隐藏的临时文件残留。

行为等价性
------------------------------------------------------------------
本模块**不改变写出的内容**：`json.dumps` 的 `ensure_ascii` / `indent` /
`sort_keys` 全部由调用方原样传入，产出的字节与改造前完全一致。
唯一新增产物是备份文件。

备份策略
------------------------------------------------------------------
  · 命名 `<原名>.bak-YYYYMMDD`，默认同一自然日只留一份
    （即「当日首次写入前」的状态，已足以覆盖「写坏后回滚」的需求）
  · 需要一天多份时传 `same_day_max=2`，超出的追加 `-HHMMSS` 后缀
  · 首次创建目标文件（原文件不存在）不产生备份
  · `backups/` 已在 .gitignore 中，不会污染仓库

临时文件命名
------------------------------------------------------------------
  · JSON：`.data.1234.tmp`            —— 命中 .gitignore 的 `*.tmp` 规则
  · xlsx：`.xxx.1234.tmp.xlsx`        —— openpyxl 强制要求 .xlsx 后缀，
    故不能省略；该名命中 `*.xlsx` 规则，同样不入库

用法
------------------------------------------------------------------
    from safe_io import atomic_write_json, atomic_save_workbook

    atomic_write_json(out_path, doc, indent=1,
                      backup=True, backup_dir=ROOT / "backups" / "mand")
    atomic_save_workbook(wb, excel_path,
                         backup=True, backup_dir=ROOT / "backups" / "精工")
"""
from __future__ import annotations

import json
import os
import shutil
import stat
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

__all__ = [
    "snapshot",
    "atomic_write_bytes",
    "atomic_write_text",
    "atomic_write_json",
    "atomic_save_workbook",
]

PathLike = Union[str, Path]


def _tmp_path(path: Path, *, keep_suffix: bool) -> Path:
    """构造同目录临时文件路径。带 pid，避免并发时互相踩。"""
    if keep_suffix:
        return path.with_name(f".{path.stem}.{os.getpid()}.tmp{path.suffix}")
    return path.with_name(f".{path.stem}.{os.getpid()}.tmp")


def _cleanup(tmp: Path) -> None:
    try:
        tmp.unlink()
    except OSError:
        pass


def _inherit_mode(dst: Path, tmp: Path) -> None:
    """让临时文件继承目标文件原有的权限位。

    必要性：临时文件由 umask 决定权限（本机 022 -> 644），而主 Excel 是 600。
    若不处理，原子替换会把 600 悄悄放宽成 644 —— 属于本次改造引入的行为变化。
    """
    try:
        mode = stat.S_IMODE(dst.stat().st_mode)
    except OSError:
        return  # 目标不存在（首次创建），保持默认权限即可
    try:
        os.chmod(tmp, mode)
    except OSError:
        pass


def snapshot(path: PathLike,
             backup_dir: PathLike,
             *,
             same_day_max: int = 1) -> Optional[Path]:
    """把现有文件快照到 backup_dir。

    文件不存在（首次创建）返回 None —— 无内容可备份。
    same_day_max=1（默认）时，同一自然日只保留一份。
    """
    src = Path(path)
    if not src.exists():
        return None

    dst_dir = Path(backup_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)

    dst = dst_dir / f"{src.name}.bak-{datetime.now().strftime('%Y%m%d')}"
    if dst.exists():
        if same_day_max <= 1:
            return dst  # 当日已备份，跳过
        dst = dst_dir / (
            f"{src.name}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )

    shutil.copy2(src, dst)
    return dst


def atomic_write_bytes(path: PathLike,
                       data: bytes,
                       *,
                       backup: bool = False,
                       backup_dir: Optional[PathLike] = None,
                       same_day_max: int = 1) -> None:
    """字节级原子写。"""
    dst = Path(path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if backup and backup_dir is not None:
        snapshot(dst, backup_dir, same_day_max=same_day_max)

    tmp = _tmp_path(dst, keep_suffix=False)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        _inherit_mode(dst, tmp)
        os.replace(tmp, dst)
    except Exception:
        _cleanup(tmp)
        raise


def atomic_write_text(path: PathLike,
                      text: str,
                      *,
                      encoding: str = "utf-8",
                      backup: bool = False,
                      backup_dir: Optional[PathLike] = None,
                      same_day_max: int = 1) -> None:
    """文本原子写。"""
    atomic_write_bytes(path, text.encode(encoding),
                       backup=backup, backup_dir=backup_dir,
                       same_day_max=same_day_max)


def atomic_write_json(path: PathLike,
                      data: Any,
                      *,
                      indent: Optional[int] = 1,
                      sort_keys: bool = False,
                      ensure_ascii: bool = False,
                      backup: bool = False,
                      backup_dir: Optional[PathLike] = None,
                      same_day_max: int = 1) -> None:
    """JSON 原子写。序列化参数与调用方传入的一致，产出字节不变。"""
    text = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent,
                      sort_keys=sort_keys)
    atomic_write_text(path, text,
                      backup=backup, backup_dir=backup_dir,
                      same_day_max=same_day_max)


def atomic_save_workbook(wb,
                         path: PathLike,
                         *,
                         backup: bool = False,
                         backup_dir: Optional[PathLike] = None,
                         same_day_max: int = 1) -> None:
    """openpyxl 工作簿的原子保存。

    `wb.save()` 同样是「截断后重写」，且 xlsx 为 zip 容器 —— 半截写入得到的是
    损坏压缩包。此处先存到同目录临时文件（保留 .xlsx 后缀，openpyxl 会校验后缀），
    再原子替换。
    """
    dst = Path(path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if backup and backup_dir is not None:
        snapshot(dst, backup_dir, same_day_max=same_day_max)

    tmp = _tmp_path(dst, keep_suffix=True)
    try:
        wb.save(str(tmp))
        _inherit_mode(dst, tmp)
        os.replace(tmp, dst)
    except Exception:
        _cleanup(tmp)
        raise
