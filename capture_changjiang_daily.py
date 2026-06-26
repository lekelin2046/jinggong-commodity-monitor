#!/usr/bin/env python3
"""
每日 10:00 工作日抓取长江有色（ccmn.cn/cjxh.shtml）数据归档。

输出（只生成数据，不截图）：
1. Markdown 数据：~/Desktop/AI/jinggong-commodity-monitor/长城有色日价格查询/YYYY-MM-DD_长江有色.md
2. Obsidian 归档：~/Documents/Obsidian Vault/工作/大宗原材料监控/日报/YYYY-MM-DD-长江有色.md

依赖：无（纯 requests + 文件 IO）
触发：openclaw cron 每周一到周五 10:00
"""
import sys, os, json
from datetime import datetime
from pathlib import Path
import urllib.request

# 路径
PROJECT_DIR = Path("/Users/siqi/Desktop/AI/jinggong-commodity-monitor")
SAVE_DIR = PROJECT_DIR / "长城有色日价格查询"
OBSIDIAN_DIR = Path("/Users/siqi/Documents/Obsidian Vault/工作/大宗原材料监控/日报")

CCMN_AJAX = "https://www.ccmn.cn/shop/historyData/getCorpStmarketPriceList"
CCMN_MARKET = "40288092327140f601327141c0560001"  # 长江现货
CCMN_PAGE_URL = "https://www.ccmn.cn/cjxh.shtml"

def ensure_dirs():
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    OBSIDIAN_DIR.mkdir(parents=True, exist_ok=True)

def fetch_prices(date_str):
    """拉 ccmn 当日所有品种均价（公开 AJAX，不需要登录）"""
    data = (
        f"marketVmid={CCMN_MARKET}"
        f"&publishDate={date_str}"
        f"&flag=1&productVmid="
    ).encode("utf-8")
    req = urllib.request.Request(
        CCMN_AJAX,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": "https://www.ccmn.cn/cjxh.shtml",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

def render_markdown(date_str, price_list, fetch_time):
    """把价格数据渲染成 markdown 表格"""
    # 重点品种（按精工业务重要性排序）
    key_varieties = [
        "1#铜", "A00铝", "0#锌", "1#锌", "1#铅", "1#镍", "1#锡",
        "441#硅", "553#硅", "3303#硅", "2202#硅",
        "金属硅553#-331#", "金属硅3303#-2202#",
        "1#镁", "1#电解锰", "1#电解锰(99.7%袋装)",
        "铝合金ADC12", "铸造铝合金锭(A356.2)", "铸造铝合金锭(A380）",
    ]
    by_name = {item["productSortName"]: item for item in price_list}

    lines = []
    lines.append(f"# 长江有色现货报价 · {date_str}")
    lines.append("")
    lines.append(f"> 数据源：[长江有色金属网 ccmn.cn]({CCMN_PAGE_URL}) · "
                 f"市场：长江现货 · 抓取时间：{fetch_time}")
    lines.append("")
    lines.append("## 重点品种")
    lines.append("")
    lines.append("| 品种 | 最低 | 最高 | **均价** | 涨跌 | 单位 |")
    lines.append("|------|------|------|----------|------|------|")
    for v in key_varieties:
        if v in by_name:
            it = by_name[v]
            lines.append(
                f"| {v} | {it['minPrice']} | {it['maxPrice']} | "
                f"**{it['avgPrice']:.0f}** | {it['highsLowsAmount']:+.0f} | {it['unit']} |"
            )
    lines.append("")
    lines.append("## 全部品种")
    lines.append("")
    lines.append("| 品种 | 最低 | 最高 | 均价 | 涨跌 | 单位 |")
    lines.append("|------|------|------|------|------|------|")
    for it in sorted(price_list, key=lambda x: x["productSortName"]):
        lines.append(
            f"| {it['productSortName']} | {it['minPrice']} | {it['maxPrice']} | "
            f"{it['avgPrice']:.0f} | {it['highsLowsAmount']:+.0f} | {it['unit']} |"
        )
    lines.append("")
    lines.append("---")
    lines.append(f"共 {len(price_list)} 个品种 · 抓取脚本：`capture_changjiang_daily.py`")
    return "\n".join(lines)

def main():
    ensure_dirs()
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    fetch_time = now.strftime("%Y-%m-%d %H:%M:%S")

    print(f"[{now.strftime('%H:%M:%S')}] 开始抓取 {date_str} 长江有色...")

    # 1. 拉数据
    try:
        result = fetch_prices(date_str)
        price_list = result["body"]["priceList"]
        print(f"  ✅ 拉到 {len(price_list)} 个品种")
    except Exception as e:
        print(f"  ❌ AJAX 失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 2. 渲染 markdown
    md_content = render_markdown(date_str, price_list, fetch_time)

    # 3. 保存到项目目录
    md_file = SAVE_DIR / f"{date_str}_长江有色.md"
    md_file.write_text(md_content, encoding="utf-8")
    print(f"  ✅ 项目目录: {md_file}")

    # 4. 保存到 Obsidian Vault
    obs_file = OBSIDIAN_DIR / f"{date_str}-长江有色.md"
    obs_file.write_text(md_content, encoding="utf-8")
    print(f"  ✅ Obsidian:  {obs_file}")

    print(f"[{now.strftime('%H:%M:%S')}] 完成 ✅")

if __name__ == "__main__":
    main()