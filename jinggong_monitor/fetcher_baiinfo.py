"""百川盈孚（baiinfo.com）抓取器 —— 高温煤焦油

背景（2026-09-17 实测）
------------------------------------------------------------------
百川**免登录**：价格以 SSR 内嵌的自然语言句形式出现在品种页 HTML 里，
形如：

    百川盈孚提示：2026年9月17日，高温煤焦油市场均价6516元/吨，
    相较于上一工作日上调21元/吨。煤焦油供需面支撑仍存……

因此不需要浏览器、不需要登录，正则直接抠「日期 + 均价 + 涨跌」即可。
（同一页面还有 CCTX 中国煤焦油现货价指数，口径不同，本项目不取。）

⚠️ 措辞陷阱：涨跌部分用的是「**相较于**上一工作日上调21元/吨」，
   不是「较上一工作日…」。按后者写正则会静默匹配失败。

品种页：
  高温煤焦油  /meijiaohua/gaowenmeijiaoyou
  中温煤焦油  /meijiaohua/zhongwenmeijiaoyou（备用，本项目未启用）

铁律：任一项解析失败 → 整体返回 None（不编造、不沿用前值）。
"""
from __future__ import annotations

import html
import logging
import re
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger("jinggong.fetcher.baiinfo")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

PAGES = {
    "COAL_TAR_HIGH": "https://www.baiinfo.com/meijiaohua/gaowenmeijiaoyou",
}

# 日期 + 市场均价（允许标签/空白分隔）
_RE_DATE_PRICE = re.compile(
    r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日[，,]?\s*"
    r"高温煤焦油市场均价\s*([\d,]+)\s*元/吨"
)
# 涨跌（注意「相较于」）
_RE_CHANGE = re.compile(
    r"相较于上一工作日\s*(上调|下调|持平|上涨|下跌)\s*([\d,]+)?\s*元/吨"
)


def _strip_tags(raw: str) -> str:
    """去标签 + 反转义，保留文本用于正则"""
    t = re.sub(r"<script.*?</script>", "", raw, flags=re.S)
    t = re.sub(r"<style.*?</style>", "", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    return re.sub(r"[ \t\u00a0]+", " ", t)


def fetch_page(url: str, timeout: int = 30) -> Optional[str]:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    req.add_header("Accept-Language", "zh-CN,zh;q=0.9")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "ignore")
        return _strip_tags(raw)
    except (urllib.error.URLError, OSError) as e:
        logger.warning("百川抓取失败 %s: %s", url, e)
        return None


def parse_coal_tar(text: str) -> Optional[dict]:
    """从页面文本解析高温煤焦油。返回 {date, price, change, change_word} 或 None"""
    m = _RE_DATE_PRICE.search(text)
    if not m:
        logger.warning("百川：未匹配到「日期 + 高温煤焦油市场均价」")
        return None
    y, mo, d, price = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
    try:
        price_v = float(price.replace(",", ""))
    except ValueError:
        logger.warning("百川：均价无法转数值 %r", price)
        return None
    if not (100 <= price_v <= 100000):
        logger.warning("百川：均价超出合理区间 %s，视为异常", price_v)
        return None

    chg = None
    word = ""
    mc = _RE_CHANGE.search(text)
    if mc:
        word = mc.group(1)
        if word in ("持平",):
            chg = 0.0
        elif mc.group(2):
            try:
                v = float(mc.group(2).replace(",", ""))
                chg = -v if word in ("下调", "下跌") else v
            except ValueError:
                chg = None
    return {"date": f"{y}-{mo:02d}-{d:02d}", "price": price_v,
            "change": chg, "change_word": word}


def fetch_coal_tar(key: str = "COAL_TAR_HIGH") -> Optional[dict]:
    """抓取高温煤焦油。取不到返回 None（铁律）。"""
    url = PAGES.get(key)
    if not url:
        raise KeyError(f"未知百川品种: {key}")
    text = fetch_page(url)
    if not text:
        return None
    r = parse_coal_tar(text)
    if r:
        logger.info("百川 %s: %s %s 元/吨 (涨跌 %s)",
                    key, r["date"], r["price"], r["change"])
    return r


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    r = fetch_coal_tar()
    if r:
        print(f"✓ 高温煤焦油 {r['date']}  {r['price']:.0f} 元/吨  "
              f"涨跌 {r['change']} ({r['change_word']})")
    else:
        print("✗ 未取到（留空）")
        sys.exit(1)
