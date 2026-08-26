#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetcher_plas.py — 普拉司网（plas.com）牌号级 FOB/CIF 挂单报价抓取器
====================================================================
口径：贸易商挂单 FOB/CIF 美元价（不含税，非成交价）。
聚合页 search/material?id= ：多家供应商报价表（GP-22 22家 / AG12A1 / PA-757K 38家）
raw-material/detail/{id}   ：单家挂单页（2405 / 1225Y / 1201-15，样本少，标注）
用途：与中塑在线（fetcher_21cp.py）人民币现货价交叉校验。
⚠️ 低频抓取（间隔 ≥2s），克制频率。

用法：
    python3 fetcher_plas.py
输出：
    终端汇总 + /tmp/plas_data.json
"""
import json
import re
import statistics
import time
import html as htmlmod
import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
BASE = "https://www.plas.com"

# key -> (类型, id, 显示名)
# type: "agg" = search/material 聚合页; "rm" = raw-material 挂单页
TARGETS = [
    ("PC2405",   "rm",  "DA0273AE9015F4CA5B1463DCB831E051", "科思创 Makrolon 2405"),
    ("PC1225Y",  "rm",  "EB2B78F0833A81A2A0EAC9108579DAA4", "帝人 PANLITE L-1225Y"),
    ("PC1201-15","rm",  "1EEC140A7A1C2624B93C8E2E18D0F4B7", "LG LUPOY 1201-15"),
    ("ABS_GP22", "agg", "4C87215C8F689191B8B4DBAE90B9CCA9", "苯领 Terluran GP-22(宁波)"),
    ("ABS_AG12A1", "agg", "C12FCA95861900CA7962A716A4E7A10C", "台化 TAIRILAC AG12A1(宁波)"),
    ("ABS_PA757K", "agg", "8C9C7A731BAE8E957B2B29E6B1671E01", "奇美 POLYLAC PA-757K(漳州)"),
]


def safe_get(url, retries=2):
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            if r.status_code == 200:
                return r.text
            print(f"    [warn] {url} -> HTTP {r.status_code}")
        except Exception as e:
            print(f"    [warn] 请求失败: {e}")
        time.sleep(2)
    return None


def parse_agg(html_text):
    """聚合页：供应商 | [FOB/CIF] 港口 | US$ X / 吨 | 时间"""
    text = re.sub(r"<script.*?</script>", "", html_text, flags=re.S)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.S)
    quotes = []
    for r in rows:
        cells = [htmlmod.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S)]
        cells = [c for c in cells if c]
        joined = " | ".join(cells)
        m = re.search(r"US\$[^0-9]*([0-9,]{4,6})\s*/\s*(MT|吨|tonne|ton)", joined)
        if not m:
            continue
        price = int(m.group(1).replace(",", ""))
        term = "FOB" if "FOB" in joined else ("CIF" if "CIF" in joined else "")
        port = ""
        pm = re.search(r"(?:FOB|CIF)\s*\]\s*([^|]{2,30}?港|[^|]{2,20})", joined)
        if pm:
            port = pm.group(1).strip()
        quotes.append({
            "supplier": cells[0] if cells else "",
            "term": term,
            "port": port,
            "price_usd": price,
            "time": next((c for c in cells if "ago" in c), ""),
        })
    return quotes


def parse_rm(html_text):
    """raw-material 挂单页：供应商 | US$ X /MT"""
    text = re.sub(r"<script.*?</script>", "", html_text, flags=re.S)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.S)
    quotes = []
    for r in rows:
        cells = [htmlmod.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S)]
        cells = [c for c in cells if c]
        joined = " | ".join(cells)
        m = re.search(r"US\$[^0-9]*([0-9,]{4,6})\s*/\s*MT", joined)
        if not m:
            continue
        quotes.append({
            "supplier": cells[0] if cells else "",
            "term": "FOB",
            "port": "",
            "price_usd": int(m.group(1).replace(",", "")),
            "time": "",
        })
    return quotes


def get_usd_cny():
    """获取当日 USD/CNY 汇率，失败返回 7.1 估算"""
    for url in ["https://open.er-api.com/v6/latest/USD",
                "https://api.frankfurter.app/latest?from=USD&to=CNY"]:
        try:
            r = requests.get(url, timeout=10)
            d = r.json()
            if "CNY" in d.get("rates", {}):
                return round(d["rates"]["CNY"], 4)
        except Exception:
            continue
    return 7.1


def summarize(quotes):
    """统计：样本数、min/max/中位数（样本 ≥10 时去两端 10% 异常）"""
    prices = sorted(q["price_usd"] for q in quotes)
    if not prices:
        return None
    n = len(prices)
    if n >= 10:
        trim = max(1, n // 10)
        robust = prices[trim:n - trim]
    else:
        robust = prices  # 样本少不去异常
    return {
        "count": n,
        "min": prices[0], "max": prices[-1],
        "median": int(statistics.median(prices)),
        "robust_median": int(statistics.median(robust)),
    }


def main():
    results = {}
    print("=" * 78)
    print("普拉司网 牌号级挂单报价抓取（FOB/CIF 美元，不含税）")
    print("=" * 78)
    for key, typ, pid, name in TARGETS:
        print(f"\n▶ {key}  ({name})")
        if typ == "agg":
            url = f"{BASE}/zh-CN/search/material?id={pid}&v=0"
            html_text = safe_get(url)
            quotes = parse_agg(html_text) if html_text else []
        else:
            url = f"{BASE}/raw-material/detail/{pid}"
            html_text = safe_get(url)
            quotes = parse_rm(html_text) if html_text else []
        if not quotes:
            results[key] = {"status": "FAIL", "name": name}
            print("    ✗ 无报价")
            continue
        s = summarize(quotes)
        print(f"    ✓ {s['count']} 家报价 | 区间 ${s['min']:,}-${s['max']:,}/吨 | 中位数 ${s['median']:,} | 稳健中位 ${s['robust_median']:,}")
        for q in quotes[:5]:
            print(f"      - {q['supplier'][:18]:20s} {q['term']} {q['port'][:8]:10s} ${q['price_usd']:,}/吨 {q['time']}")
        results[key] = {"status": "OK", "name": name, "url": url, **s,
                        "sample": quotes[:10]}
        time.sleep(2)

    usd_cny = get_usd_cny()
    print(f"\n当日 USD/CNY 汇率: {usd_cny}")
    with open("/tmp/plas_data.json", "w", encoding="utf-8") as f:
        json.dump({"usd_cny": usd_cny, "results": results}, f,
                  ensure_ascii=False, indent=2)
    print("结构化结果已存 /tmp/plas_data.json")


if __name__ == "__main__":
    main()
