"""采集调度器 v2

关键改进：
1. akshare 现货 API 统一提供 AL/CU/SS/HC/NI/I/J 品种
2. 代理品种映射：HC→钢板/A00_AL+加工费→ADC12/NI→镍生铁
3. HTML 爬虫作为补充（非主力）
"""

import logging
from datetime import date, datetime
from typing import Optional

from jinggong_monitor import get_varieties, get_sources
from jinggong_monitor.base import FetchError
from jinggong_monitor.fetcher_akshare import AkshareFetcher
from jinggong_monitor.fetcher_zgw import ZgwFetcher
from jinggong_monitor.fetcher_tungsten import ChinatungstenFetcher
from jinggong_monitor.fetcher_ccmn import CcmnFetcher
from jinggong_monitor.fetcher_playwright import PlaywrightFetcher
from jinggong_monitor.fetcher_asianmetal import AsianmetalFetcher
from jinggong_monitor.fetcher_smm import SmmFetcher

logger = logging.getLogger("jinggong.orchestrator")

_SOURCE_REGISTRY = {
    "akshare":    AkshareFetcher,
    "akshare_wti": AkshareFetcher,    # 现在统一到 AkshareFetcher
    "akshare_ine": AkshareFetcher,
    "zgw":        ZgwFetcher,
    "bxg":        PlaywrightFetcher,   # 🆕 Playwright 替代 CDP
    "smm":        SmmFetcher,           # Cookie + Playwright 独立实例
    "cnfeol":     PlaywrightFetcher,   # 🆕 Playwright 替代 requests/BS4
    "asianmetal":  AsianmetalFetcher,  # 亚洲金属网 CDP 抓取
    "100ppi":     None,               # 生意社暂未实现独立fetcher
    "mysteel":    None,               # 我的钢铁暂未实现
}

# 代理品种映射：用先导品种估算目标品种
_PROXY_MAPPING = {
    "HC":    ["AXB", "DXB", "LZB"],   # 热卷 → 钢板3类
    "NI":    ["NPI"],                   # 沪镍 → 镍生铁
    "A00_AL": ["ADC12"],               # A00铝 → ADC12（加加工费）
    "INE_SC": ["WTI"],                 # INE原油 → WTI（汇率换算）
    "SS304": ["SS409", "SS439", "SS441"],  # 🆕 304 → 铁素体不锈钢
}


class PriceCollector:
    """统一价格采集器"""

    def __init__(self):
        self.varieties = get_varieties()
        self.sources_cfg = get_sources()
        self._fetchers: dict[str, object] = {}
        self._raw_results: dict[str, dict[str, float]] = {}
        self._final_prices: dict[str, float] = {}
        self._failures: list[tuple[str, str]] = []

    def _get_fetcher(self, source_name: str):
        """懒加载 Fetcher 实例（相同数据源只在第一次实例化）"""
        if source_name not in self._fetchers:
            cls = _SOURCE_REGISTRY.get(source_name)
            if cls is None:
                return None
            # akshare 系列的源共用同一个实例
            if source_name in ("akshare", "akshare_wti", "akshare_ine"):
                if "akshare" not in self._fetchers:
                    self._fetchers["akshare"] = AkshareFetcher()
                return self._fetchers["akshare"]
            # Playwright 系列共用（bxg/cnfeol都用Playwright，smm 独立）
            if source_name in ("bxg", "cnfeol"):
                if "playwright" not in self._fetchers:
                    self._fetchers["playwright"] = PlaywrightFetcher()
                return self._fetchers["playwright"]
            self._fetchers[source_name] = cls()
        return self._fetchers[source_name]

    def collect_all(self, target_date: Optional[str] = None) -> dict[str, float]:
        """采集全部 16 品种价格

        流程：
        1. 收集所有需要的唯一数据源
        2. 逐个拉取，合并结果
        3. 代理品种映射（HC→钢板/NI→镍生铁等）
        4. 多源择优合并
        """
        # Step 1: 收集唯一数据源
        needed_sources: set[str] = set()
        for var in self.varieties:
            for src_key in ("primary", "fallback", "fallback2", "proxy"):
                src_name = var.get("sources", {}).get(src_key)
                if src_name:
                    needed_sources.add(src_name)

        # Step 2: 拉取数据（去重：同一fetcher实例只调一次）
        fetched_instances: set[int] = set()
        for source_name in needed_sources:
            fetcher = self._get_fetcher(source_name)
            if fetcher is None:
                logger.debug("跳过未实现的数据源: %s", source_name)
                continue

            # 已调用过的 fetcher 实例不重复拉取
            fetcher_id = id(fetcher)
            if fetcher_id in fetched_instances:
                logger.debug("跳过重复源: %s (共用实例)", source_name)
                continue
            fetched_instances.add(fetcher_id)

            try:
                prices = fetcher.fetch(target_date)
                self._raw_results[source_name] = prices
                # 共用实例：结果同时注入到所有使用该实例的数据源名下
                for sn in needed_sources:
                    if sn != source_name and self._get_fetcher(sn) is fetcher:
                        self._raw_results[sn] = prices
                if prices:
                    logger.info("✅ %s: %d 品种", source_name, len(prices))
                else:
                    logger.warning("⚠️ %s: 空结果", source_name)
            except FetchError as e:
                self._failures.append((source_name, str(e)))
                logger.warning("❌ %s: %s", source_name, e.detail)
            except Exception as e:
                self._failures.append((source_name, str(e)))
                logger.error("💥 %s: %s", source_name, e)

        # Step 3: 代理品种映射
        self._apply_proxy_mapping()

        # Step 4: 合并结果（多源择优）
        for var in self.varieties:
            vid = var["id"]
            sources = var.get("sources", {})
            price = self._merge_price(vid, sources)
            if price is not None and price > 0:
                self._final_prices[vid] = round(float(price), 2)

        logger.info(
            "采集完成: %d/%d | 失败源: %d",
            len(self._final_prices), len(self.varieties), len(self._failures),
        )
        return self._final_prices

    def _apply_proxy_mapping(self):
        """将先导品种数据映射为代理品种数据

        HC → AXB/DXB/LZB, NI → NPI, A00_AL → ADC12, INE_SC → WTI
        """
        for proxy_vid, target_vids in _PROXY_MAPPING.items():
            proxy_price = None
            # 在 all raw results 中查找代理品种价格
            for src_data in self._raw_results.values():
                if proxy_vid in src_data and src_data[proxy_vid] > 0:
                    proxy_price = src_data[proxy_vid]
                    break

            if proxy_price is None:
                continue

            # 将代理价格注入到对应数据源的结果中
            for target_vid in target_vids:
                # 热卷 → 钢板（加加工费）
                if proxy_vid == "HC":
                    spreads = {"AXB": 1600, "DXB": 3500, "LZB": 2600}
                    spread = spreads.get(target_vid, 2000)
                    mapped_price = proxy_price + spread

                # 沪镍 → 镍生铁
                elif proxy_vid == "NI" and target_vid == "NPI":
                    # 沪镍约 130,000 元/吨 ≈ 1300 元/镍点 × 100
                    # 镍生铁报价在 1000 元/镍点左右
                    # 简单比例映射：镍生铁 ≈ 沪镍/100 × 0.8
                    mapped_price = (proxy_price / 100) * 0.8

                # A00铝 → ADC12
                elif proxy_vid == "A00_AL" and target_vid == "ADC12":
                    # ADC12 = A00铝 + 加工费(约1500)
                    mapped_price = proxy_price + 1500

                # INE SC0 → WTI
                elif proxy_vid == "INE_SC" and target_vid == "WTI":
                    mapped_price = proxy_price / 7.2

                # 🆕 SS304 → 409/439/441 铁素体不锈钢
                elif proxy_vid == "SS304":
                    # 409/439/441 是铁素体不锈钢，价格约为 304 奥氏体不锈钢的 50-70%
                    spreads_ss = {"SS409": 0.50, "SS439": 0.60, "SS441": 0.68}
                    ratio = spreads_ss.get(target_vid, 0.60)
                    mapped_price = proxy_price * ratio

                else:
                    continue

                # 注入到对应主源的原始结果中
                for var in self.varieties:
                    if var["id"] == target_vid:
                        primary_src = var.get("sources", {}).get("primary", "")
                        if primary_src:
                            self._raw_results.setdefault(primary_src, {})[target_vid] = round(mapped_price, 2)
                            logger.info(
                                "🔗 代理映射: %s → %s (%.2f → %.2f)",
                                proxy_vid, target_vid, proxy_price, mapped_price,
                            )
                        break

    def _merge_price(self, variety_id: str, sources: dict) -> Optional[float]:
        """按优先级合并多源价格"""
        for src_key in ("primary", "fallback", "fallback2", "proxy"):
            src_name = sources.get(src_key)
            if not src_name:
                continue
            raw = self._raw_results.get(src_name, {})
            price = raw.get(variety_id)
            if price is not None and float(price) > 0:
                return round(float(price), 2)
        return None

    def get_failures(self) -> list[tuple[str, str]]:
        return self._failures

    def get_raw_results(self) -> dict:
        return self._raw_results
