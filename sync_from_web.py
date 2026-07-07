#!/usr/bin/env python3
"""
同步线上 data.json → 本地 Excel

同事在 editor.html 在线编辑后数据已提交到 GitHub，
运行此脚本：git pull → 读 data.json → 写 Excel → 本地表同步。

用法: python3 sync_from_web.py
"""

import sys, os, json, datetime, subprocess
from pathlib import Path

try:
    import openpyxl
except ImportError:
    print("ERROR: openpyxl not installed. Run: pip install openpyxl", file=sys.stderr)
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent
EXCEL_PATH = SCRIPT_DIR / "2026年有色金属市场价格.xlsx"
JSON_PATH = SCRIPT_DIR / "docs" / "data.json"
SHEET_NAME = "日均价（2026年市场）"

COLUMN_MAP = {
    2: "ADC12", 3: "A380", 4: "AlSi9Cu3", 5: "A356",
    6: "A00_AL", 7: "CU", 8: "SI_441", 9: "SI_3303",
    10: "MG", 11: "MN", 12: "SI_331",
    13: "Wenxi_MG", 14: "AM60B", 15: "AZ91D",
    16: "W", 17: "WTI",
}
CODE_TO_COL = {v: k for k, v in COLUMN_MAP.items()}


def git_pull():
    """拉取最新代码（含同事在线编辑的 data.json）"""
    print("→ git pull ...")
    result = subprocess.run(
        ["git", "pull"],
        cwd=str(SCRIPT_DIR),
        capture_output=True, text=True,
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(f"⚠️  git pull 失败: {result.stderr}", file=sys.stderr)
        return False
    return True


def sync_to_excel():
    """读 data.json → 写入 Excel"""
    if not JSON_PATH.exists():
        print(f"ERROR: {JSON_PATH} 不存在", file=sys.stderr)
        return False

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb[SHEET_NAME]

    # 找日期列映射: date_str -> row_number
    date_rows = {}
    for r in range(2, ws.max_row + 1):
        v = ws.cell(r, 1).value
        if isinstance(v, datetime.datetime):
            ds = v.strftime("%Y-%m-%d")
            date_rows[ds] = r
        elif isinstance(v, str) and v.strip() and not v.startswith("备注"):
            # Excel 可能存成文本格式的日期
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
                try:
                    dt = datetime.datetime.strptime(v.strip(), fmt)
                    date_rows[dt.strftime("%Y-%m-%d")] = r
                    break
                except ValueError:
                    continue

    updated = 0
    for ds, row_data in sorted(data.get("data", {}).items()):
        if ds not in date_rows:
            print(f"  ⏭  跳过 {ds}（Excel 中无此日期行）")
            continue
        r = date_rows[ds]
        for code, val in row_data.items():
            if val is None:
                continue
            col = CODE_TO_COL.get(code)
            if col is None:
                continue
            existing = ws.cell(r, col).value
            if existing != val:
                ws.cell(r, col).value = val
                updated += 1

    wb.save(EXCEL_PATH)
    print(f"✓ 写入完成: 更新 {updated} 个单元格")
    return True


if __name__ == "__main__":
    print(f"=== 同步线上数据 → 本地 Excel ===\n")
    if not git_pull():
        sys.exit(1)
    if not sync_to_excel():
        sys.exit(1)
    print(f"\n✓ 完成！Excel 已更新：{EXCEL_PATH.name}")
    print(f"  打开 Excel 确认后，运行 python3 excel_to_web.py 推回线上")
