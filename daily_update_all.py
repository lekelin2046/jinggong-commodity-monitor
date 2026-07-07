#!/usr/bin/env python3
"""
全品种每日抓取脚本（16项）
覆盖: ccmn(7) + SMM(7) + 钨粉(1) + WTI(1) = 16

用法: python3 daily_update_all.py
"""

import sys, os, json, datetime, asyncio, re, subprocess
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    import openpyxl
except ImportError:
    print("ERROR: openpyxl not installed", file=sys.stderr)
    sys.exit(1)

# ===== 常量 =====
EXCEL_PATH = SCRIPT_DIR / "2026年有色金属市场价格.xlsx"
SHEET_NAME = "日均价（2026年市场）"
TODAY = datetime.date.today().isoformat()

# Excel 列 → (品种代码, 来源)
COL_MAP = {
    2:  ("ADC12",    "smm"),  3:  ("A380",      "smm"),
    4:  ("AlSi9Cu3", "smm"),  5:  ("A356",      "smm"),
    6:  ("A00_AL",   "ccmn"), 7:  ("CU",        "ccmn"),
    8:  ("SI_441",   "ccmn"), 9:  ("SI_3303",   "ccmn"),
    10: ("MG",       "ccmn"), 11: ("MN",        "ccmn"),
    12: ("SI_331",   "ccmn"),
    13: ("Wenxi_MG", "smm"),  14: ("AM60B",     "smm"),
    15: ("AZ91D",    "smm"),
    16: ("W",        "web"),  17: ("WTI",       "wti"),
}

# CCMN 返回 key → 品种代码
CCMN_KEYS = {
    "A00_AL":       "A00_AL",
    "CU":           "CU",
    "SI_553_331_AVG":  "SI_441",
    "SI_3303_2202_MIN": "SI_3303",
    "SI_553_331_MAX":  "SI_331",
    "MG":           "MG",
    "MN":           "MN",
}


def get_row(ws):
    """查找或创建今天的数据行"""
    td = datetime.date.today()
    for r in range(2, ws.max_row + 1):
        v = ws.cell(r, 1).value
        if isinstance(v, datetime.datetime) and v.date() == td:
            return r
    nr = ws.max_row + 1
    ws.cell(nr, 1).value = td
    return nr


# ===== CCMN 抓取 =====
async def fetch_ccmn() -> dict:
    print("  ccmn 长江现货...", end="", flush=True)
    from jinggong_monitor.fetcher_ccmn import CcmnFetcher
    fetcher = CcmnFetcher()
    raw = fetcher.fetch()
    result = {}
    for ccmn_key, code in CCMN_KEYS.items():
        if ccmn_key in raw and raw[ccmn_key] is not None:
            result[code] = raw[ccmn_key]
    print(f" {len(result)} 品种")
    return result


# ===== SMM 抓取 =====
async def fetch_smm() -> dict:
    print("  SMM 上海有色...", end="", flush=True)
    from jinggong_monitor.fetcher_smm import _fetch_smm_raw
    prices = await _fetch_smm_raw()
    mapped = {}
    for k, v in prices.items():
        mapped["Wenxi_MG" if k == "WenxiMG" else k] = v
    print(f" {len(mapped)} 品种")
    return mapped


# ===== 钨粉 =====
def fetch_tungsten() -> dict:
    print("  中钨在线（钨粉）...", end="", flush=True)
    try:
        import requests as rq
        url = "https://www.chinatungsten.com/price/"
        resp = rq.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        })
        for line in resp.text.split("\n"):
            if "钨粉" in line or "W" in line:
                nums = re.findall(r"[\d,.]+", line)
                if nums:
                    v = float(nums[0].replace(",", ""))
                    print(f" {v} 元/公斤")
                    return {"W": v}
        print(" 未匹配到")
        return {}
    except Exception as e:
        print(f" 失败: {e}")
        return {}


# ===== WTI =====
def fetch_wti() -> dict:
    """获取WTI估算（CL实时价 or SC原油/7.15）"""
    print("  WTI 原油...", end="", flush=True)
    try:
        import akshare as ak
        df = ak.futures_foreign_commodity_realtime(symbol="CL")
        price = round(float(df.iloc[0]["最新价"]), 2)
        print(f" {price} USD (CL)")
        return {"WTI": price}
    except Exception:
        pass
    try:
        import akshare as ak
        dt = TODAY.replace("-", "")
        df = ak.futures_main_sina(symbol="SC0", start_date=dt, end_date=dt)
        close = float(df.iloc[-1]["收盘价"])
        price = round(close / 7.15, 2)
        print(f" {price} USD (SC/7.15)")
        return {"WTI": price}
    except Exception as e:
        print(f" 失败: {e}")
        return {}


# ===== 写 Excel =====
def write_excel(all_prices: dict) -> int:
    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb[SHEET_NAME]
    row = get_row(ws)
    written, skipped = [], []
    for col, (code, src) in COL_MAP.items():
        if code in all_prices and all_prices[code] is not None:
            ws.cell(row, col).value = all_prices[code]
            written.append(code)
        else:
            skipped.append(code)
    wb.save(EXCEL_PATH)
    print(f"  行 {row}: 写入 {len(written)}/16 项")
    if skipped:
        print(f"  缺: {', '.join(skipped)}")
    return row


# ===== 导出 + Push =====
def export_and_push(row: int):
    print("  导出 data.json...")
    subprocess.run([sys.executable, str(SCRIPT_DIR / "export_excel_to_json.py")],
        cwd=str(SCRIPT_DIR), capture_output=True, text=True)
    cmds = [
        ["git", "add", "docs/data.json"],
        ["git", "commit", "-m", f"全品种更新 {TODAY} row={row}"],
        ["git", "push"],
    ]
    for cmd in cmds:
        r = subprocess.run(cmd, cwd=str(SCRIPT_DIR), capture_output=True, text=True)
        msg = r.stdout.strip() or r.stderr.strip()
        if r.returncode != 0 and "nothing to commit" not in msg.lower():
            print(f"  ⚠️ {' '.join(cmd[:2])}: {msg}")
            return False
    print("  ✅ 推送成功")
    return True


async def main():
    print(f"\n{'='*50}")
    print(f"  全品种抓取 · {TODAY}")
    print(f"{'='*50}\n")

    all_prices = {}

    all_prices.update(await fetch_ccmn())
    print()
    all_prices.update(await fetch_smm())
    print()
    tungsten = fetch_tungsten()
    if tungsten: all_prices.update(tungsten)
    wti = fetch_wti()
    if wti: all_prices.update(wti)
    print()

    print(f"[写表] ", end="")
    row = write_excel(all_prices)

    print(f"[发布] ", end="")
    export_and_push(row)

    print(f"\n  已更新 {len(all_prices)}/16 品种")
    print(f"  看板: https://lekelin2046.github.io/jinggong-commodity-monitor/\n")


if __name__ == "__main__":
    asyncio.run(main())
