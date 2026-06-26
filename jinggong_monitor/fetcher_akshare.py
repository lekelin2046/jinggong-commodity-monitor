"""akshare 数据抓取器（现货+期货双轨）

核心策略：
1. futures_spot_price: 一个API获取 AL/CU/SS/HC/NI/I/J 等品种的现货基准价 + 期货主力价
2. futures_main_sina: 补充期货主连日线（备源+历史数据）
3. futures_foreign_commodity_realtime: WTI 原油实时价
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from jinggong_monitor.base import BaseFetcher, FetchError

logger = logging.getLogger("jinggong.fetcher.akshare")

# ============================================================
# 品种映射表
# ============================================================

# futures_spot_price 的 symbol → 我们的品种ID
_SPOT_SYMBOL_MAP = {
    "AL":  "A00_AL",     # A00铝 现货基准价
    "CU":  "CU",         # 电解铜
    "HC":  "HC",         # 热卷（钢板先导）
    "RB":  "RB",         # 螺纹钢
    "SS":  "SS304",      # 304不锈钢
    "NI":  "NI",         # 沪镍（镍生铁先导）
    "I":   "I",          # 铁矿石
    "J":   "J",          # 焦炭
    "SC":  "INE_SC",     # INE原油
}

# futures_main_sina 的期货代码 → 品种ID（备源）
_SINA_FUTURES_MAP = {
    "J0":   "J",         # 焦炭
    "I0":   "I",         # 铁矿石
    "CU0":  "CU",        # 沪铜
    "SS0":  "SS304",     # 304不锈钢
    "NI0":  "NI",        # 沪镍
    "HC0":  "HC",        # 热卷
    "SC0":  "INE_SC",    # INE 原油
    "AL0":  "A00_AL",    # 沪铝（备源）
    "RB0":  "RB",        # 螺纹钢
}

# 覆盖的品种（此 fetcher 声称覆盖的）
COVERED_VARIETIES = [
    "J", "I", "CU", "SS304", "A00_AL",
    "HC", "NI", "INE_SC", "WTI", "RB",
]


class AkshareFetcher(BaseFetcher):
    """akshare 综合抓取器 —— 现货基准价 + 期货 + WTI"""

    source_name = "akshare"
    varieties = COVERED_VARIETIES

    def __init__(self):
        super().__init__()
        self._ak = None

    def _load_ak(self):
        if self._ak is None:
            import akshare as ak
            self._ak = ak
        return self._ak

    def fetch(self, target_date: Optional[str] = None) -> dict[str, float]:
        """三级拉取：现货基准价 → 期货主连 → WTI"""
        results = {}

        today = target_date or date.today().strftime("%Y-%m-%d")
        td_fmt = today.replace("-", "")

        # ========== 第1级: 现货基准价（最权威） ==========
        try:
            spot_vars = list(_SPOT_SYMBOL_MAP.keys())
            df_spot = self._load_ak().futures_spot_price(date=td_fmt, vars_list=spot_vars)
            if df_spot is not None and not df_spot.empty:
                for _, row in df_spot.iterrows():
                    symbol = row.get("symbol", "")
                    spot_price = row.get("spot_price")
                    if symbol in _SPOT_SYMBOL_MAP and spot_price and float(spot_price) > 0:
                        vid = _SPOT_SYMBOL_MAP[symbol]
                        results[vid] = round(float(spot_price), 2)
                logger.info("现货基准价: %d 品种", len(results))
        except Exception as e:
            logger.warning("futures_spot_price 失败: %s", e)

        # ========== 第2级: 期货主连（补充现货未覆盖的品种） ==========
        yesterday = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
        for code, vid in _SINA_FUTURES_MAP.items():
            if vid in results and results[vid] > 0:
                continue  # 现货已覆盖，跳过

            try:
                df = self._load_ak().futures_main_sina(
                    symbol=code,
                    start_date=yesterday,
                    end_date=td_fmt,
                )
                if df is not None and not df.empty:
                    close = float(df.iloc[-1].get("收盘价", df.iloc[-1].get("close", 0)))
                    if close > 0:
                        results[vid] = round(close, 2)
            except Exception as e:
                logger.debug("期货 %s (%s) 失败: %s", vid, code, e)

        # ========== 第3级: WTI 原油 ==========
        try:
            df_wti = self._load_ak().futures_foreign_commodity_realtime(symbol="CL")
            if df_wti is not None and not df_wti.empty:
                price = float(df_wti.iloc[0].get("最新价", 0))
                if price > 0:
                    results["WTI"] = round(price, 2)
        except Exception as e:
            logger.warning("WTI 原油失败: %s", e)

        # ========== 日志 ==========
        self._after_fetch(len(results) > 0)
        if not results:
            self._raise("akshare 所有品种拉取失败")

        for vid, price in results.items():
            logger.debug("akshare %s = %.2f", vid, price)

        return results

    def health_check(self) -> bool:
        """快速健康检查"""
        try:
            ak = self._load_ak()
            df = ak.futures_spot_price(date="20260624", vars_list=["CU"])
            return df is not None and not df.empty
        except Exception:
            return False
