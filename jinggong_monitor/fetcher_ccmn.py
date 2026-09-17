"""长江有色金属网数据抓取器

数据源: ccmn.cn（长江流域有色金属现货基准价）
方式: AJAX 接口（POST /shop/historyData/getCorpStmarketPriceList）

覆盖品种：A00铝、铜、铅、锌、锡、镍、镁、锰、硅（441/3303/331/553/2202）、铝合金系列
         另供曼德看板：1#白银（元/千克）、磷铜合金（元/吨）
"""

import logging
from datetime import datetime
from typing import Optional

import requests

from jinggong_monitor.base import BaseFetcher

logger = logging.getLogger("jinggong.fetcher.ccmn")

# 长江现货市场 ID（Vmid 写死，ccmn 不变）
_CHANGJIANG_MARKET_VMID = "40288092327140f601327141c0560001"

# 品种名 → 标准 ID 映射（cmmn 中文名 → 项目标准 ID）
# 注：6/25 验证 ccmn 实际返回的品种名按表头如下映射
# 2026-06-26 主人拍板 — 金属硅中间价取值规则：
#   H 列 441  = 金属硅553#-331# 的 avgPrice
#   L 列 331  = 金属硅553#-331# 的 maxPrice
#   I 列 3303 = 金属硅3303#-2202# 的 minPrice
_NAME_MAP = {
    "A00铝": "A00_AL",                    # Col6 长江现货A00铝
    "1#铜": "CU",                          # Col7 长江现货铜
    "金属硅553#-331#": ["SI_553_331_AVG", "SI_553_331_MAX"],  # Col8/Col12（avg + max）
    "金属硅3303#-2202#": ["SI_3303_2202_MIN"],                # Col9（min）
    "1#镁": "MG",                          # Col10 长江现货镁
    "1#电解锰": "MN",                      # Col11 长江现货电解锰
    # 2026-09-17 曼德热系统看板新增（精工主流程 CCMN_KEYS 白名单不含此两项，互不影响）
    "1#白银": "AG",                        # 长江现货白银，单位 元/千克（非元/吨）
    "磷铜合金": "PCU",                     # 长江现货磷铜合金，单位 元/吨
    # 铝合金系列（ccmn 也覆盖，可用但 Excel 表头没要求）
    "铝合金ADC12": "ADC12_CCMN",
    "铸造铝合金锭(A356.2)": "A356_CCMN",
    "铸造铝合金锭(A380）": "A380_CCMN",
}

_AJAX_URL = "https://www.ccmn.cn/shop/historyData/getCorpStmarketPriceList"
_PAGE_URL = "https://www.ccmn.cn/cjxh.shtml"


class CcmnFetcher(BaseFetcher):
    """长江有色金属网价格抓取（AJAX 端点）

    关键发现（6/25）：
    - 直接 GET 主页或 hq.ccmn.cn 拿不到价格表（JS 渲染）
    - AJAX 端点 POST /shop/historyData/getCorpStmarketPriceList 一次拿全
    - 需要参数：marketVmid（长江现货）+ publishDate（YYYY-MM-DD）
    - 返回 36 个品种价格，含目标 6 项
    """

    source_name = "ccmn"
    varieties = ["A00_AL", "CU", "SI_553_331_AVG", "SI_553_331_MAX", "SI_3303_2202_MIN", "MG", "MN"]

    def __init__(self):
        super().__init__()
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": _PAGE_URL,
            "Origin": "https://www.ccmn.cn",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        })
        # 先访问主页拿 session cookie
        try:
            self._session.get(_PAGE_URL, timeout=15)
        except Exception as e:
            logger.warning("ccmn 主页访问失败（仅影响 cookie，可能仍能调 AJAX）: %s", e)

    def fetch(self, target_date: Optional[str] = None) -> dict[str, float]:
        """从长江有色 AJAX 端点拉取价格

        Args:
            target_date: YYYY-MM-DD，None 为今日

        Returns:
            {品种标准ID: 均价}  eg. {"A00_AL": 22850.0, "CU": 101180.0}

        ⚠️ 重要（2026-09-17 实测）：本端点的 `publishDate` 参数**不生效**，
           它**恒返回最新一日**的数据。证据：请求 2026-01-05 与未来日期
           2027-06-30，响应体与当日请求**字节级完全相同**（md5 一致），
           体内 `publishDate` 恒为今日。
           故本方法**不能**用于历史回填；需要历史请用会员接口
           `POST /metalquote/query`（见下方 _history_guard 说明）。
        """
        requested = target_date
        if target_date is None:
            target_date = datetime.now().strftime("%Y-%m-%d")

        results = {}

        # 调 AJAX 端点
        try:
            resp = self._session.post(
                _AJAX_URL,
                data={
                    "marketVmid": _CHANGJIANG_MARKET_VMID,
                    "publishDate": target_date,
                    "flag": "1",
                    "productVmid": "",
                },
                timeout=20,
            )
        except Exception as e:
            self._raise(f"ccmn AJAX 请求失败: {e}")
            return results

        if resp.status_code != 200:
            self._raise(f"ccmn AJAX 返回 {resp.status_code}")
            return results

        try:
            data = resp.json()
        except Exception as e:
            self._raise(f"ccmn AJAX 返回非 JSON: {e}")
            return results

        if not data.get("success"):
            self._raise(f"ccmn AJAX 业务失败: {data.get('msg')}")
            return results

        price_list = data.get("body", {}).get("priceList", [])
        logger.info("ccmn %s 长江现货返回 %d 个品种", target_date, len(price_list))

        # 防御：显式请求历史日期时校验实际数据日，避免静默产出「假历史」。
        # 仅当调用方明确传入非今日的日期才校验 —— 今日请求在早间可能拿到前一日
        # 已发布数据（源未更新），那属正常，不应误报。
        today = datetime.now().strftime("%Y-%m-%d")
        if requested and requested != today:
            actual = price_list[0].get("publishDate") if price_list else None
            if actual != requested:
                self._raise(
                    f"ccmn 端点的 publishDate 参数不生效：请求 {requested}，"
                    f"实际返回 {actual}。该端点只提供最新一日，无法用于历史回填。"
                    f"历史数据需走会员接口 /metalquote/query（返回 isLogin=false 即未登录）。"
                )
                return {}

        # 按品种名映射
        for item in price_list:
            name = item.get("productSortName", "")
            avg = item.get("avgPrice", 0)
            min_p = item.get("minPrice", 0)
            max_p = item.get("maxPrice", 0)
            if not name or not avg:
                continue
            if name in _NAME_MAP:
                targets = _NAME_MAP[name]
                # 兼容 list/str 两种（不同品种映射不同字段）
                if not isinstance(targets, list):
                    targets = [(targets, "avg")]
                else:
                    # 默认 list 里所有 ID 都取 avg（老规则）；金属硅中间价特殊处理
                    if name == "金属硅553#-331#":
                        targets = [
                            ("SI_553_331_AVG", "avg"),
                            ("SI_553_331_MAX", "max"),
                        ]
                    elif name == "金属硅3303#-2202#":
                        targets = [("SI_3303_2202_MIN", "min")]
                    else:
                        targets = [(t, "avg") for t in targets]
                for variety_id, field in targets:
                    val = {"avg": avg, "min": min_p, "max": max_p}[field]
                    if val:
                        results[variety_id] = round(float(val), 2)

        self._after_fetch(len(results) > 0)
        if not results:
            self._raise(f"ccmn {target_date} 未匹配到任何目标品种")
        return results

    def health_check(self) -> bool:
        """快速健康检查（调一次今日的 AJAX）"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            resp = self._session.post(
                _AJAX_URL,
                data={
                    "marketVmid": _CHANGJIANG_MARKET_VMID,
                    "publishDate": today,
                    "flag": "1",
                    "productVmid": "",
                },
                timeout=10,
            )
            return resp.status_code == 200 and resp.json().get("success", False)
        except Exception:
            return False
