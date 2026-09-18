"""隆众资讯「价格中心」接口封装（dc.oilchem.net）

背景（2026-09-17 实测）
------------------------------------------------------------------
隆众资讯（oilchem.net）的**文章正文**是付费墙，但它的**结构化价格数据库**
dc.oilchem.net 提供完整 REST 接口，且接口层不拦匿名调用。真正的门槛在
**服务端数据层**：未登录时价格值被替换为占位串，登录态有效则回填真实值。

实测三态（同一接口、只换身份，可作为排障判据）：

| 身份 | 占位串 | pricePowerBO.see | 含义 |
|---|---|---|---|
| 匿名 | `"请登录"` | false | 完全未授权 |
| 已登录·无价格权限 | `"无权限"` | false | 登录有效，但该品种/该列无订阅 |
| 已登录·有价格权限 | 真实数值 | **true** | 正常取数 |

⚠️ 关键：`see` 是**分品种**的，不是账号级开关。实测同一账号下
炭黑/干胶/顺丁/丁苯/防老剂/促进剂/三元乙丙/乙烯/丙烯 = true，
而柴油/原油/高温煤焦油 = false。**不能因一个品种 false 就判定整个账号无效。**
（煤焦油走百川盈孚，免登录；原油走精工现有路径。）

接口要点（踩过的坑）
------------------------------------------------------------------
  · pageSize 上限 **100**，150 即报 "pageSize数值超限"，且**失败时静默无行**
    （易误判为"该品种没数据"）
  · twoLevelBusinessType 必须传**数字** 0（传字符串会报 "未查询到指标"）
  · 不同品种的 businessType 差异很大：原油只有「国际价格(4)」，
    没有「市场价格(3)」——用错类型会得到 "未查询到指标"
  · priceBodyMap 结构有两种：按地区分组 dict（国内价）或 list（国际价）
  · 价格取值：`pick_price(row["YYYY/MM/DD"]["price"])`，按
    **主流价 > 最低价 > 最高价** 优先级（见 PRICE_KEY_ORDER）。
    ⚠️ 勿按 dict 首键取：三键齐全时会取到区间下沿。
  · ⚠️⚠️ **queryPricePage 对「区间型品种」根本不回「主流价」**，只有
    「最低价/最高价」两键 —— 此时 pick_price 会退到**区间下沿**。
    而历史回填补的是 getSingleCurve 的 `middlePrice`（主流价）。
    两侧差约半个区间宽（炭黑 N550 实测 300 元/吨），拼接处会造出假跳变。
    → 故这类品种在 VARIETY_MAP 里标 `"curve_daily": True`，**日常取数也走
    曲线接口**，保证与历史同源同字段。判据见 `verify_daily_vs_curve()`。
    受影响品种（2026-09-18 全量实测确认）：丙烯 / 炭黑N550 / 防老剂4020 /
    促进剂M / 促进剂TMTD。
  · 涨跌方向另在 row["YYYY/MM/DD"]["dataRiseOrFall"]，取值 -1/0/1
  · 行标识：国内价用 internalMarketName + specificationsName + standard；
    国际价用 marketName + specificationsName

登录态获取（两条路，cookie 优先）
------------------------------------------------------------------
  A) **cookie 直连**（默认）：`cookies/lz.json` 里的 `_member_user_tonken_` 等
     直接作为 Cookie 头。实测 11 个品种全部 200 且 see=true，无需启动浏览器。
  B) **Playwright profile 回退**：cookie 失效或风控升级时，用
     `cookies/lz_profile`（由 `lz_login_setup.py` 人工登录一次生成）。

铁律：值等于占位串/空/`-`/`询价中` → 视为**未取到**，返回 None。
      绝不沿用前值、绝不估算。
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("jinggong.lz")

PROJECT = Path(__file__).resolve().parent.parent
COOKIE_FILE = PROJECT / "cookies" / "lz.json"

API_BASE = "https://dc.oilchem.net"
QUERY_PRICE_URL = f"{API_BASE}/ndc/price/list/queryPricePage"
FUZZY_URL = f"{API_BASE}/ndc/common/fuzzyQueryBreeds"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 一切「不是价格」的值 —— 命中即视为未取到（铁律）
INVALID_TOKENS = {"", "-", "--", "请登录", "无权限", "询价中", "暂无", "未报价", "停报"}

# 登录态核心 cookie 名（用于过期检测）
TOKEN_COOKIE = "_member_user_tonken_"

# ---------------------------------------------------------------------------
# 品种映射表：需求 → 隆众品种
# 全部于 2026-09-17 登录态实测确认（see=true 且取到真实价格）
#   vid/bt/tlbt : 品种与价格类型定位
#   specs       : 规格名候选（**精确匹配**，避免 DM/TMTD/M 互相误命中）
#   markets     : 市场/地区优先级（取第一个有值的；None = 不限，取首行）
#   strict      : True = **只在 markets 内取**，取不到即留空，不跨市场兜底
#                 False（默认）= markets 全未命中时退到首个匹配行
#   curve_daily : True = **日常取数走 getSingleCurve 取 middlePrice（主流价）**，
#                 不走 queryPricePage。仅「区间型品种」需要 —— 它们的
#                 queryPricePage 响应里没有「主流价」键，只能取到区间下沿。
#
# strict 的意义：主人指定口径的品种用 True。否则一旦指定市场当日无报价，
# 会静默滑到别的市场，看板上只显示数字、看不出市场已漂移 —— 那比留空更危险。
# 未指定口径的品种保持 False，以免某市场缺报时整体断档。
# ---------------------------------------------------------------------------
VARIETY_MAP: dict[str, dict[str, Any]] = {
    # ---- 化工 ----
    "ETHYLENE": {
        "name": "乙烯", "unit": "元/吨", "vid": 196, "bt": 3, "tlbt": 0,
        "specs": None, "markets": ["华东", "山东"],
    },
    # 主人指定「华北」；隆众丙烯无「华北」市场名，山东系为地理最接近项
    # （隆众的「华北地区」标签只覆盖河北/山西/天津，丙烯在这三地无数据）
    "PROPYLENE": {
        "name": "丙烯", "unit": "元/吨", "vid": 116, "bt": 3, "tlbt": 0,
        "specs": None, "markets": ["山东"], "strict": True,
        "curve_daily": True,
    },
    # ---- 炭黑 ----
    "CARBON_BLACK_N550": {
        "name": "炭黑 N550", "unit": "元/吨", "vid": 242, "bt": 3, "tlbt": 0,
        "specs": ["N550"], "markets": ["山东"], "strict": True,
        "curve_daily": True,
    },
    # ---- 天然橡胶（隆众品种名为「干胶」）----
    # SCRWF = 国产全乳胶，主人指定云南昆明产地口径
    "NR_SCRWF": {
        "name": "天然橡胶 SCRWF", "unit": "元/吨", "vid": 259, "bt": 3, "tlbt": 0,
        "specs": ["SCRWF"], "markets": ["昆明"], "strict": True,
    },
    # RSS3 = 泰国进口烟片胶，无昆明口径，维持原多市场优先级
    "NR_RSS3": {
        "name": "天然橡胶 RSS3", "unit": "元/吨", "vid": 259, "bt": 3, "tlbt": 0,
        "specs": ["RSS3"], "markets": ["上海", "浙江", "山东"],
    },
    # ---- 合成橡胶 ----
    "BR9000": {
        "name": "顺丁橡胶 9000", "unit": "元/吨", "vid": 267, "bt": 3, "tlbt": 0,
        "specs": ["BR9000"], "markets": ["上海", "江苏", "浙江"],
    },
    "SBR1712": {
        "name": "丁苯橡胶 1712", "unit": "元/吨", "vid": 266, "bt": 3, "tlbt": 0,
        "specs": ["1712", "SBR1712"], "markets": ["江苏", "上海", "山东"],
    },
    # ---- 橡胶助剂 ----
    "ANTIOXIDANT_4020": {
        "name": "防老剂 4020", "unit": "元/吨", "vid": 282, "bt": 3, "tlbt": 0,
        "specs": ["4020"], "markets": ["华东", "衡水", "广州"],
        "curve_daily": True,
    },
    # 主人指定促进剂取山东。但山东只有 D/DZ/NS/CZ/DM 五个规格：
    #   · DM / CZ → 山东有，strict 单市场
    #   · M / TMTD → 山东**无此规格**，退到同为华北的衡水（价格与上海/杭州一致）
    "ACCEL_DM": {
        "name": "促进剂 DM", "unit": "元/吨", "vid": 281, "bt": 3, "tlbt": 0,
        "specs": ["DM"], "markets": ["山东"], "strict": True,
    },
    "ACCEL_CZ": {
        "name": "促进剂 CZ", "unit": "元/吨", "vid": 281, "bt": 3, "tlbt": 0,
        "specs": ["CZ"], "markets": ["山东"], "strict": True,
    },
    "ACCEL_M": {
        "name": "促进剂 M", "unit": "元/吨", "vid": 281, "bt": 3, "tlbt": 0,
        "specs": ["M"], "markets": ["衡水"], "strict": True,
        "curve_daily": True,
    },
    "ACCEL_TMTD": {
        "name": "促进剂 TMTD", "unit": "元/吨", "vid": 281, "bt": 3, "tlbt": 0,
        "specs": ["TMTD"], "markets": ["衡水"], "strict": True,
        "curve_daily": True,
    },
    # ---- 三元乙丙橡胶（牌号级）----
    "EPDM_6950C": {
        "name": "三元乙丙 6950C", "unit": "元/吨", "vid": 275, "bt": 3, "tlbt": 0,
        "specs": ["6950C"], "markets": ["上海", "衡水", "广东"],
    },
    "EPDM_3110M": {
        "name": "三元乙丙 3110M", "unit": "元/吨", "vid": 275, "bt": 3, "tlbt": 0,
        "specs": ["3110M"], "markets": ["上海"],
    },
    "EPDM_13561C": {
        "name": "三元乙丙 13561C", "unit": "元/吨", "vid": 275, "bt": 3, "tlbt": 0,
        "specs": ["13561C"], "markets": ["上海"],
    },
    # ---- 以下品种本账号 see=false，仅登记以便将来核对 ----
    # COAL_TAR_HIGH vid=133（高温煤焦油）→ 无权限；改用百川盈孚（免登录）
    # CRUDE_BRENT vid=110 bt=4 tlbt=22/23（布伦特 期货/FOB）→ 无权限；走精工现有路径
    "COAL_TAR_HIGH": {
        "name": "高温煤焦油(本账号无权)", "unit": "元/吨", "vid": 133, "bt": 3, "tlbt": 0,
        "specs": None, "markets": None,
    },
    "CRUDE_BRENT_FUT": {
        "name": "原油·布伦特期货(本账号无权)", "unit": "美元/桶", "vid": 110, "bt": 4, "tlbt": 22,
        "specs": ["布伦特"], "markets": ["英国"],
    },
}


# ---------------------------------------------------------------------------
# 登录态
# ---------------------------------------------------------------------------
def load_cookies(path: Optional[Path] = None) -> list[dict]:
    p = Path(path) if path else COOKIE_FILE
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning("读取 cookie 失败 %s: %s", p, e)
        return []


def cookie_header(path: Optional[Path] = None) -> str:
    """仅取 oilchem.net 域下的 cookie 拼成请求头"""
    ck = load_cookies(path)
    parts = [f"{c['name']}={c['value']}"
             for c in ck
             if "oilchem" in (c.get("domain") or "")]
    return "; ".join(parts)


def token_expiry(path: Optional[Path] = None) -> Optional[float]:
    """返回登录 token 的过期时间戳（秒）；无则 None"""
    for c in load_cookies(path):
        if c.get("name") == TOKEN_COOKIE:
            exp = c.get("expires", -1)
            return float(exp) if exp and exp > 0 else None
    return None


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def _iter_rows(resp: dict) -> list[dict]:
    """priceBodyMap 两种形态统一成 list"""
    bm = resp.get("priceBodyMap")
    if isinstance(bm, list):
        return bm
    if isinstance(bm, dict):
        out = []
        for _region, items in bm.items():
            if isinstance(items, list):
                out.extend(items)
        return out
    return []


def _row_label(row: dict) -> tuple[str, str]:
    """(市场/区域, 规格) —— 兼容国内价与国外价两套字段名"""
    market = row.get("internalMarketName") or row.get("marketName") or ""
    spec = row.get("specificationsName") or row.get("standard") or ""
    return str(market).strip(), str(spec).strip()


def to_number(raw: Any) -> Optional[float]:
    """占位串/空值 → None（铁律）；否则转 float"""
    if raw is None:
        return None
    s = str(raw).strip()
    if s in INVALID_TOKENS:
        return None
    if any(t in s for t in ("请登录", "无权限", "询价中", "暂无")):
        return None
    s2 = re.sub(r"[^\d.]", "", s)
    if not s2 or s2 == ".":
        return None
    try:
        return float(s2)
    except ValueError:
        return None


# 价格字段取值优先级（2026-09-17 实测修正）
#   隆众 price 字典有三种形态：
#     · 只有「主流价」            → 乙烯 / SCRWF / RSS3
#     · 只有「最低价/最高价」      → 丙烯 / 炭黑N550 / 促进剂 / 防老剂
#     · 三键齐全                  → 顺丁 / 丁苯 / 三元乙丙
#   原先按 dict 首键取值，遇到「三键齐全」会取到**区间下沿**而非主流价
#   （顺丁取 15300 而主流价是 15400）。现改为显式优先级：主流价 > 最低价 > 最高价。
#   ⚠️ 「只有最低价/最高价」的那一档，pick_price 只能退到区间下沿 ——
#      这是**降级**而非等价，故这类品种改走曲线接口（curve_daily）。
PRICE_KEY_ORDER = ("主流价", "最低价", "最高价")


def pick_price(price_map: Any) -> Optional[float]:
    """从一个日期的 price 字典里按优先级取值；全无效 → None（铁律）"""
    if not isinstance(price_map, dict) or not price_map:
        return None
    for k in PRICE_KEY_ORDER:
        if k in price_map:
            v = to_number(price_map[k])
            if v is not None:
                return v
    for v in price_map.values():          # 兜底：未知字段名
        n = to_number(v)
        if n is not None:
            return n
    return None


def _spec_ok(spec_cell: str, specs: Optional[list[str]], exact: bool = True) -> bool:
    if not specs:
        return True
    sp = spec_cell.strip().upper()
    for s in specs:
        s = str(s).strip().upper()
        if (sp == s) if exact else (s in sp):
            return True
    return False


def parse_series(resp: dict, specs: Optional[list[str]] = None,
                 markets: Optional[list[str]] = None,
                 exact: bool = True, strict: bool = False) -> tuple[dict[str, Optional[float]], str]:
    """从响应取「日期 → 价格」，返回 (序列, 实际采用的「市场|规格」标签)。

    取值优先级：
      1) markets 里第一个能取到有效值的市场
      2) strict=False 时，若 markets 全未命中，退到首个匹配行（避免整体断档，
         但口径会漂移 —— 故仅对主人未指定口径的品种启用）
         strict=True 时**不兜底**：markets 内取不到就返回全 None（留空），
         并打 WARNING 说明是哪个市场缺报 —— 看板显示「—」比显示错市场的值更安全
    """
    rows = _iter_rows(resp)
    dates = list(resp.get("dateList") or [])

    cand = [r for r in rows if _spec_ok(_row_label(r)[1], specs, exact)]
    if not cand:
        logger.warning("未匹配到行（specs=%r markets=%r，候选 %d 行）",
                       specs, markets, len(rows))
        return {}, ""

    def series_of(row: dict) -> dict[str, Optional[float]]:
        out: dict[str, Optional[float]] = {}
        for d in dates:
            cell = row.get(d)
            if not isinstance(cell, dict):
                out[d] = None
                continue
            pm = cell.get("price") or {}
            out[d] = pick_price(pm)
        return out

    order: list[dict] = []
    if markets:
        for m in markets:
            for r in cand:
                if m in _row_label(r)[0]:
                    order.append(r)
    if not strict:
        order += [r for r in cand if r not in order]

    for r in order:
        s = series_of(r)
        if any(v is not None for v in s.values()):
            mkt, sp = _row_label(r)
            return s, f"{mkt}|{sp}"

    if strict and markets:
        logger.warning("指定市场 %r 无有效报价（候选含 %r）——按铁律留空",
                       markets,
                       sorted({_row_label(r)[0] for r in cand}))
        return {d: None for d in dates}, f"{'/'.join(markets)}|(缺报)"

    mkt, sp = _row_label(cand[0])
    return series_of(cand[0]), f"{mkt}|{sp}"


def is_authorized(resp: dict) -> bool:
    """服务端是否放行价格（pricePowerBO.see）—— 注意是**分品种**的"""
    return bool((resp.get("pricePowerBO") or {}).get("see"))


def auth_state(resp: dict) -> str:
    """返回 'ok' | 'no_power'（登录了但无权限）| 'anonymous'（未取到登录态）"""
    pwb = resp.get("pricePowerBO") or {}
    if pwb.get("see"):
        return "ok"
    # 有 token 时服务端回 "无权限"，无 token 时回 "请登录"
    blob = json.dumps(resp, ensure_ascii=False)
    return "no_power" if "无权限" in blob else "anonymous"


# ---------------------------------------------------------------------------
# 抓取 · cookie 直连（默认路径）
# ---------------------------------------------------------------------------
def fetch_raw_http(vid: int, bt: int, tlbt: int = 0,
                   cookie: Optional[str] = None, page_size: int = 100,
                   timeout: int = 40) -> dict:
    """同步调 queryPricePage。pageSize 实际值会被夹到 100。"""
    payload = {"varietiesId": vid, "businessType": str(bt),
               "twoLevelBusinessType": tlbt, "timeType": 0,
               "pageNum": 1, "pageSize": min(int(page_size), 100)}
    body = json.dumps(payload).encode()
    req = urllib.request.Request(QUERY_PRICE_URL, data=body, method="POST")
    hdrs = {"User-Agent": UA, "Referer": f"{API_BASE}/page/", "Origin": API_BASE,
            "Content-Type": "application/json"}
    if cookie is None:
        cookie = cookie_header()
    if cookie:
        hdrs["Cookie"] = cookie
    for k, v in hdrs.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, data=body, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def fetch_variety_curve_daily(key: str, days: int = 14,
                              cookie: Optional[str] = None) -> dict[str, Any]:
    """日常取数（**曲线口径**）：取最近 `days` 天的曲线，只认 middlePrice。

    与 fetch_variety 返回同结构（含 date/price/series/source/auth/error）。
    用于「区间型品种」—— 日报接口对它们不回主流价，取不到真口径。

    为什么不用日报接口的 low/high 取平均代替：
      实测 middlePrice **不等于** (low+high)/2。例（山东|N550）：
        2026-09-03  low=9000  high=9300  → 中值 9150，middlePrice=9200
        2026-09-17  low=11800 high=12300 → 中值 12050，middlePrice=12000
      middlePrice 是隆众单独维护的主流价，自算中值会造成**新的**口径偏差。
    """
    import datetime as _dt
    cfg = VARIETY_MAP[key]
    out: dict[str, Any] = {"key": key, "name": cfg["name"], "unit": cfg["unit"],
                           "date": None, "price": None, "series": {},
                           "source": "", "auth": "", "error": None}
    end = _dt.date.today()
    start = end - _dt.timedelta(days=int(days))
    r = fetch_variety_curve(key, start.isoformat(), end.isoformat(), cookie=cookie)
    out["error"] = r.get("error")
    out["source"] = r.get("source") or ""
    out["auth"] = r.get("auth") or ""
    out["series"] = r.get("series") or {}
    live = {d: v for d, v in out["series"].items() if v is not None}
    if live:
        d = max(live)
        out["date"] = d
        out["price"] = live[d]
    return out


def fetch_variety(key: str, cookie: Optional[str] = None,
                  sleep: float = 0.6) -> dict[str, Any]:
    """按映射表 key 取价。

    返回 {key, name, unit, date, price, series, source, auth, error, mode}
    —— 取不到时 price=None（绝不编造）。

    mode：`daily`＝日报接口 queryPricePage；`curve`＝曲线接口 getSingleCurve。
    ⚠️ 区间型品种（cfg["curve_daily"]）走 curve，与历史回填同口径；
       曲线取不到时**回退** daily 并打 WARNING（口径会偏低，但好过断档）。
    """
    cfg = VARIETY_MAP.get(key)
    if not cfg:
        raise KeyError(f"未知品种 key: {key}（可选：{', '.join(VARIETY_MAP)}）")
    out: dict[str, Any] = {"key": key, "name": cfg["name"], "unit": cfg["unit"],
                           "date": None, "price": None, "series": {},
                           "source": "", "auth": "", "error": None, "mode": ""}
    if cfg.get("curve_daily"):
        try:
            r = fetch_variety_curve_daily(key, cookie=cookie)
        except Exception as e:                                  # noqa: BLE001
            r = {"error": f"{type(e).__name__}: {e}"}
        if r.get("price") is not None:
            for k in ("date", "price", "series", "source", "auth", "error"):
                out[k] = r.get(k)
            out["mode"] = "curve"
            if sleep:
                time.sleep(sleep)
            return out
        logger.warning("%s 曲线口径取数失败（%s）—— 回退日报接口，"
                       "该值与历史主流价口径不同，可能偏低",
                       cfg["name"], r.get("error") or "无有效点")
        out["error"] = r.get("error")
    try:
        doc = fetch_raw_http(cfg["vid"], cfg["bt"], cfg["tlbt"], cookie)
        if str(doc.get("status")) != "200":
            out["error"] = doc.get("message") or "接口返回非 200"
            return out
        resp = doc.get("response") or {}
        out["auth"] = auth_state(resp)
        series, src = parse_series(resp, cfg.get("specs"), cfg.get("markets"),
                                   strict=bool(cfg.get("strict")))
        out["series"] = series
        out["source"] = src
        dates = sorted(series)
        for d in reversed(dates):
            if series.get(d) is not None:
                out["date"] = d
                out["price"] = series[d]
                break
        out["mode"] = "daily"
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    if sleep:
        time.sleep(sleep)
    return out


# ---------------------------------------------------------------------------
# 抓取 · 曲线接口（getSingleCurve）—— 可回溯任意历史区间
#   与 queryPricePage 的分工：
#     · queryPricePage  列固定 **5 个日期**（以 queryEndDate 为锚向前取，不支持翻页）
#                       —— 只适合"取最新一期"，无法回溯
#     · getSingleCurve  传 queryStartDate/queryEndDate 返回**整段日序列**，
#                       且每条带 lowPrice/highPrice/**middlePrice(主流价)**
#                       —— 补历史与日常取数都用它，一次请求拿一段
#   businessId 由行枚举（queryPricePage）得到，品种+市场+规格唯一且稳定。
# ---------------------------------------------------------------------------
CURVE_URL = f"{API_BASE}/ndc/price/curve/getSingleCurve"

# 曲线点的取值优先级：主流价 > 最低价 > 最高价（与 pick_price 同哲学）
CURVE_PRICE_KEYS = ("middlePrice", "lowPrice", "highPrice")


def _post_json(url: str, payload: dict, cookie: Optional[str] = None,
               timeout: int = 60) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    hdrs = {"User-Agent": UA, "Referer": f"{API_BASE}/page/", "Origin": API_BASE,
            "Content-Type": "application/json"}
    if cookie is None:
        cookie = cookie_header()
    if cookie:
        hdrs["Cookie"] = cookie
    for k, v in hdrs.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, data=body, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def fetch_curve_raw(business_id: int, business_type: int = 3, tlbt: int = 0,
                    index_price_type: int = 0, time_type: int = 0,
                    start_date: Optional[str] = None,
                    end_date: Optional[str] = None,
                    cookie: Optional[str] = None, timeout: int = 60) -> dict:
    """取某一行（品种×市场×规格）在 [start_date, end_date] 内的全部日价格点。

    日期格式 YYYY-MM-DD；time_type：0/2=日 1=周 3=月 4=季 5=年。
    """
    payload: dict[str, Any] = {"businessId": int(business_id),
                               "businessType": int(business_type),
                               "twoLevelBusinessType": int(tlbt),
                               "indexPriceType": int(index_price_type),
                               "timeType": int(time_type)}
    if start_date:
        payload["queryStartDate"] = str(start_date)
    if end_date:
        payload["queryEndDate"] = str(end_date)
    return _post_json(CURVE_URL, payload, cookie=cookie, timeout=timeout)


def curve_series(resp: dict) -> dict[str, Optional[float]]:
    """priceDataList → {YYYY-MM-DD: 价格}；取不到价格的点也登记为 None（铁律留空）"""
    out: dict[str, Optional[float]] = {}
    for item in resp.get("priceDataList") or []:
        if not isinstance(item, dict):
            continue
        d = str(item.get("dataDate") or "").replace("/", "-").strip()
        if not d:
            continue
        val = None
        for k in CURVE_PRICE_KEYS:
            val = to_number(item.get(k))
            if val is not None:
                break
        out[d] = val
    return out


def resolve_business_row(key: str, cookie: Optional[str] = None,
                         sleep: float = 0.5) -> dict[str, Any]:
    """按 VARIETY_MAP 的口径（specs / markets / strict）选出目标行。

    返回 {ok, business_id, market, spec, region, business_type, tlbt,
          index_price_type, error}；选不到时 ok=False 且 error 说明原因。
    """
    cfg = VARIETY_MAP.get(key)
    if not cfg:
        raise KeyError(f"未知品种 key: {key}")
    out: dict[str, Any] = {"ok": False, "business_id": None, "market": "", "spec": "",
                           "region": "", "business_type": cfg["bt"],
                           "tlbt": cfg["tlbt"], "index_price_type": 0, "error": None}
    try:
        doc = _post_json(QUERY_PRICE_URL,
                         {"varietiesId": cfg["vid"], "businessType": str(cfg["bt"]),
                          "twoLevelBusinessType": cfg["tlbt"], "timeType": 0,
                          "pageNum": 1, "pageSize": 100},
                         cookie=cookie)
        if str(doc.get("status")) != "200":
            out["error"] = doc.get("message") or "行枚举失败"
            return out
        rows = _iter_rows(doc.get("response") or {})
        cand = [r for r in rows if _spec_ok(_row_label(r)[1], cfg.get("specs"))]
        if not cand:
            out["error"] = "未有规格匹配行"
            return out
        markets = cfg.get("markets")
        order: list[dict] = []
        if markets:
            for m in markets:
                order += [r for r in cand if m in _row_label(r)[0]]
        if not bool(cfg.get("strict")):
            order += [r for r in cand if r not in order]
        if not order:
            avail = sorted({_row_label(r)[0] for r in cand})
            out["error"] = f"指定市场 {markets} 无行（候选 {avail}）"
            return out
        pick = order[0]
        mkt, sp = _row_label(pick)
        out.update({"ok": True, "business_id": pick.get("businessId"), "market": mkt,
                    "spec": sp, "region": pick.get("regionName") or "",
                    "business_type": pick.get("businessType", cfg["bt"]),
                    "tlbt": pick.get("twoLevelBusinessType", cfg["tlbt"]),
                    "index_price_type": pick.get("indexPriceType", 0) or 0})
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    if sleep:
        time.sleep(sleep)
    return out


def fetch_variety_curve(key: str, start_date: str, end_date: str,
                        cookie: Optional[str] = None,
                        row: Optional[dict] = None) -> dict[str, Any]:
    """按 key 取 [start_date, end_date] 的完整日序列（含历史）。

    返回 {key, name, unit, series, source, auth, error, business_id}
    """
    cfg = VARIETY_MAP[key]
    out: dict[str, Any] = {"key": key, "name": cfg["name"], "unit": cfg["unit"],
                           "series": {}, "source": "", "auth": "", "error": None,
                           "business_id": None}
    if row is None:
        row = resolve_business_row(key, cookie)
    if not row.get("ok"):
        out["error"] = row.get("error") or "未定位到目标行"
        return out
    out["business_id"] = row["business_id"]
    out["source"] = f"{row['market']}|{row['spec']}"
    try:
        doc = fetch_curve_raw(row["business_id"], row["business_type"], row["tlbt"],
                              row["index_price_type"], 0, start_date, end_date,
                              cookie=cookie)
        if str(doc.get("status")) != "200":
            out["error"] = doc.get("message") or "曲线接口返回非 200"
            return out
        resp = doc.get("response") or {}
        out["auth"] = auth_state(resp)
        out["series"] = curve_series(resp)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def fetch_daily(keys: Optional[list[str]] = None,
                cookie: Optional[str] = None) -> dict[str, dict[str, Any]]:
    """批量抓取，返回 {key: 结果}。逐品种独立，互不影响。"""
    keys = keys or [k for k in VARIETY_MAP
                    if "无权" not in VARIETY_MAP[k]["name"]]
    res: dict[str, dict[str, Any]] = {}
    for k in keys:
        res[k] = fetch_variety(k, cookie)
    return res


def check_login(path: Optional[Path] = None) -> tuple[bool, str]:
    """登录态体检：(是否可用, 说明)。用干胶(天胶, vid=259)作探针。"""
    ck = cookie_header(path)
    if not ck:
        return False, f"未找到 cookie 文件 {path or COOKIE_FILE}（请先跑 lz_login_setup.py）"
    exp = token_expiry(path)
    note = ""
    if exp:
        days = (exp - time.time()) / 86400
        note = f"，token 剩余 {days:.1f} 天"
        if days <= 0:
            return False, f"token 已过期{note}，请重跑 lz_login_setup.py"
    try:
        doc = fetch_raw_http(259, 3, 0, ck)
    except Exception as e:
        return False, f"接口异常 {type(e).__name__}: {e}{note}"
    resp = doc.get("response") or {}
    st = auth_state(resp)
    if st == "ok":
        return True, f"登录态有效（see=true）{note}"
    if st == "no_power":
        return False, f"登录态有效但无价格权限（see=false）{note}"
    return False, f"未取到登录态（匿名）{note}"


def verify_daily_vs_curve(keys: Optional[list[str]] = None,
                          probe_days: int = 14,
                          cookie: Optional[str] = None) -> list[dict[str, Any]]:
    """体检：逐品种比较**日报口径**与**曲线口径**在同一交易日的取值。

    用途：发现「未标记 curve_daily、但实际日志接口也取不到主流价」的品种
    （即口径分裂的漏网之鱼）。

    返回 [{key, name, date, daily, curve, diff, verdict}]
    verdict：ok（一致）/ drift（不一致，需改走曲线）/ unknown（某侧无值）
    """
    import datetime as _dt
    keys = keys or [k for k in VARIETY_MAP if "无权" not in VARIETY_MAP[k]["name"]]
    end = _dt.date.today()
    start = end - _dt.timedelta(days=int(probe_days))
    rows: list[dict[str, Any]] = []
    for k in keys:
        cfg = VARIETY_MAP[k]
        rec = {"key": k, "name": cfg["name"], "date": None,
               "daily": None, "curve": None, "diff": None,
               "verdict": "unknown", "market": "", "spec": ""}
        try:
            doc = fetch_raw_http(cfg["vid"], cfg["bt"], cfg["tlbt"], cookie)
            resp = (doc.get("response") or {}) if str(doc.get("status")) == "200" else {}
            ser, src = parse_series(resp, cfg.get("specs"), cfg.get("markets"),
                                    strict=bool(cfg.get("strict")))
            live = {d: v for d, v in ser.items() if v is not None}
            if live:
                d = max(live)
                rec["daily"] = live[d]
                rec["date"] = d.replace("/", "-")
                rec["market"] = src
        except Exception as e:                                   # noqa: BLE001
            logger.warning("体检 %s 日报口径失败: %s", cfg["name"], e)
        try:
            r = fetch_variety_curve(k, start.isoformat(), end.isoformat(), cookie=cookie)
            if not rec["market"]:
                rec["market"] = r.get("source") or ""
            live2 = {d: v for d, v in (r.get("series") or {}).items() if v is not None}
            if live2:
                if rec["date"] and rec["date"] in live2:
                    rec["curve"] = live2[rec["date"]]          # 同一天比
                    if not rec["spec"]:
                        rec["spec"] = ""
                else:
                    d2 = max(live2)
                    rec["curve"] = live2[d2]
                    rec["date"] = rec["date"] or d2
        except Exception as e:                                   # noqa: BLE001
            logger.warning("体检 %s 曲线口径失败: %s", cfg["name"], e)
        if rec["daily"] is None or rec["curve"] is None:
            rec["verdict"] = "unknown"
        else:
            rec["diff"] = rec["daily"] - rec["curve"]
            rec["verdict"] = "ok" if abs(rec["diff"]) < 1e-6 else "drift"
        rows.append(rec)
        time.sleep(0.3)
    return rows


# ---------------------------------------------------------------------------
# 抓取 · Playwright 回退（cookie 失效/风控升级时用）
# ---------------------------------------------------------------------------
_JS_FETCH = """async (payload) => {
    const r = await fetch('https://dc.oilchem.net/ndc/price/list/queryPricePage', {
        method: 'POST',
        credentials: 'include',
        headers: {'Content-Type': 'application/json',
                  'Referer': 'https://dc.oilchem.net/page/'},
        body: JSON.stringify(payload)
    });
    return {status: r.status, body: await r.text()};
}"""


async def fetch_raw(page, vid: int, bt: int, tlbt: int = 0,
                    page_size: int = 100) -> dict:
    """在已登录页面内调 queryPricePage。page 须已位于 dc.oilchem.net 域下。"""
    payload = {"varietiesId": vid, "businessType": str(bt),
               "twoLevelBusinessType": tlbt, "timeType": 0,
               "pageNum": 1, "pageSize": min(int(page_size), 100)}
    res = await page.evaluate(_JS_FETCH, payload)
    if res.get("status") != 200:
        raise RuntimeError(f"queryPricePage HTTP {res.get('status')}")
    return json.loads(res["body"])


async def fetch_variety_pw(page, key: str) -> dict[str, Optional[float]]:
    cfg = VARIETY_MAP[key]
    doc = await fetch_raw(page, cfg["vid"], cfg["bt"], cfg["tlbt"])
    if str(doc.get("status")) != "200":
        raise RuntimeError(f"{cfg['name']}: {doc.get('message')}")
    resp = doc.get("response") or {}
    if not is_authorized(resp):
        logger.warning("%s: 服务端未放行（see=false）", cfg["name"])
    series, _src = parse_series(resp, cfg.get("specs"), cfg.get("markets"),
                                strict=bool(cfg.get("strict")))
    return series


async def probe_authorization(page) -> bool:
    """登录态体检（Playwright 版）"""
    try:
        doc = await fetch_raw(page, 259, 3, 0)
        return is_authorized(doc.get("response") or {})
    except Exception as e:
        logger.warning("登录态体检失败: %s", e)
        return False


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="隆众价格中心 · 映射表与登录态体检")
    ap.add_argument("--check", action="store_true", help="体检登录态并试抓全部品种")
    ap.add_argument("--verify", action="store_true",
                    help="逐品种比对「日报口径 vs 曲线口径」，暴露口径分裂")
    args = ap.parse_args()

    if args.verify:
        print("隆众 · 日报口径 vs 曲线口径 体检")
        print("=" * 92)
        print(f"{'品种':<24}{'日期':<13}{'日报':>10}{'曲线(主流价)':>14}{'差':>10}  {'判定':<8}取值行")
        print("-" * 92)
        drift = []
        for r in verify_daily_vs_curve():
            dv = f"{r['daily']:.0f}" if r["daily"] is not None else "—"
            cv = f"{r['curve']:.0f}" if r["curve"] is not None else "—"
            df = f"{r['diff']:+.0f}" if r["diff"] is not None else "—"
            flag = {"ok": "一致",
                    "drift": "★分裂",
                    "unknown": "数据不足"}[r["verdict"]]
            if r["verdict"] == "drift":
                drift.append(r["key"])
            print(f"{r['name']:<24}{str(r['date'] or '—'):<13}{dv:>10}{cv:>14}{df:>10}  {flag:<8}{r['market']}")
        print("-" * 92)
        print(f"口径分裂 {len(drift)} 项：{', '.join(drift) if drift else '无'}")
        if drift:
            print("→ 处置：在 VARIETY_MAP 里给这些品种加 \"curve_daily\": True")
        sys.exit(0)

    if not args.check:
        print("隆众价格中心 · 品种映射表")
        print("=" * 78)
        for k, v in VARIETY_MAP.items():
            print(f"  {k:18s} {v['name']:26s} vid={v['vid']:<5} bt={v['bt']} "
                  f"tlbt={v['tlbt']:<3} specs={v.get('specs')}")
        print(f"\n共 {len(VARIETY_MAP)} 个映射项")
    else:
        ok, msg = check_login()
        print(f"登录态: {'✓' if ok else '✗'} {msg}")
        print("=" * 78)
        print(f"{'品种':<24}{'日期':<13}{'价格':>10}  {'状态':<10}取值市场")
        print("-" * 78)
        for k, r in fetch_daily().items():
            if r["price"] is not None:
                flag = "✓"
            elif r["auth"] == "no_power":
                flag = "无权限"
            elif r["auth"] == "anonymous":
                flag = "未登录"
            else:
                flag = r["error"] or "无值"
            p = f"{r['price']:.0f}" if r["price"] is not None else "—"
            print(f"{r['name']:<24}{str(r['date'] or '—'):<13}{p:>10}  {flag:<10}{r['source']}")
