#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_lz_gate.py — 严格复核隆众资讯（oilchem）文章的数据门槛

背景：初次探测仅用「暂未登录」字符串判断，过于粗糙。
     本次对同一批文章同时检测：
       (a) 门槛标记（登录/会员/订阅/免费开通/致电热线 等）
       (b) 正文是否真含价格数字（元/吨 或 表格数值）
     并打印正文首段，便于人工判读。
"""
import re
import html
import subprocess
import sys

UA_DESKTOP = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

ARTICLES = {
    "天然橡胶价格汇总": "https://www.oilchem.net/26-0916-17-66f8295a0e00e000.html",
    "顺丁橡胶出厂价格一览表": "https://www.oilchem.net/26-0916-16-e7a54bfe4c3f002a.html",
    "丁苯橡胶价格汇总": "https://www.oilchem.net/26-0916-17-5e88904494f23666.html",
    "顺丁橡胶早间提示": "https://www.oilchem.net/26-0917-08-567c477c8a18f4c0.html",
    "炭黑早间提示": "https://www.oilchem.net/26-0917-08-d39d75a4b09997dd.html",
    "炭黑日评": "https://www.oilchem.net/26-0916-16-5920a73253394206.html",
    "天胶日评": "https://www.oilchem.net/26-0916-17-a0dee3b42efc44d0.html",
    "促进剂防老剂周评": "https://www.oilchem.net/26-0910-17-4ccec7b874838ea5.html",
    "三元乙丙月评": "https://www.oilchem.net/26-0828-17-6db7961082308c78.html",
}

GATE_MARKERS = ["暂未登录", "免费开通", "会员登录", "15天的免费浏览权",
                "请您致电资讯热线", "开通会员", "登录后查看"]


def fetch(url):
    r = subprocess.run(
        ["curl", "-s", "--compressed", "--max-time", "30", "-A", UA_DESKTOP, url],
        capture_output=True)
    return r.stdout.decode("utf-8", "ignore")


def to_text(t):
    b = re.sub(r"<script.*?</script>", "", t, flags=re.S)
    b = re.sub(r"<style.*?</style>", "", b, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", b))


def main():
    for name, url in ARTICLES.items():
        raw = fetch(url)
        txt = to_text(raw)
        hits = [m for m in GATE_MARKERS if m in txt]
        # 正文价格特征：元/吨 的数值，或 NNNN~NNNN 区间
        prices = re.findall(r"(\d{3,6})\s*[-~]\s*(\d{3,6})", txt)
        yuan = len(re.findall(r"元/吨", txt))
        # 定位正文起止
        i = txt.find("当前位置")
        j = txt.find("免责声明")
        body = re.sub(r"\s+", " ", txt[i:j]) if i >= 0 and j > i else ""
        print("=" * 78)
        print(f"【{name}】")
        print(f"  HTTP字节={len(raw)}  门槛标记={hits or '无'}")
        print(f"  区间价对={len(prices)}  含'元/吨'次数={yuan}")
        print(f"  正文长度={len(body)}")
        if body:
            print(f"  正文抽样: {body[:700]}")
        print()


if __name__ == "__main__":
    main()
