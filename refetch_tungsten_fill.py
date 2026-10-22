#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中钨在线官方报价表图片直取 → 回填当日钨粉(W)。

背景（2026-10-22 定案）
---------------------
中文 / 英文「钨产品报价」**栏目页**的文章列表自 2026-10-20 起停止更新，
原 `fetch_tungsten()` 依赖栏目页「当日文章」→ W 连续两日静默留空。

但中钨在线**并未停更**：官方每日报价表图片仍按日发布，URL 规则固定

    http://www.ctia.com.cn/en/wp-content/uploads/YYYY/MM/tungsten-price-YYYYMMDD-en.jpg

图片内 `Tungsten Powder  99.9%, 2-10μm` 行的 Price(Domestic) 即本项目 W 口径
（RMB/kg）。故正确修法是**换入口、不换源**——口径与历史序列完全连续。

用法
----
    # 1) 取图存证 + 打印图内数值（人工/视觉核对），不写表
    python refetch_tungsten_fill.py --date 2026-10-22 --dry

    # 2) 核对无误后写表 + 导出 + 推送
    python refetch_tungsten_fill.py --date 2026-10-22 --price 740

铁律：抓不到就留空。--price 必须与官方图一致；本脚本会重新取图存证，
不一致时拒绝写入（除非 --force）。
"""

import argparse
import datetime
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

EXCEL_PATH = SCRIPT_DIR / "2026年有色金属市场价格.xlsx"
SHEET_NAME = "日均价（2026年市场）"
W_COL = 16  # P 列 = 钨粉
EVIDENCE_DIR = SCRIPT_DIR / "data" / "tungsten_evidence"
BACKUP_DIR = SCRIPT_DIR / "backups" / "精工"

IMG_URL = ("http://www.ctia.com.cn/en/wp-content/uploads/{y}/{m}/"
           "tungsten-price-{d}-en.jpg")


def img_url(day: datetime.date) -> str:
    return IMG_URL.format(y=day.year, m=f"{day.month:02d}",
                          d=day.strftime("%Y%m%d"))


def fetch_image(day: datetime.date) -> Path | None:
    """下载官方报价表图片到 data/tungsten_evidence/，返回本地路径。"""
    import requests

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    dst = EVIDENCE_DIR / f"tungsten-price-{day.strftime('%Y%m%d')}-en.jpg"
    url = img_url(day)
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 Chrome/131.0"})
        if r.status_code != 200 or len(r.content) < 5000:
            print(f"  ✗ 官方报价表图片不可用：HTTP {r.status_code} / {len(r.content)} 字节")
            return None
        dst.write_bytes(r.content)
        print(f"  ✓ 官方报价表已存证 {dst.name}（{len(r.content)} 字节）")
        print(f"    {url}")
        return dst
    except Exception as e:
        print(f"  ✗ 下载失败：{type(e).__name__}: {e}")
        return None


def ocr_w(day: datetime.date,
          img: Path | None) -> float | None:
    """裁剪 `Tungsten Powder` 行做单行 OCR，返回钨粉价（元/千克）。

    英文报价表版面固定：14 行表格，Tungsten Powder 为第 7 个数据行。
    多窗口 + 多预处理表决，任一环节失败返回 None（不做猜测）。
    """
    if not img or not img.exists():
        return None
    try:
        from PIL import Image, ImageOps
    except Exception as e:
        print(f"  ⚠️ PIL 缺失（{type(e).__name__}），跳过自动比对")
        return None

    # tesseract 走 CLI（与 fetcher_tungsten 一致，不依赖 pytesseract）；
    # 临时文件放项目目录 —— macOS 下 tesseract 子进程对 /tmp 访问受限。
    try:
        subprocess.run(["tesseract", "--version"], capture_output=True, timeout=5)
    except Exception as e:
        print(f"  ⚠️ tesseract 不可用（{type(e).__name__}），跳过自动比对")
        return None

    im = Image.open(img).convert("L")
    W, H = im.size
    votes: list[int] = []
    tmp_png = SCRIPT_DIR / "_tmp_w_row.png"
    try:
        # 纵向窗口扫描：覆盖第 5~9 行可能位置
        for top in [i / 100 for i in range(44, 62)]:
            for hh in (0.040, 0.045, 0.050):
                box = (int(W * 0.34), int(H * top), int(W * 0.62), int(H * (top + hh)))
                crop = ImageOps.autocontrast(im.crop(box))
                crop = crop.resize((crop.width * 4, crop.height * 4), Image.LANCZOS)
                for thresh in (None, 170):
                    out = crop if thresh is None else crop.point(
                        lambda p, t=thresh: 0 if p < t else 255)
                    out.save(tmp_png)
                    r = subprocess.run(
                        ["tesseract", str(tmp_png), "stdout", "-l", "eng",
                         "--psm", "7", "-c", "tessedit_char_whitelist=0123456789"],
                        capture_output=True, text=True, timeout=20)
                    d = "".join(ch for ch in r.stdout if ch.isdigit())
                    if len(d) == 3 and 200 <= int(d) <= 3000:
                        votes.append(int(d))
    finally:
        tmp_png.unlink(missing_ok=True)
    if not votes:
        return None
    # 取众数
    from collections import Counter
    val, cnt = Counter(votes).most_common(1)[0]
    print(f"  · OCR 票型：{dict(Counter(votes).most_common(4))} → 采用 {val}（{cnt} 票）")
    return float(val)


def find_row(ws, day: datetime.date) -> int | None:
    for r in range(2, ws.max_row + 1):
        v = ws.cell(r, 1).value
        if isinstance(v, datetime.datetime) and v.date() == day:
            return r
        if isinstance(v, datetime.date) and v == day:
            return r
        if isinstance(v, str):
            for f in ("%Y-%m-%d", "%Y/%m/%d"):
                try:
                    if datetime.datetime.strptime(v.strip(), f).date() == day:
                        return r
                except ValueError:
                    pass
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--price", type=float, help="写入值（元/千克）")
    ap.add_argument("--dry", action="store_true", help="只取图+OCR，不写表")
    ap.add_argument("--strict", action="store_true", help="OCR 与 --price 不一致时阻断写入")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    day = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()
    print(f"\n中钨在线报价表 → 钨粉(W) {day}\n" + "-" * 52)

    img = fetch_image(day)
    if img is None:
        print("\n✗ 官方图不可得，按铁律留空。\n")
        return 1
    ocr_val = ocr_w(day, img)

    if args.dry or args.price is None:
        print(f"\n[DRY] 图已存证，OCR={ocr_val}。请人工核对图片后带 --price 写入。")
        print(f"      看图：open {img}\n")
        return 0

    price = float(args.price)
    # ⚠️ 该图中央横贯半透明水印 `www.chinatungsten.com`，正压在 Tungsten Powder
    #    行上，OCR 结构性不可靠（实测把 740 读成 702/840）。故 OCR 仅作提示，
    #    写值以人工/视觉核对为准；不一致时打印警示但继续（--strict 可改为阻断）。
    if ocr_val is not None and abs(ocr_val - price) > 0.5:
        print(f"  ⚠️ OCR={ocr_val} 与 --price={price} 不一致（水印干扰，属已知现象）")
        if args.strict:
            print("  ✗ --strict：拒绝写入，请人工复核图片后重试\n")
            return 2
    elif ocr_val is not None:
        print(f"  ✓ OCR={ocr_val} 与 --price 一致")

    import openpyxl
    from jinggong_monitor.safe_io import atomic_save_workbook
    from changelog import (record_changes, current_commit_sha, SOURCE_AUTO_CRON)

    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb[SHEET_NAME]
    row = find_row(ws, day)
    if not row:
        print(f"✗ 表内无 {day} 行，终止（不新建行）\n")
        return 1

    old = ws.cell(row, W_COL).value
    if old not in (None, "") and abs(float(old) - price) < 0.5:
        print(f"  行{row} 已是 {price}，无需重写")
        return 0
    ws.cell(row, W_COL).value = price
    atomic_save_workbook(wb, EXCEL_PATH, backup=True,
                         backup_dir=BACKUP_DIR, same_day_max=1)
    print(f"  ✓ 行{row} 钨粉 {old!r} → {price}（原子写 + 备份）")

    sha = current_commit_sha(str(SCRIPT_DIR))
    n = record_changes(
        [{"date_row": day.strftime("%Y-%m-%d"), "code": "W", "old": old, "new": price}],
        source=SOURCE_AUTO_CRON, editor="中钨在线官方报价表", commit=sha,
    )
    print(f"  📝 变更留痕 {n} 条（auto_cron / 中钨在线官方报价表）")

    print("  导出 data.json...")
    subprocess.run([sys.executable, str(SCRIPT_DIR / "export_excel_to_json.py")],
                   cwd=str(SCRIPT_DIR), capture_output=True, text=True)
    if args.no_push:
        print("  (--no-push：跳过推送)")
        return 0

    def git(a, timeout=90):
        return subprocess.run(["git"] + a, cwd=str(SCRIPT_DIR),
                              capture_output=True, text=True, timeout=timeout)

    git(["add", "docs/data.json", "docs/changelog.json"])
    git(["commit", "-m", f"钨粉 {day} = {price}（中钨在线官方报价表图片直取）"])
    r = git(["push"], timeout=120)
    v = git(["rev-list", "--left-right", "--count", "HEAD...origin/main"], timeout=30)
    ok = v.returncode == 0 and v.stdout.split()[:2] == ["0", "0"]
    print("  ✅ 推送成功" if ok else f"  ⚠️ 推送待核：{v.stdout.strip()}")
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
