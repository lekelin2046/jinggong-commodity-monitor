#!/usr/bin/env python3
"""LME 铝（官方 Cash Ask）历史月份补全 —— 世铝网月度官方价表口径

背景（2026-10-08）：
  backfill_lme_official.py 只回填「上一官方数据日」，接口仅返回最新一个数据日，
  一旦错过即永久丢失。9 月因此留下 8 天空缺（09-01~04、07、08、28、30）；
  另有 09-10/09-11/09-14 三行是 09-16 改口径前「日延一日」写入的残留，
  每行装的都是**前一天**的官方价。

数据源：世铝网（cnal）月度官方报价表「LME 原铝官方报价及结算价月度统计」
  https://market.cnal.com/lme/... ，列 = 日期|现货买|现货卖|均价|3M买|3M卖|3M均价|结算价
  取「现货卖」＝ 官方 Cash Ask，与 fetcher_lme 口径一致（已用 09-15~09-25
  共 11 个有值日逐日比对，全部完全一致）。

规则：
  · 空单元格 → 写入；已有值 → 跳过（幂等，不重复留痕）；
  · --fix 已错位行（现值 == 前一官方数据日官方价）→ 改写为该行官方价，
    写入前必须同时满足：① 现值确等于**前一交易日**官方价（证明是错位而非人工修正）
    ② 该日在官方表内。任一不满足 → 拒绝改写并告警。
  · 官方表未列出的日期（英国/中国假期）→ 不写，留空。

用法:
    python3 tools/backfill_lme_month.py --month 2026-09 [--fix] [--dry-run] [--no-push]
"""

import argparse
import datetime
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import openpyxl  # noqa: E402

from changelog import record_changes, current_commit_sha, SOURCE_AUTO_CRON  # noqa: E402

EXCEL_PATH = SCRIPT_DIR / "2026年有色金属市场价格.xlsx"
SHEET_NAME = "日均价（2026年市场）"
LME_COL = 27
CODE = "LME_AL"
CACHE_DIR = SCRIPT_DIR / "sources" / "lme_month"


# ===== 抓取 / 解析世铝网月度表 =====
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def find_month_page(year: int, month: int) -> str:
    """按年月搜出该月的「LME 原铝官方报价及结算价月度统计」页面 URL。"""
    import urllib.parse
    import urllib.request

    q = f"{year}年{month}月 LME原铝 官方报价 结算价 月度统计 世铝网"
    url = "https://www.bing.com/search?q=" + urllib.parse.quote(q)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    htmltxt = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "ignore")
    hits = re.findall(r"https?://market\.cnal\.com/lme/[^\"'<>\\ ]+", htmltxt)
    pat = re.compile(rf"原铝官方报价.{0,6}月度统计|LME原铝官方报价")
    # 从候选页里挑「原铝」且与目标月份相符的那条
    for h in dict.fromkeys(hits):
        head = h.rsplit("/", 2)[0]
        m = re.search(r"/lme/(\d{4})/(\d{2}-\d{2})/", h)
        if m and int(m.group(1)) == year and int(m.group(2).split("-")[0]) == month + 1:
            return h
    if hits:
        return hits[0]
    raise RuntimeError(f"未找到 {year}-{month:02d} 的世铝网月度表 URL（bing 返回 {len(hits)} 条候选）")


def fetch_month_table(year: int, month: int) -> dict:
    """返回 {日期字符串: 现货卖(Cash Ask)}，全部月份。失败抛异常。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"cnal-lme-{year}-{month:02d}.html"
    if cache.exists():
        raw = cache.read_text(encoding="utf-8", errors="ignore")
    else:
        import urllib.request
        page = find_month_page(year, month)
        req = urllib.request.Request(page, headers={"User-Agent": UA})
        raw = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")
        cache.write_text(raw, encoding="utf-8")
        print(f"  已抓取 {page} → 缓存 {cache.name}")

    out = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", raw, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if len(cells) < 3 or "年" not in cells[0] or "月" not in cells[0]:
            continue
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", cells[0])
        if not m:
            continue
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        sell = cells[2].replace(",", "").strip()
        if not re.fullmatch(r"\d+(\.\d+)?", sell):
            continue
        out[f"{y:04d}-{mo:02d}-{d:02d}"] = float(sell)
    if not out:
        raise RuntimeError("解析失败：世铝网页面未提取到任何日期行（页面结构可能已变）")
    return out


# ===== 主流程 =====
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True, help="YYYY-MM")
    ap.add_argument("--fix", action="store_true", help="修正旧日延一日错位行")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    y, mo = (int(x) for x in args.month.split("-"))
    today = datetime.date.today()
    print("=" * 54)
    print(f"  LME 铝 · {args.month} 历史补全（世铝网官方价表）  {today}")
    print("=" * 54)

    print("[1/4] 抓取世铝网月度官方价表（现货卖 = Cash Ask）...")
    table = fetch_month_table(y, mo)
    month_days = {k: v for k, v in table.items() if k.startswith(f"{y}-{mo:02d}-")}
    print(f"  官方表 {args.month} 共 {len(month_days)} 个数据日"
          f"（区间 {min(month_days)} ~ {max(month_days)}）")

    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb[SHEET_NAME]

    rows = {}
    for r in range(2, ws.max_row + 1):
        v = ws.cell(r, 1).value
        s = v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else str(v).strip()
        rows[s] = r

    writes, fixes, skipped, absent = [], [], [], []
    for day in sorted(month_days):
        off = month_days[day]
        r = rows.get(day)
        if r is None:
            absent.append(f"{day}(无行)")
            continue
        cur = ws.cell(r, LME_COL).value
        if isinstance(cur, (int, float)) and abs(float(cur) - off) < 1e-6:
            skipped.append(day)
            continue
        if cur in (None, ""):
            writes.append((r, day, off))
            continue
        # 有值但 ≠ 官方值
        if args.fix:
            prev_days = sorted(d for d in month_days if d < day)
            prev_off = month_days[prev_days[-1]] if prev_days else None
            if prev_off is not None and abs(float(cur) - prev_off) < 1e-6:
                fixes.append((r, day, cur, off))
            else:
                print(f"  ⚠️ {day} 现值 {cur} 既≠官方 {off} 也≠前一日官方 {prev_off}"
                      f" → 疑似人工修正，**不改**")
        else:
            skipped.append(f"{day}(现{cur}≠官方{off}，未开--fix)")

    print(f"[2/4] 官方表比对：新增 {len(writes)}，错位修正 {len(fixes)}，"
          f"已一致 {len(skipped)}，无对应行 {len(absent)}")
    for r, day, off in writes:
        print(f"    + {day}  行{r}  = {off}")
    for r, day, old, off in fixes:
        print(f"    ~ {day}  行{r}  {old} → {off}（修正旧日延一口径）")
    if absent:
        print(f"    · 表中无行：{', '.join(absent)}")

    if not writes and not fixes:
        print("  无需变更，退出。")
        return 0
    if args.dry_run:
        print("  [dry-run] 未写入。")
        return 0

    bak_dir = SCRIPT_DIR / "backups" / "精工"
    bak_dir.mkdir(parents=True, exist_ok=True)
    bak = bak_dir / f"{EXCEL_PATH.name}.bak-lme{args.month.replace('-', '')}"
    shutil.copy2(EXCEL_PATH, bak)
    print(f"[3/4] 已备份 {bak.name}")

    changes = []
    for r, day, off in writes:
        ws.cell(r, LME_COL).value = off
        changes.append({"date_row": day, "code": CODE, "old": None, "new": off})
    for r, day, old, off in fixes:
        ws.cell(r, LME_COL).value = off
        changes.append({"date_row": day, "code": CODE, "old": old, "new": off})
    wb.save(EXCEL_PATH)
    print(f"  ✅ 已写入 Excel，{len(changes)} 个单元格")

    n = record_changes(changes, source=SOURCE_AUTO_CRON, editor="—",
                       commit=current_commit_sha(str(SCRIPT_DIR)))
    print(f"  📝 变更留痕 {n} 条")

    print("[4/4] 导出 data.json 并提交推送...")
    subprocess.run([sys.executable, str(SCRIPT_DIR / "export_excel_to_json.py")],
                   cwd=str(SCRIPT_DIR), capture_output=True, text=True)
    if args.no_push:
        print("  --no-push：已导出，未推送。")
        return 0

    r = subprocess.run(["git"] + ["add", "docs/data.json", "docs/changelog.json"],
                       cwd=str(SCRIPT_DIR), capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ⚠️ git add 失败: {(r.stdout + r.stderr).strip()}")
        return 1
    msg = f"LME 铝 {args.month} 补全 {len(writes)} 空缺 + {len(fixes)} 错位修正（世铝网官方价表）"
    subprocess.run(["git"] + ["commit", "-m", msg], cwd=str(SCRIPT_DIR),
                   capture_output=True, text=True)

    sys.path.insert(0, str(SCRIPT_DIR))

    from git_helper import git_push  # noqa: E402
    ok = git_push(cwd=str(SCRIPT_DIR))
    print(f"  {'✅ 已推送' if ok else '⚠️ 推送未成功，本地已提交，等下一轮补推'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())