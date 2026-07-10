#!/usr/bin/env python3
"""
变更日志核心模块（changelog）

提供三个数据写入入口共用的「变更记录器」：
1. 线上 editor.html  → 由前端 JS 实现等效逻辑（见 editor.html）
2. 线下 excel_to_web  → 调用 record_changes()（本模块）
3. 自动 cron daily_update_all → 调用 record_changes()（本模块）

存储：docs/changelog.json，结构 { "records": [ {ts, date_row, code, old, new, source, editor, commit}, ... ] }
每次追加不覆盖历史，随仓库 commit/push，天然可追溯。

用法（Python 侧）：
    from changelog import record_changes, compute_dict_diff
    diffs = compute_dict_diff(before_data, after_data)   # before/after: {date: {code: val}}
    record_changes(diffs, source="manual_xlsx", editor="—")
"""

import json
import datetime
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CHANGELOG_PATH = SCRIPT_DIR / "docs" / "changelog.json"

# 来源枚举（与前端 editor.html 保持一致）
SOURCE_EDITOR = "editor"          # 线上网页手工编辑
SOURCE_MANUAL_XLSX = "manual_xlsx"  # 线下改 xlsx 后推送
SOURCE_AUTO_CRON = "auto_cron"    # 自动抓取覆盖

# 编辑者占位（线下/自动不记具体人）
UNKNOWN_EDITOR = "—"


def _norm(v):
    """将任意单元格值规范化为 float 或 None（空/——/非数字 → None）"""
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        if s in ("", "—", "-", "—", "——"):
            return None
        try:
            return float(s.replace(",", ""))
        except ValueError:
            return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def norm_value(v):
    """公开的值归一化（供外部脚本复用，等价于内部 _norm）"""
    return _norm(v)


def load_changelog() -> dict:
    """读取 changelog.json，不存在则返回空结构"""
    if CHANGELOG_PATH.exists():
        try:
            return json.loads(CHANGELOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"records": []}


def save_changelog(data: dict):
    """写回 changelog.json（原子性：先写临时文件再替换）"""
    CHANGELOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHANGELOG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CHANGELOG_PATH)


def compute_dict_diff(before: dict, after: dict) -> list:
    """对比两个 {date_str: {code: val}} 字典，返回变更列表

    Args:
        before: 变更前的数据（如 git HEAD 版 data.json 的 data 字段）
        after:  变更后的数据
    Returns:
        [ {"date_row": "2026-07-10", "code": "ADC12", "old": 24050.0, "new": 24100.0}, ... ]
        注：old/new 为 float 或 None（None 表示清空/无值）
    """
    diffs = []
    for ds in sorted(set(before) | set(after)):
        b = before.get(ds) or {}
        a = after.get(ds) or {}
        for code in sorted(set(b) | set(a)):
            ov = _norm(b.get(code))
            nv = _norm(a.get(code))
            if ov != nv:
                diffs.append({
                    "date_row": ds,
                    "code": code,
                    "old": ov,
                    "new": nv,
                })
    return diffs


def record_changes(diffs: list, source: str, editor: str = UNKNOWN_EDITOR, commit: str = "") -> int:
    """将一批变更追加写入 changelog.json

    Args:
        diffs: compute_dict_diff 的输出（或手工构造的同结构列表）
        source: SOURCE_EDITOR / SOURCE_MANUAL_XLSX / SOURCE_AUTO_CRON
        editor: 编辑者标识（线上=GitHub login，线下/自动="—"）
        commit: 关联的 git commit sha（尽量提供，失败可为空）
    Returns:
        实际写入的记录条数
    """
    if not diffs:
        return 0
    data = load_changelog()
    # 统一起给这批变更打时间戳
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    for d in diffs:
        data["records"].append({
            "ts": ts,
            "date_row": d["date_row"],
            "code": d["code"],
            "old": d["old"],
            "new": d["new"],
            "source": source,
            "editor": editor or UNKNOWN_EDITOR,
            "commit": commit or "",
        })
    save_changelog(data)
    return len(diffs)


def current_commit_sha(cwd: str = None) -> str:
    """尽力获取当前 HEAD commit sha（用于关联记录到具体提交）"""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd or str(SCRIPT_DIR),
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


if __name__ == "__main__":
    # 快速自检
    before = {"2026-07-10": {"ADC12": 24050, "A380": 25950}}
    after = {"2026-07-10": {"ADC12": 24100, "A380": 25950, "A356": 23200}}
    diffs = compute_dict_diff(before, after)
    print("diffs:", diffs)
    n = record_changes(diffs, source=SOURCE_MANUAL_XLSX, editor="—")
    print(f"写入 {n} 条；当前共 {len(load_changelog()['records'])} 条")
    # 清理自检数据
    data = load_changelog()
    data["records"] = []
    save_changelog(data)
    print("自检完成，已清空测试记录")
