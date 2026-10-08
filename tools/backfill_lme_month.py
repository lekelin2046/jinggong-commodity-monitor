#!/usr/bin/env python3
"""LME 铝（官方 Cash Ask）历史月份补全 —— 世铝网月度官方价表口径

背景（2026-10-08）：
  backfill_lme_official.py 只回填「上一官方数据日」，接口仅返回最新一个数据日，
  一旦错过即永久丢失。9 月因此留下 8 天空缺（09-01~04、07、08、28、30）；
  另有 09-10/09-11/09-14 三行是 09-16 改口径前「日延一日」写入的残留，
  每行装的都是**前一天**的官方价。
  → 本脚本同日固化为**月度例行核验**：每月对上个月每个官方数据日逐日复核，
    把「错了才发现」变成「每月自动发现」。

数据源：世铝网（cnal）月度官方报价表「LME 原铝官方报价及结算价月度统计」
  https://market.cnal.com/lme/... ，列 = 日期|现货买|现货卖|均价|3M买|3M卖|3M均价|结算价
  取「现货卖」＝ 官方 Cash Ask，与 fetcher_lme 口径一致（已用 09-15~09-25
  共 11 个有值日逐日比对，全部完全一致）。
  URL 定位走**世铝网自己的 LME 行情索引页**（索引只含当月与上月，恰好够用），
  按标题「YYYY年M月LME原铝…」匹配，不靠搜索引擎、不靠 URL 路径推月份，跨年不会错。

规则：
  · **默认只读核验**——逐日比对，输出「一致 / 空缺待补 / 日延一错位 /
    其他偏差 / 表中无行」五类清单并给出结论，**不写任何数据**；
  · 加 `--apply` 才落库：空单元格 → 补入；日延一错位 → 改写。后者必须满足
    「现值 == **前一官方数据日**官方价」（证明是旧错位而非人工修正），否则
    归入「其他偏差」**一律不改**并告警；
  · 幂等 —— 已一致则跳过，不重复写、不重复留痕；
  · 官方表未列出的日期（英国/中国假期）→ 不写，留空。

用法:
    # 核验上一自然月（只读，月初例行）
    python3 tools/backfill_lme_month.py
    # 核验指定月 / 确认后写入 / 只导出不推送
    python3 tools/backfill_lme_month.py --month 2026-09
    python3 tools/backfill_lme_month.py --month 2026-09 --apply
    python3 tools/backfill_lme_month.py --month 2026-09 --apply --no-push
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


IDX_URL = "https://market.cnal.com/lme/"


def find_month_page(year: int, month: int) -> str:
    """定位该月「LME 原铝官方报价及结算价月度统计」页 URL。

    2026-10-08 改造：原先靠 Bing 搜索定位，但 Bing 会把结果里的月份数字当
    自己的月份去比对（`month + 1` 的写法在跨年时必错），且搜索结果页结构变动
    即失效。改用**世铝网自己的 LME 行情索引页**——稳定、且只含当月与上月，
    对「月度核验上一月」这个场景刚好够用；标题里带「2026年9月」字样，
    按**标题**匹配而非按 URL 路径推月份，跨年不会再错。
    """
    idx = _get(IDX_URL).decode("utf-8", "ignore")

    # 标题形如「2026年9月LME原铝官方报价及结算价月度统计」
    want = re.compile(rf"{year}年{month}月\s*LME原铝官方报价及结算价月度统计")
    for m in re.finditer(
            r'<a[^>]+href="(https://market\.cnal\.com/lme/[^"]+\.shtml)"[^>]*>(.*?)</a>',
            idx, re.S):
        title = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        if want.search(title.replace(" ", "")):
            return m.group(1)
    raise RuntimeError(
        f"索引页未列出 {year}-{month:02d} 的原铝月度统计表（可能尚未发布，通常次月 1 日出）")


def _get(url: str, timeout: int = 60) -> bytes:
    """GET 并返回**解压后**的字节。

    2026-10-08 修复：世铝网对 urllib 请求返回 **gzip 压缩体**（`1f 8b` 魔数），
    urllib 不会像 curl 那样自动解压，直接 .decode('utf-8') 会得到乱码 →
    解析出 0 行，误报「页面结构已变」。故此处显式按 Content-Encoding 解压。
    """
    import gzip
    import urllib.request
    import zlib

    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    resp = urllib.request.urlopen(req, timeout=timeout)
    data = resp.read()
    enc = (resp.headers.get("Content-Encoding") or "").lower()
    if "gzip" in enc or data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    elif "deflate" in enc:
        try:
            data = zlib.decompress(data)
        except zlib.error:
            data = zlib.decompress(data, -zlib.MAX_WBITS)
    return data


def fetch_month_table(year: int, month: int) -> dict:
    """返回 {日期字符串: 现货卖(Cash Ask)}。失败抛异常。

    ⚠️ 缓存只存**解压后**的文本；早先版本可能已缓存过压缩体，
    读取时若仍非文本（decode 后找不到 '<'）则自动重抓，避免误报结构变更。
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"cnal-lme-{year}-{month:02d}.html"
    raw = ""
    if cache.exists():
        raw = cache.read_text(encoding="utf-8", errors="ignore")
        if "<" not in raw or "年" not in raw:
            print("  ⚠️ 缓存疑似损坏/为压缩体，重新抓取")
            raw = ""
    if not raw:
        page = find_month_page(year, month)
        raw = _get(page).decode("utf-8", "ignore")
        if "<table" not in raw.lower():
            raise RuntimeError(f"抓取内容不像 HTML（前 80 字：{raw[:80]!r}）")
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
    ap = argparse.ArgumentParser(
        description="LME 铝月度核验（默认只读）；加 --apply 才写入")
    ap.add_argument("--month", help="YYYY-MM，缺省＝上一自然月")
    ap.add_argument("--apply", action="store_true",
                    help="确认后真正写入（空缺直接补、日延一错位修正）")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    if args.month:
        y, mo = (int(x) for x in args.month.split("-"))
    else:
        # 月度核验默认核验「上一自然月」：世铝网次月 1 日才出上月表
        first = datetime.date.today().replace(day=1)
        prev = first - datetime.timedelta(days=1)
        y, mo = prev.year, prev.month
        args.month = f"{y}-{mo:02d}"
    today = datetime.date.today()
    mode = "写入" if args.apply else "核验（只读）"
    print("=" * 54)
    print(f"  LME 铝 · {args.month} 月度核验/补全（世铝网官方价表）  {today}  模式：{mode}")
    print("=" * 54)

    print("[1/4] 抓取世铝网月度官方价表（现货卖 = Cash Ask）...")
    try:
        table = fetch_month_table(y, mo)
    except Exception as e:
        # 定时任务场景：抓不到属常态（表未发布/站点抖动），给清晰原因后
        # 优雅退出（code 0 = 无差异），不抛栈、不当成故障刷屏。
        print(f"  ℹ️ 跳过：{e}")
        print("  → 本月不核验，未改动任何数据。等表发布后重跑即可。")
        return 0
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

    # ---- 逐日比对，分类 ----
    ok, writes, fixes, suspects, absent = [], [], [], [], []
    prev_days_sorted = sorted(month_days)
    for day in prev_days_sorted:
        off = month_days[day]
        r = rows.get(day)
        if r is None:
            absent.append(f"{day}(无行)")
            continue
        cur = ws.cell(r, LME_COL).value
        if isinstance(cur, (int, float)) and abs(float(cur) - off) < 1e-6:
            ok.append(day)
            continue
        if cur in (None, ""):
            writes.append((r, day, off))
            continue
        # 有值但 ≠ 官方值：判它是「旧日延一错位」还是「人工修正/其他偏差」
        idx = prev_days_sorted.index(day)
        prev_off = month_days[prev_days_sorted[idx - 1]] if idx > 0 else None
        if prev_off is not None and abs(float(cur) - prev_off) < 1e-6:
            fixes.append((r, day, cur, off))
        else:
            suspects.append((day, cur, off))

    print(f"[2/4] 逐日比对（官方表 {len(month_days)} 日 vs 表内）：")
    print(f"    ✅ 一致 {len(ok)}"
          f"   ｜ 空缺待补 {len(writes)}"
          f"   ｜ 日延一错位 {len(fixes)}"
          f"   ｜ 其他偏差 {len(suspects)}"
          f"   ｜ 表中无行 {len(absent)}")
    for r, day, off in writes:
        print(f"    + {day}  行{r}  = {off}")
    for r, day, old, off in fixes:
        print(f"    ~ {day}  行{r}  {old} → {off}（日延一错位）")
    for day, cur, off in suspects:
        print(f"    ? {day}  现值 {cur} ≠ 官方 {off}"
              f"（既非前一日官方价 → 疑似人工修正或源方回溯修订，**不改**）")
    if absent:
        print(f"    · 表中无行：{', '.join(absent)}")

    # ---- 月度核验结论 ----
    clean = not (writes or fixes or suspects or absent)
    if clean:
        print(f"\n  🟢 核验通过：{args.month} 共 {len(ok)} 个官方数据日，表内全部与官方价一致。")
    else:
        print(f"\n  🟡 核验发现 {len(writes) + len(fixes) + len(suspects) + len(absent)} 处差异"
              f"（待补 {len(writes)} / 错位 {len(fixes)} / 其他偏差 {len(suspects)} / 无行 {len(absent)}）")

    if not writes and not fixes:
        print("  无需变更，退出。")
        return 0
    if not args.apply:
        print("\n  [核验模式] 未加 --apply，不写入任何数据。"
              "确认无误后重跑：加 --apply")
        return 0

    # ---- 备份 ----
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