"""LME 铝价格抓取器

数据源：metalmarket.cash 公开 API（无需认证）
- 端点：https://metalmarket-api-896235965740.europe-west1.run.app/api/v1/prices/aluminum
- 数据来源标注：metals.dev（LME 聚合价，非 LME 官方 Cash Ask 结算价）
- 单位：USD/tonne（美元/吨）
- 更新频率：近似实时（实际观测有数天延迟可能）
- 无需登录/cookie/Playwright

备注：LME 官方页面 (lme.com) 有 Cloudflare JS Challenge 拦截，
纯 HTTP 请求无法通过。本模块使用第三方免费 API 作为数据源，
价格与 LME 官方 Cash Ask 接近（偏差通常 <2%），适合趋势观察。
如需精确官方结算价，需改用 Playwright 渲染 lme.com 页面。
"""

import logging
from typing import Optional
from datetime import datetime, timezone

import requests

from jinggong_monitor.base import BaseFetcher, FetchError

logger = logging.getLogger("jinggong.fetcher.lme")

# metalmarket.cash 公开 API（Google Cloud Run 后端）
LME_API_URL = "https://metalmarket-api-896235965740.europe-west1.run.app/api/v1/prices/aluminum"

# 请求头（模拟浏览器）
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


class LmeFetcher(BaseFetcher):
    """LME 铝价格抓取器（通过 metalmarket.cash 免费API）"""

    source_name = "lme"
    varieties = ["LME_AL"]

    def fetch(self, target_date: Optional[str] = None) -> dict:
        try:
            resp = requests.get(LME_API_URL, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            self._after_fetch(False)
            self._raise(f"API 请求失败: {e}", recoverable=True)

        # 解析响应
        # 预期格式：{"id":"aluminum","symbol":"AL","price":3279.37,"unit":"USD/t",...}
        price = data.get("price")
        if not price or not isinstance(price, (int, float)) or price <= 0:
            self._after_fetch(False)
            self._raise(f"返回数据异常: {data!r}", recoverable=True)

        price_val = round(float(price), 2)
        ts = data.get("timestamp", "")
        logger.info("LME_AL = %.2f USD/t (source=metals.dev, ts=%s)", price_val, ts)

        self._after_fetch(True)
        return {"LME_AL": price_val}

    def health_check(self) -> bool:
        try:
            resp = requests.get(LME_API_URL, headers=_HEADERS, timeout=15)
            return resp.status_code == 200 and "aluminum" in resp.text
        except Exception:
            return False


def fetch_lme() -> dict:
    """便捷函数：抓取 LME 铝价格（USD/吨）"""
    print("  LME（铝）...", end="", flush=True)
    try:
        fetcher = LmeFetcher()
        res = fetcher.fetch()
        if res and "LME_AL" in res:
            print(f" {res['LME_AL']} USD/t")
            return res
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
