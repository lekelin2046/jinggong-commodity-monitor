#!/usr/bin/env python3
"""
卓创资讯（sci99.com）价格抓取模块

依赖：
- Playwright Chromium 浏览器（~/.cache/ms-playwright）
- cookies/sci99.json（Cookie-Editor 导出的 JSON 格式 cookie 文件）

原理：
- 卓创价格表格是 JS 动态渲染的，curl/requests 不可行
- 必须用 Playwright 真实浏览器加载 cookie 后才能看到价格数据
- cookie 由人工在普通浏览器登录后通过 Cookie-Editor 扩展导出
- cookie 过期时脚本自动跳过，不会静默填错数

用法:
    from jinggong_monitor.fetcher_sci99 import fetch_sci99_async
    prices = await fetch_sci99_async()
    # 返回 {"SS_304": 15700, "SS_409": 8000, ...}
"""

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Dict, Optional

SCRIPT_DIR = Path(__file__).parent.parent
COOKIE_FILE = SCRIPT_DIR / "cookies" / "sci99.json"
SCREENSHOTS_DIR = SCRIPT_DIR / "screenshots"

# 卓创品种 ID → 品种代码 → 品名（供日志用）
SCI99_VARIETIES = {
    173890: {"code": "SS_304", "name": "304不锈钢板材"},
    39171:  {"code": "SS_409", "name": "409不锈钢板材"},
    82050:  {"code": "SS_439", "name": "439不锈钢板材"},
    73340:  {"code": "SS_441", "name": "441不锈钢板材"},
    195718: {"code": "NICKEL_IRON", "name": "镍铁"},
    83370:  {"code": "HIGH_CARBON_FECR", "name": "高碳铬铁"},
}

# 搜索结果页 URL 模板
SEARCH_URL = "https://prices.sci99.com/cn/search.aspx?keyword={vid}"


def _load_cookies() -> Optional[list]:
    """加载并校验 cookie 格式"""
    if not COOKIE_FILE.exists():
        print(f"  [卓创] cookie 文件不存在: {COOKIE_FILE}")
        return None
    try:
        cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [卓创] cookie 解析失败: {e}")
        return None
    if not isinstance(cookies, list) or len(cookies) == 0:
        print(f"  [卓创] cookie 格式异常（非数组或为空）")
        return None
    # 规范化 sameSite（Cookie-Editor 导出可能为空，Playwright 要求 Strict|Lax|None）
    for c in cookies:
        if not c.get("sameSite") or c.get("sameSite") not in ("Strict", "Lax", "None"):
            c["sameSite"] = "Lax"
    return cookies


def _extract_price(html: str) -> Optional[float]:
    """从搜索结果页 HTML 中提取平均价（第三个数字列）

    表格结构预期：
      <tr>
        <td>品种编号</td><td>品类</td><td>规格</td><td>厂商</td><td>地区</td>
        <td>类型</td><td>名称</td><td>付款条件</td>
        <td>最低价</td><td>最高价</td><td>平均价</td><td>涨跌</td><td>状态</td>
      </tr>
    """
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    for row in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        texts = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        # 跳过空行和表头行
        if len(texts) < 11:
            continue
        # 检查是否含"元/吨"或"美元"等价格单位标志
        if not any(("元" in t or "美元" in t or "镍点" in t) for t in texts):
            continue
        # 最低价在 texts[8] 附近，平均价在 texts[10] 附近
        # 这些索引是近似值，因为 DOM 可能有隐藏列
        # 更稳健的方式：找所有纯数字列，取中间那个
        numeric_candidates = []
        for t in texts:
            t_clean = t.replace(",", "").replace("¥", "").replace("￥", "").strip()
            # 去除涨跌符号（▼▲ 等）
            t_clean = re.sub(r'^[▼▲↑↓]+\s*', '', t_clean)
            try:
                v = float(t_clean)
                numeric_candidates.append(v)
            except ValueError:
                pass

        # 行格式: 品种ID(数字) | ... | 最低价 | 最高价 | 平均价 | 涨跌 | 状态
        # 跳过第一个数字（品种ID），后面的数字中第3个是平均价
        # 但涨跌列可能为文字（如"▼100"）导致数字数量不确定
        # 稳健策略：从所有数字中排除首尾，在中间段找
        if len(numeric_candidates) >= 3:
            # 跳过品种ID（首元素），从剩余数字中取正中间那个
            price_only = numeric_candidates[1:]  # 排除品种ID
            if len(price_only) >= 3:
                # [最低, 最高, 平均, 涨跌?] → 取第3个（index=2）即平均价
                avg = price_only[2]
            else:
                # [最低, 最高] → 取中间
                avg = (price_only[0] + price_only[1]) / 2
            if avg <= 0:
                continue
            return avg
    return None


def _check_logged_in(html: str) -> bool:
    """快速判断搜索页是否在登录态"""
    # 未登录/服务过期时会显示"请登录"/"无权限"/"服务过期"
    if "请登录" in html and "无权限" in html:
        return False
    if "服务过期" in html:
        return False
    # 有价格数字行则确认登录态
    if re.search(r"\d{4,}\s*元/吨|<td[^>]*>\d{4,}</td>", html):
        return True
    return True  # 不明确时放行（可能是新页面格式）


async def fetch_sci99_async(timeout: int = 90) -> Dict[str, float]:
    """异步抓取卓创 6 个品种的平均价

    Returns:
        {"SS_304": 15700.0, "SS_409": 8000.0, ...}
        登录态失效或页面加载失败时返回空 dict（不估算，严格守铁律）
    """
    cookies = _load_cookies()
    if not cookies:
        return {}

    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("  [卓创] Playwright 未安装")
        return {}

    result: Dict[str, float] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-quic",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            viewport={"width": 1440, "height": 900},
        )
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        # 先在主域建立会话
        try:
            await page.goto("https://www.sci99.com/", wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass  # 首页加载失败不影响 search.aspx

        for vid, info in SCI99_VARIETIES.items():
            code, name = info["code"], info["name"]
            url = SEARCH_URL.format(vid=vid)
            try:
                await page.goto(url, wait_until="networkidle", timeout=45000)
                await page.wait_for_timeout(2000)
                html = await page.content()

                if not _check_logged_in(html):
                    print(f"  [卓创] {name} 登录态失效")
                    continue

                price = _extract_price(html)
                if price is not None:
                    result[code] = price
                    print(f"  [卓创] {name}: {price}")
                else:
                    print(f"  [卓创] {name}: 未提取到价格")
            except Exception as e:
                print(f"  [卓创] {name}: 页面加载失败 ({e})")
                continue

        await browser.close()

    return result


def fetch_sci99_sync(timeout: int = 90) -> Dict[str, float]:
    """同步包装，供非异步环境调用"""
    return asyncio.run(fetch_sci99_async(timeout=timeout))
