"""SMM 上海有色网数据抓取器（SSR + Cookies 复用模式）

核心思路：
1. 优先用已存的 cookies 访问 hq.smm.cn/aluminum 和 /magnesium 两个聚合页
2. SMM 价格是 SSR 渲染在 HTML 里的，直接正则提取，无需调 API、无需访问品种详情页
3. cookies 失效时才重新登录（登录一次约 8s，cookies 有效期约 7 天）

数据来源: hq.smm.cn
目标品种: ADC12, A380, AlSi9Cu3, A356, AM60B, AZ91D, 闻喜镁锭
         另供曼德看板: SMM A00铝（AL_A00）、AlSi12(Fe)铝合金（AL_ALSI12FE）

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
    # —— 铝（2026-09-17 新增 A00 / ZLD104，供塑料看板「铝」分组使用）——
    "A00": {
        "page": "aluminum",
        # 页面形如「SMM A00铝 \t24170~24190\t24180」；须锚定 "SMM " 前缀，
        # 否则会误命中「SMM A00铝(中原)/(佛山)」等地区行与「A00铝升贴水」行
        "pattern": r"SMM A00铝\s+(\d{4,6})~(\d{4,6})\s+(\d{4,6})",
    },
    "ZLD104": {
        "page": "aluminum",
        # ⚠️ 页面同时存在「ZLD104铝合金」与「低碳ZLD104铝合金」两行，
        # 不加负向断言时后者也满足匹配（值不同：24350 vs 24300）
        "pattern": r"(?<!低碳)ZLD104铝合金\s+(\d{4,6})~(\d{4,6})\s+(\d{4,6})",
    },
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
        # 页面另有「低碳AlSi9Cu3铝合金锭」「国标AlSi9Cu3铝合金锭」等变体行，负向断言排除
        "pattern": r"(?<!低碳)AlSi9Cu3铝合金\s+(\d{4,6})~(\d{4,6})\s+(\d{4,6})",
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
    # 2026-09-17 曼德热系统看板新增（同在 aluminum 页；精工主流程按 COL_MAP 取值，多余 key 自动忽略）
    # ⚠️ 同段另有裸 "AlSi12" / "AlSi20" / "AlSi50"（铝合金锭系列，价格不同），
    #    故 AL_ALSI12FE 必须精确锚定 "AlSi12(Fe)铝合金" 并容忍全/半角括号，否则误抓。
    "AL_A00": {
        "page": "aluminum",
        "pattern": r"SMM A00铝\s+(\d{4,6})~(\d{4,6})\s+(\d{4,6})",
    },
    "AL_ALSI12FE": {
        "page": "aluminum",
        "pattern": r"AlSi12[（(]Fe[)）]铝合金\s+(\d{4,6})~(\d{4,6})\s+(\d{4,6})",
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
        await asyncio.sleep(2)
        # 2026-08 登录页新增"请阅读并同意"弹窗，需点击"同意并登录"才真正提交
        try:
            agree_btn = page.locator("button:has-text('同意并登录')")
            if await agree_btn.count() > 0:
                await agree_btn.first.click()
                logger.info("点击了'同意并登录'")
        except Exception:
            pass
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


# 价格表格特征：形如「24300~24400」的低~高价区间。
# 用作"页面是否已渲染出价格"的兜底判据（当某页没有配置品种正则时）。
_PRICE_TABLE_RE = re.compile(r"\d{4,6}~\d{4,6}")

# 页面就绪判据（2026-09-17 加固）：按「该页所辖品种自身的正则」判断 SSR 是否已就绪。
# 比通用「数字~数字」更精确——如 alloy_chart 页的 ADC12 日本 CIF 用「3090-3110 3100」
# 连字符格式，通用区间判据在该页永不命中，会造成无谓轮询。
_PAGE_READY_RE: dict = {}
for _cfg in SMM_VARIETIES.values():
    _PAGE_READY_RE.setdefault(_cfg["page"], []).append(re.compile(_cfg["pattern"]))


async def _fetch_page_text(ctx, page_url: str, page_name: Optional[str] = None,
                           wait_ms: int = 9000, poll_ms: int = 3000,
                           max_poll: int = 8) -> str:
    """用 cookies 访问页面，返回 body innerText

    Args:
        page_name: 页面标识（aluminum/magnesium/alloy_chart），用于选取就绪判据。
        wait_ms: 首轮等待（等 SSR 基本成型）。
        poll_ms: 轮询间隔；首轮未就绪时按此间隔复查。
        max_poll: 轮询上限次数（总等待约 wait_ms + poll_ms*max_poll）。

    2026-09-17 加固：原实现为「固定 sleep 9s 后读一次」，当日 15:00 铝/镁两页
    均读到无价格表的文本 → 触发内部重登录 → 又被外层 90s 超时掐断 → SMM 12 键
    全空（事后复测页面与 cookies 均正常，属时点性渲染慢）。改为轮询到价格表出现
    即返回：正常情况更快（早退），渲染慢时容忍度更高（不误判为 cookies 失效）。
    """
    def _ready(text: str) -> bool:
        pats = _PAGE_READY_RE.get(page_name or "")
        if pats:
            return any(p.search(text) for p in pats)
        return bool(_PRICE_TABLE_RE.search(text))

    page = await ctx.new_page()
    try:
        await page.goto(page_url, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(wait_ms)  # 等 SSR 渲染
        text = await page.inner_text("body")
        if _ready(text):
            return text
        # 首轮未就绪 → 轮询复查，避免把"渲染慢"误判成"cookies 失效"
        for _ in range(max_poll):
            await page.wait_for_timeout(poll_ms)
            text = await page.inner_text("body")
            if _ready(text):
                logger.info(f"{page_name} 页价格表延迟渲染，轮询后已就绪")
                return text
        logger.warning(f"{page_name} 页轮询 {max_poll} 次后仍未就绪（返回当前文本）")
        return text
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
                    texts[page_name] = await _fetch_page_text(ctx, url, page_name)
                except Exception as e:
                    logger.warning(f"抓 {page_name} 页失败: {e}")
                    texts[page_name] = ""

            # 解析价格
            results = _parse_prices(texts)

            # aluminum 页关键铝合金品种（ADC12/A380/A356/AlSi9Cu3）偶发 SSR 渲染慢，
            # 若缺失则对 aluminum 页单独重试一次（更长等待），避免整日留空
            alum_keys = {"ADC12", "A380", "A356", "AlSi9Cu3"}
            if not alum_keys.issubset(results.keys()) and texts.get("aluminum"):
                logger.warning("铝合金关键品种缺失，重试 aluminum 页(更长等待)...")
                texts["aluminum"] = await _fetch_page_text(ctx, SMM_PAGES["aluminum"], "aluminum", wait_ms=12000)
                results.update(_parse_prices({"aluminum": texts["aluminum"]}))

            # 若一个都没拿到，可能 cookies 过期，重新登录
            if not results:
                logger.warning("未提取到任何价格，cookies 可能过期，重新登录")
                await _login_and_save_cookies(ctx)
                # 重新抓
                for page_name, url in SMM_PAGES.items():
                    try:
                        texts[page_name] = await _fetch_page_text(ctx, url, page_name)
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
        logger.info(f"=== SMM 抓取完成: {len(results)}/{len(SMM_VARIETIES)} 品种 ===")
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
