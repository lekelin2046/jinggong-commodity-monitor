"""隆众价格中心：目标品类 → varietiesId / channelId 映射（免登录可做）

价格中心接口族（dc.oilchem.net，均为公开元数据接口）：
  GET /ndc/common/fuzzyQueryBreeds?keyword=X          → 搜品种，拿 varietiesId
  GET /ndc/price/list/queryVarietiesByChannelId?channelId=N
  GET /ndc/price/list/queryBusinessTypeByVarietiesId?varietiesId=N
  POST /ndc/price/list/queryPricePage                  → 价格数据（未登录 price 字段="请登录"）

本脚本只做映射，不取价格。产出 data/probe_dc/variety_map.json
用途：登录态到位后，用 varietiesId 直接调 queryPricePage 取价。
"""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "data" / "probe_dc"  # 2026-09-23 整理：本文件位于 tools/probes/，根目录上溯两级
OUT.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 用户需求里的品类关键词（含牌号，多搜几个词提高命中）
KEYWORDS = [
    "原油", "布伦特",
    "乙烯", "丙烯",
    "三元乙丙", "乙丙橡胶", "EPDM",
    "煤焦油", "炭黑",
    "天然橡胶", "全乳胶", "SCRWF", "RSS3",
    "顺丁橡胶", "丁苯橡胶",
    "防老剂", "促进剂",
    # 铝（作对照，SMM 已覆盖）
    "铝",
]


def get(url: str) -> dict:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    req.add_header("Referer", "https://dc.oilchem.net/page/")
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def search(kw: str) -> list:
    url = ("https://dc.oilchem.net/ndc/common/fuzzyQueryBreeds?keyword="
           + urllib.parse.quote(kw))
    try:
        d = get(url)
        if d.get("status") != "200":
            return []
        return d.get("response") or []
    except Exception as e:
        print(f"    [warn] {kw} 查询异常: {e}")
        return []


def main():
    print("=" * 76)
    print("隆众价格中心 目标品类 → varietiesId 映射（免登录）")
    print("=" * 76)

    result = {}
    for kw in KEYWORDS:
        items = search(kw)
        result[kw] = items
        print(f"\n[{kw}] 命中 {len(items)} 个")
        for it in items[:14]:
            print(f"    id={it.get('id'):<7} name={it.get('name')}"
                  f"  短名={it.get('shortName') or '-'}  alias={it.get('aliasName') or '-'}")
        time.sleep(0.4)     # 轻量节流

    OUT.joinpath("variety_map.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n映射表 → {OUT/'variety_map.json'}")

    # 汇总：用户需求逐项对照
    print()
    print("=" * 76)
    print("需求逐项对照")
    print("=" * 76)
    need = {
        "原油 BENT": ["原油", "布伦特"],
        "乙烯": ["乙烯"], "丙烯": ["丙烯"],
        "三元乙丙 6950C/3110M/13561C": ["三元乙丙", "乙丙橡胶", "EPDM"],
        "煤焦油": ["煤焦油"], "炭黑 N550": ["炭黑"],
        "天然橡胶 SCRWF / RSS3": ["天然橡胶", "全乳胶", "SCRWF", "RSS3"],
        "合成橡胶 顺丁9000 / 丁苯1712": ["顺丁橡胶", "丁苯橡胶"],
        "防老剂 4020": ["防老剂"],
        "促进剂 DM/CZ/M/TMTD": ["促进剂"],
    }
    for name, kws in need.items():
        hits = []
        for k in kws:
            for it in result.get(k, []):
                hits.append(f"{it.get('name')}(id={it.get('id')})")
        uniq = list(dict.fromkeys(hits))
        mark = "✓" if uniq else "✗"
        print(f"  {mark} {name}: {', '.join(uniq[:6]) if uniq else '未命中'}")


if __name__ == "__main__":
    main()
