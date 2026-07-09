"""精工有色金属 - 16 品种今日价格快速抓取（无截图）"""
import asyncio, sys, os, re
from datetime import datetime
from pathlib import Path
from typing import Optional
sys.path.insert(0, str(Path(__file__).parent))
from jinggong_monitor.credentials import require_smm
os.environ["NO_PROXY"] = "ccmn.cn,chinatungsten.com,smm.cn,hq.smm.cn,user.smm.cn,asianmetal.cn"

# ---------- 公共 ----------
async def _launch():
    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    b = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled","--no-sandbox"])
    return p, b

async def _login_smm(ctx):
    smm_user, smm_pass = require_smm()
    page = await ctx.new_page()
    await page.goto("https://user.smm.cn/login", timeout=30000, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)
    await page.locator("#userName").fill(smm_user)
    await page.locator("#password").fill(smm_pass)
    await page.locator("#user_account_password_login_button").click()
    await asyncio.sleep(5)
    ok = "login" not in page.url.lower()
    await page.close()
    return ok

# 从 SMM 的铝/镁文本中正则提取（取第3个数字=均价）
def _extract_smm(text: str, pattern: str) -> Optional[int]:
    m = re.search(pattern, text)
    return int(m.group(3)) if m else None

# ---------- 抓取 ----------
def get_ccmn():
    from jinggong_monitor.fetcher_ccmn import CcmnFetcher
    return CcmnFetcher().fetch(datetime.now().strftime("%Y-%m-%d"))

async def get_smm():
    p, b = await _launch()
    ctx = await b.new_context(viewport={"width":1280,"height":900}, bypass_csp=True)
    if not await _login_smm(ctx):
        await b.close(); await p.stop()
        return {}, "❌ SMM 登录失败"
    page = await ctx.new_page()
    await page.goto("https://hq.smm.cn/aluminum", timeout=20000, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)
    al = await page.inner_text("body")
    mg_page = await ctx.new_page()
    await mg_page.goto("https://hq.smm.cn/magnesium", timeout=20000, wait_until="domcontentloaded")
    await mg_page.wait_for_timeout(5000)
    mg = await mg_page.inner_text("body")
    await mg_page.close(); await page.close(); await ctx.close()
    await b.close(); await p.stop()

    r = {}
    r["ADC12"] = _extract_smm(al, r"ADC12\D+?(\d+)\D+?(\d+)\D+?(\d+)")
    r["A380"] = _extract_smm(al, r"A380\D+?(\d+)\D+?(\d+)\D+?(\d+)")
    r["AlSi9Cu3"] = _extract_smm(al, r"AlSi9Cu3\D+?(\d+)\D+?(\d+)\D+?(\d+)")
    r["A356"] = _extract_smm(al, r"A356铝合金\s+\D+?(\d+)\D+?(\d+)\D+?(\d+)")
    r["Wenxi_MG"] = _extract_smm(mg, r"镁锭9990（闻喜）\D+?(\d+)\D+?(\d+)\D+?(\d+)")
    r["AM60B"] = _extract_smm(mg, r"AM60B出厂价\D+?(\d+)\D+?(\d+)\D+?(\d+)")
    r["AZ91D"] = _extract_smm(mg, r"AZ91D出厂价[^（]*?(\d+)\D+?(\d+)\D+?(\d+)")
    return r, ""

def get_wti():
    import akshare as ak
    df = ak.futures_foreign_commodity_realtime(symbol="CL")
    return round(float(df.iloc[0]["最新价"]), 2)

def get_tungsten():
    from jinggong_monitor.fetcher_tungsten import ChinatungstenFetcher
    r = ChinatungstenFetcher().fetch()
    return r.get("W")

async def get_wenxi_mg():
    from jinggong_monitor.fetcher_asianmetal import fetch_async
    r = await fetch_async()
    return r.get("Wenxi_MG")

# ---------- 主流程 ----------
async def main():
    print("=" * 75)
    print(f"  精工有色金属 · 16 品种今日价格   {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 75)

    print("\n[1/4] 长江现货 ccmn ... ", end="", flush=True)
    ccmn = get_ccmn()
    print(f"{len(ccmn)} 品种")

    print("[2/4] SMM 登录抓取 ... ", end="", flush=True)
    smm, err = await get_smm()
    print(f'{len([v for v in smm.values() if v])} 品种' + (f' | {err}' if err else ''))

    print("[3/4] 亚洲金属网闻喜镁锭 ... ", end="", flush=True)
    wenxi_mg = await get_wenxi_mg()
    print(f"{wenxi_mg} 元/吨" if wenxi_mg else "未获取")

    print("[4/5] WTI 原油 ... ", end="", flush=True)
    wti = get_wti()
    print(f"{wti} USD/bbl")

    print("[5/5] 中钨在线钨粉 ... ", end="", flush=True)
    w = get_tungsten()
    print(f"{w} 元/千克" if w else "未获取")

    # 16 个品种 + WTI
    rows = [
        ("Col2  ADC12",            smm.get("ADC12"),       "SMM"),
        ("Col3  A380",             smm.get("A380"),        "SMM"),
        ("Col4  AlSi9Cu3",         smm.get("AlSi9Cu3"),    "SMM"),
        ("Col5  A356",             smm.get("A356"),        "SMM"),
        ("Col6  A00铝",            ccmn.get("A00_AL"),     "ccmn"),
        ("Col7  铜",               ccmn.get("CU"),         "ccmn"),
        ("Col8  金属硅中间价441",  ccmn.get("SI_553_331_AVG"), "ccmn"),
        ("Col9  金属硅中间价3303", ccmn.get("SI_3303_2202_MIN"),"ccmn"),
        ("Col10 镁",               ccmn.get("MG"),         "ccmn"),
        ("Col11 电解锰",           ccmn.get("MN"),         "ccmn"),
        ("Col12 金属硅中间价331",  ccmn.get("SI_553_331_MAX"),"ccmn"),
        ("Col13 闻喜镁锭",         wenxi_mg,               "亚洲金属网"),
        ("Col14 AM60B",            smm.get("AM60B"),       "SMM"),
        ("Col15 AZ91D",            smm.get("AZ91D"),       "SMM"),
        ("Col16 钨粉",             w,                "中钨在线"),
        ("—     WTI 原油",         wti,              "akshare"),
    ]

    print("\n" + "=" * 75)
    print("  品种                    来源       价格          单位")
    print("-" * 75)
    for label, val, src in rows:
        if val:
            unit = "USD/bbl" if "WTI" in label else "元/千克" if "钨粉" in label else "元/吨"
            print(f"  {label:20s}  {src:8s}  {val:>8,}  {unit}")
        else:
            print(f"  {label:20s}  {src:8s}  {'—':>8}  未获取")

    print("=" * 75)

asyncio.run(main())
