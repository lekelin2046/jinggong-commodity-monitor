"""SMM 上海有色网数据抓取器（SSR + Cookies 复用模式）

核心思路：
1. 优先用已存的 cookies 访问 hq.smm.cn/aluminum 和 /magnesium 两个聚合页
2. SMM 价格是 SSR 渲染在 HTML 里的，直接正则提取，无需调 API、无需访问品种详情页
3. cookies 失效时才重新登录（登录一次约 8s，cookies 有效期约 7 天）

数据来源: hq.smm.cn
目标品种: ADC12, A380, AlSi9Cu3, A356, AM60B, AZ91D, 闻喜镁锭

性能对比（vs 旧方案）：
- 旧方案：访问 7 个品种详情页，每页 3-5s，总耗时 25-40s
- 新方案：2 个聚合页，每页 5s（等 SSR 渲染），总耗时 10-12s
- cookies 复用：跳过登录（8s），二次抓取仅 10s
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

from jinggong_monitor.base import BaseFetcher, FetchError
from jinggong_monitor.credentials import require_smm

logger = logging.getLogger("jinggong.fetcher.smm")

# 代理配置（防止代理拦截国内站点）
os.environ.setdefault("NO_PROXY", "smm.cn,hq.smm.cn,user.smm.cn")
os.environ.setdefault("no_proxy", os.environ["NO_PROXY"])

COOKIE_FILE = Path(__file__).parent.parent / "data" / "smm_cookies.json"

# 截图目录（相对于项目根，不再硬编码绝对路径）
_SHOT_DIR = Path(__file__).parent.parent / "screenshots" / datetime.now().strftime("%Y-%m-%d")

# SMM 聚合页 URL（SSR 渲染，含全部品种价格）
SMM_PAGES = {
    "aluminum": "https://hq.smm.cn/aluminum",
    "magnesium": "https://hq.smm.cn/magnesium",
    "alloy_chart": "https://hq.smm.cn/h5/aluminum-alloy-price-chart",
}

# 品种 → 页面 → 正则模式
# 正则匹配格式：品种名 [中间描述] 低价~高价 均价
SMM_VARIETIES = {
    "ADC12": {
        "page": "aluminum",
        "pattern": r"SMM铝合金ADC12\s+(\d{4,6})~(\d{4,6})\s+(\d{4,6})",
    },
    "A380": {
        "page": "aluminum",
        "pattern": r"A380铝合金\s+(\d{4,6})~(\d{4,6})\s+(\d{4,6})",
    },
    "A356": {
        "page": "aluminum",
        "pattern": r"A356铝合金\s+(\d{4,6})~(\d{4,6})\s+(\d{4,6})",
    },
    "AlSi9Cu3": {
        "page": "aluminum",
        "pattern": r"AlSi9Cu3铝合金\s+(\d{4,6})~(\d{4,6})\s+(\d{4,6})",
    },
    "AM60B": {
        "page": "magnesium",
        "pattern": r"AM60B出厂价\s+(\d{4,6})~(\d{4,6})\s+(\d{4,6})",
    },
    "AZ91D": {
        "page": "magnesium",
        "pattern": r"AZ91D出厂价\s+(\d{4,6})~(\d{4,6})\s+(\d{4,6})",
    },
    "WenxiMG": {
        "page": "magnesium",
        "pattern": r"镁锭9990（闻喜）\s+(\d{4,6})~(\d{4,6})\s+(\d{4,6})",
    },
    "ADC12_JAPAN_CIF": {
        "page": "alloy_chart",
        "pattern": r"日本进口ADC12铝合金价格\s+(\d{4})\s*-\s*(\d{4})\s+(\d{4})",
    },
}


async def _login_and_save_cookies(ctx) -> bool:
    """登录 SMM 并保存 cookies 到 data/smm_cookies.json

    Returns: True 登录成功，False 失败
    """
    smm_user, smm_pass = require_smm()
    page = await ctx.new_page()
    try:
        await page.goto("https://user.smm.cn/login", timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        await page.locator("#userName").fill(smm_user)
        await page.locator("#password").fill(smm_pass)
        await page.locator("#user_account_password_login_button").click()
        await asyncio.sleep(8)
        ok = "login" not in page.url.lower()
        if ok:
            cookies = await ctx.cookies()
            COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
            COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2))
            logger.info(f"SMM 登录成功，cookies 已保存 ({len(cookies)} 个)")
        else:
            logger.error("SMM 登录失败：URL 仍含 login")
        return ok
    finally:
        await page.close()


async def _fetch_page_text(ctx, page_url: str) -> str:
    """用 cookies 访问页面，返回 body innerText"""
    page = await ctx.new_page()
    try:
        await page.goto(page_url, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)  # 等 SSR 渲染
        return await page.inner_text("body")
    finally:
        await page.close()


async def _fetch_smm_raw(target_date: Optional[str] = None) -> dict:
    """抓取 SMM 全部品种价格

    流程：
    1. 加载 cookies（若有）
    2. 访问铝页 + 镁页，正则提取价格
    3. 若价格提取失败（cookies 过期），重新登录后重试一次
    """
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = await b.new_context()
            # 加载已有 cookies
            if COOKIE_FILE.exists():
                cookies = json.loads(COOKIE_FILE.read_text())
                await ctx.add_cookies(cookies)
                logger.info(f"已加载 {len(cookies)} 个 cookies")
            else:
                logger.info("无 cookies 文件，需登录")

            # 抓两个页面
            texts = {}
            for page_name, url in SMM_PAGES.items():
                try:
                    texts[page_name] = await _fetch_page_text(ctx, url)
                except Exception as e:
                    logger.warning(f"抓 {page_name} 页失败: {e}")
                    texts[page_name] = ""

            # 解析价格
            results = _parse_prices(texts)

            # 若一个都没拿到，可能 cookies 过期，重新登录
            if not results:
                logger.warning("未提取到任何价格，cookies 可能过期，重新登录")
                await _login_and_save_cookies(ctx)
                # 重新抓
                for page_name, url in SMM_PAGES.items():
                    try:
                        texts[page_name] = await _fetch_page_text(ctx, url)
                    except Exception as e:
                        logger.warning(f"重试抓 {page_name} 页失败: {e}")
                        texts[page_name] = ""
                results = _parse_prices(texts)

            return results
        finally:
            await b.close()


def _parse_prices(texts: dict) -> dict:
    """从页面文本解析价格

    Args:
        texts: {"aluminum": "...", "magnesium": "..."}
    Returns:
        {"ADC12": 24000, "A380": 25900, ...}（均价）
    """
    results = {}
    for variety, cfg in SMM_VARIETIES.items():
        text = texts.get(cfg["page"], "")
        m = re.search(cfg["pattern"], text)
        if m:
            low, high, avg = int(m.group(1)), int(m.group(2)), int(m.group(3))
            # 简单合理性检查：低价 ≤ 均价 ≤ 高价，且都在 100-100000 区间
            if low <= avg <= high and 100 <= avg <= 100000:
                results[variety] = float(avg)
                logger.info(f"  ✅ {variety}: {low}~{high}, 均价 {avg}")
            else:
                logger.warning(f"  ⚠️ {variety} 价格异常: {low}~{high} avg={avg}，跳过")
        else:
            logger.warning(f"  ❌ {variety}: 正则未匹配")
    return results


class SmmFetcher(BaseFetcher):
    """SMM 抓取器（SSR + Cookies 复用）"""

    def fetch(self, target_date: Optional[str] = None) -> dict:
        """抓取 SMM 7 品种价格

        Args:
            target_date: 目标日期（YYYY-MM-DD），SMM 只能抓当日，此参数仅用于日志
        Returns:
            {"ADC12": 24000.0, "A380": 25900.0, ...}
        """
        logger.info(f"=== SMM 抓取开始 (target_date={target_date}) ===")
        results = asyncio.run(_fetch_smm_raw(target_date))
        if not results:
            self._raise(FetchError("SMM 抓取失败：未拿到任何品种价格（登录态可能失效）"))
        logger.info(f"=== SMM 抓取完成: {len(results)}/7 品种 ===")
        return results


# ============================================================
# 命令行入口：python -m jinggong_monitor.fetcher_smm
# 用途：手动测试 + 刷新 cookies
# ============================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    fetcher = SmmFetcher()
    data = fetcher.fetch()
    print("\n=== 抓取结果 ===")
    for k, v in data.items():
        print(f"  {k}: {v}")
