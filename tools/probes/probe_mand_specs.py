#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""曼德新品种口径探针（只读，不写业务数据）。

背景：曼德热系统 2026-10-14 回复 6 项未接入品种的口径：
  - 镨钕金属  → 改用卓创（金属镨钕 PrNd≥99%（中国）市场价）
  - PA6      → 工程塑料 > PA6 > 华南地区 > 神马塑料 > 型号 BL3280H
  - PA66     → 工程塑料 > PA66 > 华中地区 > 神马塑料 > 型号 EPR27
  - PP-TD20  → PP粒 > 华东地区 > 大庆石化 > 型号 T30S
  - PP-TD40  → PP粒 > 华东地区 > 大庆石化 > 型号 EP548R

本探针回答两个问题：
  ① 隆众（dc.oilchem.net）是否收录这些牌号？  → fuzzyQueryBreeds 免登录搜索
  ② 卓创（prices.sci99.com）是否收录？          → 登录态搜索页逐行打印（含地区/厂商/规格/价格）

用法：
  /Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/python tools/probes/probe_mand_specs.py
  ... tools/probes/probe_mand_specs.py --only lz
  ... tools/probes/probe_mand_specs.py --only sci99
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "probe_mand_specs.json"

# 曼德指定的牌号 / 厂家 / 地区关键词
LZ_KEYWORDS = ["BL3280H", "EPR27", "T30S", "EP548R", "神马", "大庆石化",
               "PA6", "PA66", "镨钕", "工程塑料", "PP粒"]
SCI99_KEYWORDS = ["PA6", "PA66", "BL3280H", "EPR27", "T30S", "EP548R",
                  "大庆石化", "神马", "金属镨钕"]


# ---------------------------------------------------------------- 隆众
def probe_lz() -> dict:
    from jinggong_monitor.lz_price_center import API_BASE, UA

    out: dict = {}
    print("=" * 78)
    print("① 隆众 dc.oilchem.net —— fuzzyQueryBreeds（免登录）")
    print("=" * 78)
    for kw in LZ_KEYWORDS:
        url = f"{API_BASE}/ndc/common/fuzzyQueryBreeds?keyword={urllib.parse.quote(kw)}"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", UA)
        req.add_header("Referer", f"{API_BASE}/page/")
        hits = []
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                doc = json.loads(r.read().decode("utf-8", "ignore"))
            hits = doc.get("response") or []
        except Exception as e:                                   # noqa: BLE001
            print(f"\n[{kw}] 请求失败 {type(e).__name__}: {e}")
            out[kw] = {"error": str(e)}
            continue
        rows = [{"id": it.get("id"), "name": it.get("name"),
                 "short": it.get("shortName"), "alias": it.get("aliasName")}
                for it in hits]
        out[kw] = rows
        print(f"\n[{kw}] 命中 {len(rows)}")
        for it in rows[:14]:
            print(f"    id={str(it['id']):<8} {it['name']}"
                  f"  短名={it['short'] or '-'}  alias={it['alias'] or '-'}")
    return out


# ------------------------------------------------- 隆众：枚举 vid 下的全部报价行
# 曼德指定的品种在隆众库里对应：PA6=3084 / PA66=3085 / PP=317（别名 PP粒料）
#                             镨钕合金=5802 / 氧化镨钕=5855
LZ_VIDS = {3084: "聚酰胺6（PA6）", 3085: "聚酰胺66（PA66）", 317: "PP（PP粒料）",
           5802: "镨钕合金", 5855: "氧化镨钕"}
# 曼德指定牌号 → 用于在行里做命中标注
WANT_PATTERNS = ("BL3280H", "EPR27", "T30S", "EP548R", "神马", "大庆")


def _cell_price(row: dict, dates: list) -> tuple:
    """返回 (最新价, 生效日期) —— 取 middlePrice 优先"""
    for d in dates:
        cell = row.get(d)
        if isinstance(cell, dict):
            pm = cell.get("price") or {}
            if isinstance(pm, dict):
                v = (pm.get("middlePrice") or pm.get("lowPrice") or pm.get("highPrice"))
                if v not in (None, "", "-"):
                    return v, d
    return None, None


def probe_lz_rows(dump_keys: bool = True) -> dict:
    from jinggong_monitor.lz_price_center import (
        fetch_raw_http, _iter_rows, cookie_header, auth_state)

    ck = cookie_header()
    print()
    print("=" * 78)
    print("③ 隆众 —— 枚举目标品种（vid）下的全部报价行")
    print(f"   cookie 长度 = {len(ck) if ck else 0}")
    print("=" * 78)

    out: dict = {}
    for vid, label in LZ_VIDS.items():
        # businessType: 3=市场价格，1/2 为其他口径，逐个试
        for bt in (3, 2, 1):
            try:
                doc = fetch_raw_http(vid, bt, 0, ck)
            except Exception as e:                               # noqa: BLE001
                print(f"\n[{vid} {label}] bt={bt} 请求失败 {type(e).__name__}: {e}")
                continue
            resp = doc.get("response") or {}
            rows = _iter_rows(resp)
            if not rows:
                continue
            dates = list(resp.get("dateList") or [])
            auth = auth_state(resp)
            print(f"\n[{vid} {label}] bt={bt} 行数={len(rows)} 权限={auth} "
                  f"dateList={dates}")
            if dump_keys and rows:
                print(f"    字段名样例：{sorted(rows[0].keys())}")
            hits = []
            for r in rows:
                mkt = str(r.get("internalMarketName") or r.get("marketName") or "").strip()
                spec = str(r.get("specificationsName") or r.get("standard") or "").strip()
                vendor = str(r.get("manufacturerName") or r.get("brandName")
                             or r.get("producerName") or "").strip()
                price, day = _cell_price(r, dates)
                blob = f"{mkt}|{spec}|{vendor}"
                flag = " ★" if any(p.lower() in blob.lower() for p in WANT_PATTERNS) else ""
                if flag:
                    hits.append((mkt, spec, vendor, r.get("businessId"), price, day))
            print(f"    命中曼德指定牌号/厂家 {len(hits)} 行")
            for h in hits[:25]:
                print(f"      ★ 市场={h[0]} 规格={h[1]} 厂家={h[2]} "
                      f"businessId={h[3]} 价={h[4]} @{h[5]}")
            if not hits:
                print("    全部行（前 40）：")
                for r in rows[:40]:
                    mkt = str(r.get("internalMarketName") or r.get("marketName") or "").strip()
                    spec = str(r.get("specificationsName") or r.get("standard") or "").strip()
                    vendor = str(r.get("manufacturerName") or r.get("brandName")
                                 or r.get("producerName") or "").strip()
                    price, day = _cell_price(r, dates)
                    print(f"      - 市场={mkt:<10} 规格={spec:<22} 厂家={vendor:<14} "
                          f"id={r.get('businessId')} 价={price} @{day}")
            out[f"{vid}:{bt}"] = {
                "label": label, "rows": len(rows), "auth": auth, "dates": dates,
                "hits": [{"market": h[0], "spec": h[1], "vendor": h[2],
                          "businessId": h[3], "price": h[4], "date": h[5]} for h in hits],
            }
            break       # 该 vid 已有行，不必再试其它 bt
    return out


# ---------------------------------------------------------------- 卓创
def _rows(html: str) -> list:
    out = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
        cells = [c for c in cells if c]
        if cells:
            out.append(cells)
    return out


async def probe_sci99() -> dict:
    from jinggong_monitor.fetcher_sci99 import _load_cookies
    from playwright.async_api import async_playwright

    cookies = _load_cookies()
    out: dict = {}
    print()
    print("=" * 78)
    print("② 卓创 prices.sci99.com —— 登录态搜索页")
    print(f"   cookie={'OK' if cookies else '不可用'}")
    print("=" * 78)
    if not cookies:
        return out

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(locale="zh-CN",
                                        viewport={"width": 1440, "height": 900})
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        try:
            await page.goto("https://www.sci99.com/", wait_until="domcontentloaded",
                            timeout=30000)
        except Exception:                                        # noqa: BLE001
            pass

        for kw in SCI99_KEYWORDS:
            url = f"https://prices.sci99.com/cn/search.aspx?keyword={urllib.parse.quote(kw)}"
            try:
                await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                await page.wait_for_timeout(3500)
                html = await page.content()
            except Exception as e:                               # noqa: BLE001
                print(f"\n[{kw}] 失败 {type(e).__name__}: {e}")
                out[kw] = {"error": str(e)}
                continue
            rows = _rows(html)
            priced = [r for r in rows
                      if any(u in " ".join(r) for u in ("元/吨", "万元/吨", "元/千克"))]
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
            # 表头行（第一行含「品种编号」或「品类」字样）
            header = next((r for r in rows if any("品类" in c or "规格" in c for c in r)), [])
            has_next = bool(re.search(r"下一页|nextPage|page=2", html))
            out[kw] = {"total_rows": len(rows), "priced_rows": len(priced),
                       "logged_in": "退出" in text, "header": header,
                       "has_next_page": has_next, "samples": priced[:60]}
            print(f"\n[{kw}] 表内行 {len(rows)} | 带价 {len(priced)} "
                  f"| 登录态 {out[kw]['logged_in']} | 分页 {has_next}")
            print(f"    表头：{' | '.join(header)}")
            for s in priced[:60]:
                print("    " + " | ".join(s)[:300])
        await browser.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["lz", "sci99", "lzrows"])
    args = ap.parse_args()

    result = {}
    if args.only == "lzrows":
        result["lzrows"] = probe_lz_rows()
    else:
        if args.only != "sci99":
            result["lz"] = probe_lz()
            result["lzrows"] = probe_lz_rows()
        if args.only != "lz":
            result["sci99"] = asyncio.run(probe_sci99())

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
