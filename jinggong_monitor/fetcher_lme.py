"""LME 铝价格抓取器 —— LME 官网官方 Cash Ask 口径

数据源：LME 官网官方「Official prices」数据接口
- API: https://www.lme.com/api/trading-data/day-delayed?datasourceId=5ec6a4fc-6bd2-4fb0-b7f5-6ac0f3e68d1d
- 口径: Cash Ask（官方现货卖出价，USD/t）= 页面表格 Cash 列 Ask = Values[1]
- 发布节奏: 伦敦每个交易日收市后公布（约北京 20:25 后更新）；北京 15:00 抓取时
  DateOfData 为前一伦敦交易日（日延一日口径），写入当天行，看板有注说明。
- 取值规则: 官方值缺失（'-'）或接口不可得 → 抛 FetchError，当日留空（守铁律不编造）。

技术路线（2026-09-10 实验验证，见 probe_lme_official.py）：
  lme.com API 有 Cloudflare 指纹校验：requests 403、Playwright ctx.request 403、
  无 cf_clearance cookie 可导出。唯一可行 = headed Chrome（持久化 profile）
  打开页面过 CF 后【页面内 fetch()】调用 API，会话内稳定成功。
  注意：运行前需 unset NODE_OPTIONS（Playwright driver 兼容性，与其它 Playwright 源一致）。

历史: 2026-09-08~09-10 前版本用 metalmarket.cash 聚合 API（metals.dev 源），
实测其内部 ts 冻结（09-10 时数据停在 09-02、滞后 7 天），已弃用。
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

from jinggong_monitor.base import BaseFetcher, FetchError

logger = logging.getLogger("jinggong.fetcher.lme")

PROJECT = Path(__file__).resolve().parent.parent
PROFILE_DIR = PROJECT / "cookies" / "lme_official_profile"

PAGE_URL = "https://www.lme.com/en/Metals/Non-ferrous/LME-Aluminium"
API_URL = ("https://www.lme.com/api/trading-data/day-delayed"
           "?datasourceId=5ec6a4fc-6bd2-4fb0-b7f5-6ac0f3e68d1d")

CF_WAIT_S = 90        # 单次尝试内等待 CF 挑战通过的最长时间
ATTEMPTS = 3          # CF 偶发拦截，多试几次
RETRY_GAP_S = 10
RENDER_WAIT_S = 3     # 过盾后稍等再 fetch


def _is_cf_page(page) -> bool:
    try:
        return "just a moment" in (page.title() or "").lower()
    except Exception:
        return True


class LmeFetcher(BaseFetcher):
    """LME 铝官方价抓取器（lme.com 官方 Cash Ask，headed Playwright）"""

    source_name = "lme"
    varieties = ["LME_AL"]

    def __init__(self, attempts: int = ATTEMPTS):
        super().__init__()
        self._attempts = attempts

    def fetch(self, target_date: Optional[str] = None) -> dict:
        """返回 {"LME_AL": Cash Ask, "_date_of_data": 官方数据日}"""
        # 铁律：定时任务跑 Playwright 前必须清掉 NODE_OPTIONS，否则 driver 连接失败
        import os
        os.environ.pop("NODE_OPTIONS", None)
        # 延迟 import：playwright 较重，且避免模块加载顺序影响其它 fetcher
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            self._after_fetch(False)
            self._raise(f"playwright 未安装: {e}", recoverable=True)

        last_err = ""
        for i in range(1, self._attempts + 1):
            doc = None
            try:
                with sync_playwright() as pw:
                    doc = self._one_attempt(pw)
            except Exception as e:
                last_err = f"第{i}次异常: {e}"
                logger.warning("LME %s", last_err)
            if doc:
                return doc
            if i < self._attempts:
                logger.info("LME 第%d次未成功(%s)，%ds 后重试", i, last_err, RETRY_GAP_S)
                time.sleep(RETRY_GAP_S)

        self._after_fetch(False)
        self._raise(f"{self._attempts}次尝试均未成功（CF拦截/接口不可得），最后错误: {last_err}",
                    recoverable=True)

    def _one_attempt(self, pw) -> Optional[dict]:
        """单次尝试：headed 过 CF → 页面内 fetch → 解析。成功返回带 LME_AL 的 dict"""
        PROFILE_DIR.parent.mkdir(exist_ok=True)
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,            # headless 会被 CF 拦截，必须 headed
            channel="chrome",
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(PAGE_URL, timeout=60000, wait_until="domcontentloaded")
            deadline = time.time() + CF_WAIT_S
            while time.time() < deadline and _is_cf_page(page):
                time.sleep(3)
            if _is_cf_page(page):
                logger.warning("LME Cloudflare 未通过（本回合）")
                return None

            time.sleep(RENDER_WAIT_S)
            res = page.evaluate(
                """async (url) => {
                    const r = await fetch(url, {credentials: 'include',
                        headers: {'Accept': 'application/json'}});
                    return {status: r.status, body: await r.text()};
                }""", API_URL)
            if res["status"] != 200:
                logger.warning("LME 页面内 fetch status=%s", res["status"])
                return None

            doc = json.loads(res["body"])
            date_of_data = str(doc.get("DateOfData", ""))[:10]
            row = next((r for r in doc.get("Rows", [])
                        if r.get("RowTitle") == "Aluminium"), None)
            if not row:
                logger.warning("LME 响应无 Aluminium 行")
                return None
            vals = row.get("Values") or []
            cash_ask = vals[1] if len(vals) > 1 else "-"
            if not cash_ask or cash_ask == "-":
                # 官方未公布（如假日），守铁律不填
                logger.warning("LME Aluminium Cash Ask 缺失('-'), DateOfData=%s", date_of_data)
                return None

            price = round(float(cash_ask), 2)
            logger.info("LME_AL = %.2f USD/t (LME官网官方 Cash Ask, DateOfData=%s)",
                        price, date_of_data)
            self._after_fetch(True)
            return {"LME_AL": price, "_date_of_data": date_of_data}
        finally:
            ctx.close()

    def health_check(self) -> bool:
        return self._last_success


def fetch_lme() -> dict:
    """便捷函数：抓取 LME 官方铝价（Cash Ask，USD/吨），写入当天行"""
    print("  LME（铝, 官网官方 Cash Ask）...", end="", flush=True)
    try:
        fetcher = LmeFetcher()
        res = fetcher.fetch()
        if res and "LME_AL" in res:
            dod = res.get("_date_of_data", "?")
            print(f" {res['LME_AL']} USD/t (官方价数据日={dod})")
            return {"LME_AL": res["LME_AL"]}
        print(" 未获取")
        return {}
    except FetchError as e:
        print(f" 失败: {e.detail}")
        return {}
    except Exception as e:
        print(f" 异常: {e}")
        import traceback
        traceback.print_exc()
        return {}
