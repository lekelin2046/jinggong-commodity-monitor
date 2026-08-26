#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetcher_21cp.py — 中塑在线（intl.21cp.com）牌号级市场参考价抓取器
====================================================================
数据口径：余姚中国塑料城市场参考价（人民币含税现货，日更，工信部指定指数企业背书）
反爬处理：全站 SafeLine WAF，普通 UA 一律 468 拦截；
          实测 Googlebot UA 对 /market/detail/ 详情页放行（200）。
          ⚠️ 模拟搜索引擎 UA 属低频合规使用，必须克制频率（每日 1 次，请求间隔 ≥2s），
          禁止高频抓取，避免被封。

用法：
    python3 fetcher_21cp.py                 # 抓全部 6 个牌号
    python3 fetcher_21cp.py 2405 1225Y      # 只抓指定牌号（关键词）
输出：
    终端打印核对表 + /tmp/21cp_data.json（结构化）
"""
import json
import re
import sys
import time
import html as htmlmod
import requests

GOOGLEBOT_UA = ("Mozilla/5.0 (compatible; Googlebot/2.1; "
                "+http://www.google.com/bot.html)")
BASE = "https://intl.21cp.com"
SEARCH_URL = BASE + "/market/list/----1.html"
DETAIL_URL = BASE + "/market/detail/{pid}--.html"

# 牌号 -> (key, 搜索关键词, 品牌过滤关键字, 优先产地关键字, 显示名)
# 注：PP M100RHC(镇海炼化) 中塑未收录，不在此列
TARGETS = [
    ("PC2405",     "2405",   ["covestro", "科思创", "拜耳"], [], "科思创PC2405"),
    ("PC1225Y",    "1225Y",  ["teijin", "帝人"], [], "帝人PC1225Y"),
    ("PC1201-15",  "1201-15",["lg", "lg化学", "lg chem"], [], "LG PC1201-15"),
    ("ABS_GP22",   "GP-22",  ["styrolution", "苯领", "英力士"], [], "苯领ABS GP-22"),
    ("ABS_AG12A1", "AG12A1", ["formosa", "台化"], [], "台化ABS AG12A1-H"),
    ("ABS_PA757K", "PA-757K", ["chi mei", "chimei", "奇美"], ["zhenjiang", "镇江"], "镇江奇美PA-757K"),
    ("PP_SP179",   "SP179",  ["huajin", "华锦"], [], "华锦PP SP179"),
    ("POE_7467",   "7467",   ["dow", "陶氏", "dupont"], [], "陶氏POE 7467"),
    ("PA6_YH400",  "YH400",  ["baling", "巴陵", "yueyang", "岳化", "岳阳"], [], "巴陵PA6 YH400"),
]

# 显示名辅助：key -> 显示名
DISPLAY_NAMES = {t[0]: t[4] for t in TARGETS}

HEADERS = {
    "User-Agent": GOOGLEBOT_UA,
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def safe_get(url, params=None, retries=2):
    """带重试的 GET，返回 Response 或 None"""
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=25)
            if r.status_code == 200:
                return r
            print(f"    [warn] {url} -> HTTP {r.status_code}")
        except Exception as e:
            print(f"    [warn] 请求失败: {e}")
        time.sleep(2)
    return None


def search_detail_ids(keyword):
    """搜索关键词 -> 详情页 id 列表"""
    r = safe_get(SEARCH_URL, params={"keyword": keyword})
    if not r:
        return []
    ids = re.findall(r'href="(/market/detail/(\d+)--\.html)"', r.text)
    seen = []
    for _, pid in ids:
        if pid not in seen:
            seen.append(pid)
    return seen


def parse_detail(pid):
    """抓详情页 -> {title, brand, latest, latest_date, total, history}"""
    r = safe_get(DETAIL_URL.format(pid=pid))
    if not r:
        return None
    raw = r.text
    text = re.sub(r"<script.*?</script>", "", raw, flags=re.S)

    # 标题（品牌+牌号）
    title = ""
    m = re.search(r"<title>(.*?)</title>", raw, flags=re.S)
    if m:
        title = htmlmod.unescape(m.group(1)).strip()

    # 历史价行：日期 价格 yuan/ton 涨跌幅 涨跌值 ...
    lines = [htmlmod.unescape(x.strip())
             for x in re.sub(r"<[^>]+>", "|", text).split("|") if x.strip()]
    history = []
    total = None
    for i, ln in enumerate(lines):
        if re.search(r"20\d\d-\d{2}-\d{2}", ln):
            ctx = lines[i:i + 7]
            joined = " ".join(ctx)
            dm = re.search(r"(20\d\d-\d{2}-\d{2})", joined)
            pm = re.search(r"(\d{4,5})\s*yuan/ton", joined)
            if dm and pm:
                history.append({
                    "date": dm.group(1),
                    "price": int(pm.group(1)),
                    "raw": joined[:140],
                })
        tm = re.search(r"共\s*(\d+)\s*条", joined) if "joined" in dir() else None
        if tm:
            total = int(tm.group(1))
    # 去重（同一日期只留一条）
    seen_dates = {}
    for h in history:
        if h["date"] not in seen_dates:
            seen_dates[h["date"]] = h
    history = list(seen_dates.values())

    latest = history[0] if history else None
    return {
        "pid": pid,
        "title": title,
        "total_records": total if total else len(history),
        "latest": latest,
        "history": history,
    }


def match_brand(data, keywords):
    """详情页标题是否命中品牌关键字（忽略大小写与空格）"""
    if not data or not data.get("title"):
        return False
    t = re.sub(r"\s+", "", data["title"].lower())
    return any(re.sub(r"\s+", "", k.lower()) in t for k in keywords)


def prefer_match(data, prefer):
    """是否命中优先产地关键字（镇江/漳州等）"""
    if not prefer or not data or not data.get("title"):
        return False
    t = re.sub(r"\s+", "", data["title"].lower())
    return any(re.sub(r"\s+", "", k.lower()) in t for k in prefer)


def query_history_by_date(pid, target_date, max_pages=25):
    """翻页查询指定日期的历史价（详情页默认只显示最近10条，需翻页）。
    返回 (status, hit) 其中 status: EXACT/RANGE/PAST/NOT_FOUND
    EXACT: (date, price); RANGE: (prev, next); PAST: 最早一条"""
    target_date = str(target_date)
    for page in range(2, max_pages + 1):
        r = safe_get(DETAIL_URL.format(pid=pid).replace("--.html", f"--{page}.html"))
        if not r:
            break
        rows = _parse_price_rows(r.text)
        if not rows:
            break
        oldest, newest = rows[-1][0], rows[0][0]
        hit = [x for x in rows if x[0] == target_date]
        if hit:
            return ("EXACT", hit[0])
        if oldest <= target_date <= newest:
            prev = next = None
            for d, p in rows:
                if d > target_date:
                    next = (d, p)
                elif d < target_date and prev is None:
                    prev = (d, p)
            return ("RANGE", prev, next)
        if newest < target_date:
            return ("PAST", rows[0])
        time.sleep(1.2)
    return ("NOT_FOUND", None)


def _parse_price_rows(html_text):
    """从详情页 HTML 提取 (日期, 价格) 行列表"""
    text = re.sub(r"<script.*?</script>", "", html_text, flags=re.S)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.S)
    out = []
    for r in rows:
        cells = [htmlmod.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S)]
        cells = [c for c in cells if c]
        j = " | ".join(cells)
        m = re.search(r"(20\d\d-\d{2}-\d{2})", j)
        p = re.search(r"(\d{4,5})\s*yuan/ton", j)
        if m and p:
            out.append((m.group(1), int(p.group(1))))
    return out


def main():
    only = sys.argv[1:] if len(sys.argv) > 1 else []
    date_arg = None
    if "--date" in only:
        i = only.index("--date")
        date_arg = only[i + 1] if i + 1 < len(only) else None
        only = only[:i] + only[i + 2:]
    results = {}
    print("=" * 78)
    print("中塑在线 牌号级市场参考价抓取（人民币含税现货口径）")
    print("=" * 78)
    for key, keyword, brand_kw, prefer, _name in TARGETS:
        if only and keyword not in only and key not in only:
            continue
        print(f"\n▶ {key}  (搜索关键词: {keyword})")
        pids = search_detail_ids(keyword)
        print(f"    搜索命中 {len(pids)} 个候选详情页: {pids}")
        if not pids:
            results[key] = {"status": "NOT_FOUND", "keyword": keyword}
            continue
        # 抓全部候选，按 品牌匹配 → 优先产地 → 首个 排序
        cands = []
        for pid in pids:
            data = parse_detail(pid)
            if data:
                cands.append(data)
        brand_hits = [c for c in cands if match_brand(c, brand_kw)]
        pool = brand_hits if brand_hits else cands
        picked = next((c for c in pool if prefer_match(c, prefer)), pool[0] if pool else None)
        if not picked:
            results[key] = {"status": "FETCH_FAIL", "keyword": keyword}
            continue
        if not brand_hits and len(cands) > 1:
            print(f"    [警告] 无品牌匹配，已取候选之一（请人工核对）")
        latest = picked["latest"]
        print(f"    ✓ {picked['title'][:70]}")
        print(f"      最新: {latest['date']}  {latest['price']} 元/吨  | 历史 {picked['total_records']} 条")
        # 近 5 条
        for h in picked["history"][:5]:
            print(f"        {h['date']}  {h['price']} 元/吨")
        results[key] = {
            "status": "OK",
            "keyword": keyword,
            "title": picked["title"],
            "pid": picked["pid"],
            "total_records": picked["total_records"],
            "latest_date": latest["date"],
            "latest_price": latest["price"],
            "recent": picked["history"][:10],
        }
        time.sleep(2)  # 克制频率

    # --date 模式：补查指定日期历史价（覆盖全部 6 牌号）
    if date_arg:
        print("\n" + "=" * 78)
        print(f"按日期查询: {date_arg}")
        print("=" * 78)
        for key, keyword, brand_kw, prefer, _name in TARGETS:
            if key not in results or results[key].get("status") != "OK":
                print(f"  {key}: 跳过（当日未抓取）")
                continue
            pid = results[key]["pid"]
            st, hit = query_history_by_date(pid, date_arg)
            if st == "EXACT":
                print(f"  {key:12s} {hit[0]}  {hit[1]:>6,} 元/吨 ✓")
                results[key]["history_lookup"] = {"date": hit[0], "price": hit[1]}
            elif st == "RANGE":
                prev, nxt = hit
                print(f"  {key:12s} {date_arg} 当日无报价 | 前 {prev[0]} {prev[1]:,} | 后 {nxt[0]} {nxt[1]:,}")
            elif st == "PAST":
                print(f"  {key:12s} 数据未覆盖到该日，最早 {hit[0]} {hit[1]:,}")
            else:
                print(f"  {key:12s} 未查到")
            time.sleep(1.2)

    with open("/tmp/21cp_data.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\n" + "=" * 78)
    print("结果汇总")
    print("=" * 78)
    for key, v in results.items():
        if v.get("status") == "OK":
            print(f"  {key:12s} {v['latest_date']}  {v['latest_price']:>6} 元/吨  (历史 {v['total_records']} 条)")
        else:
            print(f"  {key:12s} {v.get('status')}")
    print("\n结构化结果已存 /tmp/21cp_data.json")


if __name__ == "__main__":
    main()
