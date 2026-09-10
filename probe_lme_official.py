"""LME 官网官方价抓取探针（方案 A 可行性验证 · 最终版）

结论（2026-09-10 实验确认）：
  - lme.com API 路径有 Cloudflare 拦截：纯 requests 403；Playwright ctx.request 也 403
    （CF 校验浏览器指纹，无 cf_clearance cookie 可导出复用）
  - 唯一可行：headed Chrome（持久化 profile）打开页面过 CF 后，
    【页面内 fetch()】调用官方 day-delayed API —— 会话内 100% 成功
  - API: /api/trading-data/day-delayed?datasourceId=5ec6a4fc-6bd2-4fb0-b7f5-6ac0f3e68d1d
    返回 GroupedColumnTitles（Cash/3 month/15 month/Dec27/Dec28/Dec29 × Bid/Ask）
    + Rows（MAL0 Aluminium 等），DateOfData=价格所属交易日（日延一日）

用法：
  unset NODE_OPTIONS && python probe_lme_official.py [--attempts 2] [--hold 5]

产出：stdout 打印 Aluminium Cash Bid/Ask；data/lme_official_latest.json 存原始响应
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT = Path(__file__).resolve().parent
PROFILE_DIR = PROJECT / "cookies" / "lme_official_profile"
OUT_JSON = PROJECT / "data" / "lme_official_latest.json"

PAGE_URL = "https://www.lme.com/en/Metals/Non-ferrous/LME-Aluminium"
API_URL = ("https://www.lme.com/api/trading-data/day-delayed"
           "?datasourceId=5ec6a4fc-6bd2-4fb0-b7f5-6ac0f3e68d1d")


def is_cf(page) -> bool:
    try:
        return "just a moment" in (page.title() or "").lower()
    except Exception:
        return True


def fetch_official(pw, hold_s: float):
    """单次尝试：headed 打开页面 → 等 CF → 页面内 fetch API → 解析。成功返回 doc dict"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 启动 headed Chrome ...")
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        channel="chrome",
        viewport={"width": 1280, "height": 800},
        args=["--disable-blink-features=AutomationControlled"],
    )
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(PAGE_URL, timeout=60000, wait_until="domcontentloaded")
        deadline = time.time() + 90
        while time.time() < deadline and is_cf(page):
            time.sleep(3)
        if is_cf(page):
            print("  Cloudflare 未通过（如需人机验证请手动点击后重试）")
            return None

        res = page.evaluate(
            """async (url) => {
                const r = await fetch(url, {credentials: 'include',
                    headers: {'Accept': 'application/json'}});
                return {status: r.status, body: await r.text()};
            }""", API_URL)
        print(f"  页面内 fetch status = {res['status']}")
        if res["status"] != 200:
            return None
        doc = json.loads(res["body"])
        OUT_JSON.parent.mkdir(exist_ok=True)
        OUT_JSON.write_text(res["body"], encoding="utf-8")
        return doc
    finally:
        if hold_s:
            time.sleep(hold_s)
        ctx.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempts", type=int, default=2)
    ap.add_argument("--hold", type=float, default=2, help="关闭浏览器前停留秒数")
    args = ap.parse_args()

    for i in range(1, args.attempts + 1):
        print(f"===== 尝试 #{i} =====")
        with sync_playwright() as pw:
            doc = fetch_official(pw, args.hold)
        if doc:
            print(f"  DateOfData = {doc['DateOfData']}")
            for row in doc["Rows"]:
                vals = row["Values"]
                cash_bid = vals[0] if len(vals) > 0 else "-"
                cash_ask = vals[1] if len(vals) > 1 else "-"
                print(f"  {row['RowTitle']:<18} Cash Bid={cash_bid:>10}  Ask={cash_ask:>10}")
            al = next((r for r in doc["Rows"] if r["RowTitle"] == "Aluminium"), None)
            if al and al["Values"][1] != "-":
                print(f"\n✅ 官方 Aluminium Cash Ask = {al['Values'][1]} USD/t "
                      f"(数据日 {doc['DateOfData'][:10]})，原始响应已存 {OUT_JSON}")
                return 0
            print("  Aluminium Cash Ask 缺失（'-'）")
            return 1
        print(f"  第 {i} 次未成功" + ("，10s 后重试..." if i < args.attempts else ""))
        time.sleep(10)
    print(f"\n❌ {args.attempts} 次尝试均未成功")
    return 1


if __name__ == "__main__":
    sys.exit(main())
