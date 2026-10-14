#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测隆众 vid=275（三元乙丙）下的全部「市场|规格」行，确认是否存在 3092PM。

只读探测，不写任何数据文件。
用法：/Users/siqi/.workbuddy/binaries/python/envs/jinggong/bin/python tools/probes/probe_epdm_specs.py
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from jinggong_monitor.lz_price_center import (  # noqa: E402
    fetch_raw_http, _iter_rows, _row_label, cookie_header, API_BASE, UA,
)


def fuzzy(kw: str) -> list:
    url = f"{API_BASE}/ndc/common/fuzzyQueryBreeds?keyword={urllib.parse.quote(kw)}"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    req.add_header("Referer", f"{API_BASE}/page/")
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
        return d.get("response") or []
    except Exception as e:                                   # noqa: BLE001
        print(f"  [warn] {kw}: {type(e).__name__}: {e}")
        return []


def main():
    print("=" * 78)
    print("① 隆众品种搜索（免登录模糊查询）")
    print("=" * 78)
    for kw in ("3092PM", "3092", "三井", "三元乙丙", "EPDM"):
        hits = fuzzy(kw)
        print(f"\n[{kw}] 命中 {len(hits)}")
        for it in hits[:12]:
            print(f"    id={it.get('id'):<7} name={it.get('name')}"
                  f"  短名={it.get('shortName') or '-'}  alias={it.get('aliasName') or '-'}")

    print()
    print("=" * 78)
    print("② vid=275（三元乙丙）行枚举 —— 市场 / 规格")
    print("=" * 78)
    ck = cookie_header()
    print(f"cookie 长度：{len(ck) if ck else 0}")
    doc = fetch_raw_http(275, 3, 0, ck)
    print(f"接口 status={doc.get('status')}  message={doc.get('message')}")
    resp = doc.get("response") or {}
    dates = list(resp.get("dateList") or [])
    print(f"dateList（接口默认 5 日）= {dates}")
    rows = _iter_rows(resp)
    print(f"总行数 = {len(rows)}")

    seen = []
    for r in rows:
        mkt, sp = _row_label(r)
        price = None
        for d in dates:
            cell = r.get(d)
            if isinstance(cell, dict):
                pm = cell.get("price") or {}
                if isinstance(pm, dict):
                    v = pm.get("middlePrice") or pm.get("lowPrice") or pm.get("highPrice")
                    if v not in (None, "", "-"):
                        price = v
                        break
        seen.append((mkt, sp, r.get("businessId"), price))

    print(f"\n{'市场':<14}{'规格':<16}{'businessId':<12}最新价")
    print("-" * 60)
    for mkt, sp, bid, price in seen:
        print(f"{str(mkt):<14}{str(sp):<16}{str(bid):<12}{price}")

    hits = [x for x in seen if "3092" in str(x[1]).upper() or "3092" in str(x[0]).upper()]
    print("\n" + "-" * 60)
    if hits:
        print(f"✓ 找到 3092 相关行 {len(hits)} 条：")
        for h in hits:
            print(f"    {h}")
    else:
        print("✗ vid=275 下未发现含「3092」的市场/规格行")

    specs = sorted({str(x[1]) for x in seen})
    print(f"\n现有全部规格 {len(specs)} 个：{specs}")


if __name__ == "__main__":
    main()
