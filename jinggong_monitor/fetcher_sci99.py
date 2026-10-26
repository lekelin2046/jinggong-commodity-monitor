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
import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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


async def fetch_sci99_async(timeout: int = 90, holder: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """异步抓取卓创 6 个品种的平均价

    Args:
        timeout: 保留参数（兼容旧调用），实际超时由各品种 goto 内部控制
        holder: 可选外部字典；每个品种取到值后立即写入，
                即使外层 asyncio.wait_for 超时取消任务，已取部分也不丢失
                （2026-08-28 修复：此前总时限一到部分结果被整体丢弃）

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
                    if holder is not None:
                        holder[code] = price  # 立即外写，超时取消也不丢
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


# ===========================================================================
# 曼德热系统专用：按「品种编号」精确定位单行（2026-10-14 新增）
# ===========================================================================
# 背景：曼德 2026-10-14 逐项确认了 5 个原「未接入」品种的口径（见
#       output/曼德看板品种口径优化说明_2026-10-14.md）。
#
# 为什么用「品种编号」而不是关键词：search.aspx?keyword=<编号> 实测**精确返回
# 唯一一行**，而按牌号关键词搜索会返回同名多厂家/多市场（如 T30S 有 20 条带价行），
# 无法保证口径唯一。编号取自搜索页「ID」列，是卓创内部稳定的行标识。
#
# 每项：(曼德品种代码, 卓创编号, 口径描述, 单位换算倍数)
#   · scale=1      源单位已是 元/吨
#   · scale=10000  源单位为 万元/吨，×10000 归一到看板统一的 元/吨
#     （曼德清单对镨钕金属标注的单位即 元/吨，故此处做单位归一，不改变数值含义）
SCI99_MAND_TARGETS: Tuple[Tuple[str, int, str, float], ...] = (
    ("PRND",      34618,  "金属镨钕 PrNd≥99% · 中国 · 市场价",           10000),
    ("PA6",       43234,  "PA6 · BL3280H · 华南 · 市场价",                1),
    ("PA66",      16980,  "PA66 · EPR27 · 神马工程塑料 · 企业报价(出厂价)", 1),
    ("PP_T30S",   17969,  "T30S 拉丝料 · 大庆石化 · 沈阳 · 市场价",        1),
    ("PP_EP548R", 198236, "EP548R 高熔共聚 · 大庆炼化 · 余姚 · 市场价",     1),
)

# 搜索页表格列序（2026-10-14 实测，表头 18 列 / 数据行 19 列）
_MAND_COLS = {
    "id": 0, "name": 1, "spec": 2, "vendor": 3, "market": 4,
    "ptype": 5, "dtype": 6, "low": 8, "high": 9, "avg": 10,
    "unit": 14, "date": 15,
}

_JS_MAND_TABLE = """
() => {
  const out = [];
  for (const tr of document.querySelectorAll('table tr')) {
    const cells = [...tr.querySelectorAll('th,td')].map(td => td.innerText.trim());
    if (cells.some(c => c !== '')) out.push(cells);
  }
  return out;
}
"""

# 目标编号行等待与重试参数（2026-10-26 引入，见 fetch_sci99_mand_async 注释）
_MAND_WAIT_MS = 12000       # 单次页面「等待目标编号行出现」的上限
_MAND_RETRY = 3             # 最多尝试次数（含首次）


async def _wait_rows_for(page, vid, timeout_ms: int = _MAND_WAIT_MS,
                         poll_ms: int = 500) -> List[List[str]]:
    """轮询表格，直到出现「首列 == 目标编号」的行为止，返回最后一次快照。

    替代原先「固定 sleep 后取一次」的做法，消除页面渲染竞态导致的空结果。
    超时未出现也返回最后快照，由上层 parse_mand_row 判定命中与否。
    """
    target = str(vid)
    rows: List[List[str]] = []
    for _ in range(max(1, timeout_ms // poll_ms)):
        rows = await page.evaluate(_JS_MAND_TABLE)
        if any(r and str(r[0]).strip() == target for r in rows):
            return rows
        await page.wait_for_timeout(poll_ms)
    return rows


def _cell(row: List[str], key: str) -> str:
    i = _MAND_COLS[key]
    return row[i].strip() if i < len(row) else ""


def _norm_quote_date(raw: str, today: dt.date) -> Optional[str]:
    """卓创报价日期形如 `10/14`（无年份）→ `2026-10-14`（跨年时回退一年）"""
    m = re.match(r"(\d{1,2})\s*[/-]\s*(\d{1,2})", (raw or "").strip())
    if not m:
        return None
    mo, da = int(m.group(1)), int(m.group(2))
    year = today.year
    if mo > today.month + 1:      # 1 月看到 12/xx ⇒ 属上一年
        year -= 1
    try:
        return dt.date(year, mo, da).isoformat()
    except ValueError:
        return None


def _to_price(raw: str) -> Optional[float]:
    """清成纯数值；占位/空 → None（守铁律，绝不估值）"""
    s = re.sub(r"[,，\s]", "", (raw or "").strip())
    s = re.sub(r"^[▼▲↑↓+\-]+", "", s)
    if not s or s in ("-", "--", "无", "暂无"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


def parse_mand_row(rows: List[List[str]], vid: int,
                   today: Optional[dt.date] = None) -> Optional[dict]:
    """在搜索页表格里按编号取出目标行 → 结构化结果（含**源报价日期**）"""
    today = today or dt.date.today()
    target = str(vid)
    for row in rows:
        if _cell(row, "id") != target:
            continue
        avg_raw = _cell(row, "avg")
        if not avg_raw:                      # 表头行没有「平均价」数字位
            continue
        value = _to_price(avg_raw)
        if value is None:
            return {"value": None, "date": _norm_quote_date(_cell(row, "date"), today),
                    "raw_unit": _cell(row, "unit"), "spec": _cell(row, "spec"),
                    "vendor": _cell(row, "vendor"), "market": _cell(row, "market"),
                    "pnote": _cell(row, "ptype"), "note": ""}
        return {
            "value": value,
            "date": _norm_quote_date(_cell(row, "date"), today),
            "raw_unit": _cell(row, "unit"),
            "spec": _cell(row, "spec"),
            "vendor": _cell(row, "vendor"),
            "market": _cell(row, "market"),
            "pnote": _cell(row, "ptype"),
            "note": row[-1] if len(row) > 16 else "",
        }
    return None


async def fetch_sci99_mand_async(targets=None, wait_ms: int = 3000,
                                 holder: Optional[Dict[str, dict]] = None
                                 ) -> Dict[str, dict]:
    """按品种编号抓取曼德新品种的单行报价（含单位归一与源报价日期）。

    参数
        targets: 可覆盖默认的 SCI99_MAND_TARGETS（测试用）
        holder : 外部字典，逐项取到即写入（外层超时也不丢已得部分）

    返回
        {code: {"value": float 元/吨, "date": "YYYY-MM-DD", "raw_unit": str,
                "spec": str, "vendor": str, "market": str}}
        —— 取不到价格的编号**不入结果**（前端按缺失渲染，绝不沿用前值）。
    """
    targets = targets or SCI99_MAND_TARGETS

    cookies = _load_cookies()
    if not cookies:
        print("  [卓创] cookie 不可用，跳过曼德新品种")
        return {}
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("  [卓创] Playwright 未安装")
        return {}

    out: Dict[str, dict] = {}
    today = dt.date.today()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-quic", "--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36",
            viewport={"width": 1600, "height": 1000},
            locale="zh-CN",
        )
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        try:
            await page.goto("https://www.sci99.com/", wait_until="domcontentloaded",
                            timeout=30000)
        except Exception:                                        # noqa: BLE001
            pass

        for code, vid, desc, scale in targets:
            url = SEARCH_URL.format(vid=vid)
            hit = None
            load_err = None
            # 2026-10-26 修复：原「固定 sleep(wait_ms) 后取一次表格」存在渲染竞态——
            # 结果行尚未渲染即快照，得 rows 只有表头 → parse 返回 None →
            # 打印「页面未返回该编号行」静默留空。实测同一编号 2 分钟内连测
            # 两次结果互相矛盾（一次成功、一次全缺），即典型竞态而非源方停更。
            # 改为「轮询等待目标编号行出现 + 未命中退避重载重试」。
            for attempt in range(1, _MAND_RETRY + 1):
                try:
                    await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                    if attempt == 1:
                        await page.wait_for_timeout(min(wait_ms, 1500))
                    rows = await _wait_rows_for(page, vid, timeout_ms=_MAND_WAIT_MS)
                except Exception as e:                           # noqa: BLE001
                    load_err = f"{type(e).__name__}: {e}"
                    await page.wait_for_timeout(1500 * attempt)
                    continue

                hit = parse_mand_row(rows, vid, today)
                if hit is not None:
                    break                                        # 命中（含源方空值）
                if attempt < _MAND_RETRY:
                    print(f"  [卓创] {code}（编号 {vid}）: 第 {attempt} 次未取到该行"
                          f"（表格 {len(rows)} 行），退避重载重试")
                    await page.wait_for_timeout(1500 * attempt)

            if hit is None:
                extra = f"；末次异常 {load_err}" if load_err else ""
                print(f"  [卓创] {code}（编号 {vid}）: 页面未返回该编号行 "
                      f"（已重试 {_MAND_RETRY} 次）→ 留空{extra}")
                continue
            if hit["value"] is None:
                print(f"  [卓创] {code}（编号 {vid}）: 源方无报价（{hit.get('note') or '空值'}）"
                      f" → 留空")
                continue

            value = hit["value"] * scale
            rec = {
                "value": round(value, 2),
                "date": hit["date"],
                "raw_unit": hit["raw_unit"],
                "spec": hit["spec"], "vendor": hit["vendor"], "market": hit["market"],
            }
            out[code] = rec
            if holder is not None:
                holder[code] = rec
            unit_note = "" if scale == 1 else f"（源 {hit['raw_unit']} ×{scale:g}）"
            print(f"  [卓创] {code}: {rec['value']:,.2f} 元/吨{unit_note}"
                  f"  @{rec['date']}  [{hit['vendor'] or '-'}"
                  f"|{hit['market'] or '-'}|{hit['spec']}]")

        await browser.close()

    return out


def fetch_sci99_mand_sync(targets=None) -> Dict[str, dict]:
    """同步包装，供 mand_update.py 调用"""
    return asyncio.run(fetch_sci99_mand_async(targets=targets))
