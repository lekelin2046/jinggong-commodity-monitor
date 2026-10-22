#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中钨在线「官方每日报价表」图片直取（换入口，不换源）。

背景（2026-10-22 定案）
---------------------
中文 `news.chinatungsten.com/cn/tungsten-product-news.html` 与英文
`/en/tungsten-product-news.html` 的**文章列表**自 2026-10-20 起停止更新，
导致 `ChinatungstenFetcher.fetch()`（依赖栏目页「当日文章」）连续留空。

但中钨在线并未停更：官方每日报价表图片仍按日发布，且 URL 规则固定

    http://www.ctia.com.cn/en/wp-content/uploads/YYYY/MM/tungsten-price-YYYYMMDD-en.jpg

图内 `Tungsten Powder  99.9%, 2-10μm` 行的 Price(Domestic) 即本项目 W 口径
（RMB/kg）。故修法是**换入口、不换源**——口径与历史序列完全连续。

⚠️ 两个已知约束（勿"优化"掉）
------------------------------
1. **不做自动取数**。该图中央横贯半透明水印 `www.chinatungsten.com`，正压在
   Tungsten Powder 行；实测 OCR 把 740 读成 702、840，盲扫还会串到
   Tungsten Bar 的 840。故本模块**只负责下载存证**，数值由视觉读取后经
   `refetch_tungsten_fill.py --price N` 写入（守铁律：宁留空，勿错值）。
2. **发布时点 14:00~15:26（北京）**。实测 Last-Modified 落在 UTC 06:00~07:26，
   即当日图片常在 15:00 编排之后才生成 → 15:00 那轮常取不到，须由 17:00
   `--check` 补差再取。

实测可用性（2026-10-22）：10-08/13/16/19/20/21/22、09-23/24/28/29 均 200；
09-25、09-30 为 404（个别交易日无图）→ 规则可用但非 100%，缺图即留空。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 项目根（本文件位于 <root>/jinggong_monitor/）
ROOT = Path(__file__).resolve().parent.parent

EVIDENCE_DIR = ROOT / "data" / "tungsten_evidence"

IMG_URL = ("http://www.ctia.com.cn/en/wp-content/uploads/{y}/{m}/"
           "tungsten-price-{d}-en.jpg")

# 该站对"完整浏览器 UA"与短 UA 都放行；统一用短串（与 refetch 脚本一致）
UA = "Mozilla/5.0 Chrome/131.0"

# 图片体积下限：正常约 250~270KB，小于此值基本是错误页/防盗链占位
MIN_BYTES = 5000


def official_image_url(day: date) -> str:
    """当日官方报价表图片 URL（规则固定，无需抓页面）。"""
    return IMG_URL.format(y=day.year, m=f"{day.month:02d}",
                          d=day.strftime("%Y%m%d"))


def local_image_path(day: date) -> Path:
    """本地存证路径：data/tungsten_evidence/tungsten-price-YYYYMMDD-en.jpg"""
    return EVIDENCE_DIR / f"tungsten-price-{day.strftime('%Y%m%d')}-en.jpg"


def download_official_image(day: date, timeout: int = 30) -> Optional[Path]:
    """下载当日官方报价表图片存证，返回本地路径；不可得返回 None。

    - 已存在且体积正常 → 直接复用（幂等，避免重复下载与无谓写盘）
    - HTTP 非 200 / 体积过小 → 视为当日无图（如 09-25、09-30 实测 404）
    - 写入用 `.part` 临时文件 + os.replace，防止半截文件被当成存证

    注意：本函数**只下载，不解析**。数值读取见模块 docstring 约束 1。
    """
    dst = local_image_path(day)
    if dst.is_file() and dst.stat().st_size >= MIN_BYTES:
        return dst

    url = official_image_url(day)
    try:
        import requests

        r = requests.get(url, timeout=timeout, headers={"User-Agent": UA})
        if r.status_code != 200:
            logger.info("中钨官方报价表 %s 不可得：HTTP %s", day, r.status_code)
            return None
        if len(r.content) < MIN_BYTES:
            logger.info("中钨官方报价表 %s 体积异常：%s 字节", day, len(r.content))
            return None

        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(dst.suffix + ".part")
        tmp.write_bytes(r.content)
        tmp.replace(dst)
        logger.info("中钨官方报价表已存证：%s（%s 字节）", dst.name, len(r.content))
        return dst
    except Exception as e:  # noqa: BLE001
        logger.warning("中钨官方报价表下载失败：%s: %s", type(e).__name__, e)
        return None


def relay_target(day: date) -> date:
    """把任意日期归一化为 date（接受 str / datetime / date）。"""
    if isinstance(day, datetime):
        return day.date()
    if isinstance(day, date):
        return day
    return date.fromisoformat(str(day)[:10])


def pending_evidence(day: date) -> Optional[Path]:
    """当日已存证、但仍待视觉确认的官方图（存在即返回路径）。"""
    d = relay_target(day)
    p = local_image_path(d)
    return p if p.is_file() and p.stat().st_size >= MIN_BYTES else None


def fill_command(day: date) -> str:
    """给出人工/视觉确认后的回填命令（供日志与自动化直接照抄）。"""
    d = relay_target(day)
    return (f"python refetch_tungsten_fill.py --date {d.isoformat()} --price <图内数值>")
