#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针：亚洲金属网「价格走势」曲线接口的历史回溯能力（只读，2026-10-15）。

背景
------------------------------------------------------------------
蜂巢看板 13 项里稀土三品种（镨钕 / 镝铁 / 金属铽）原以为无历史
（`/PraseodymiumPriceIndex` 页 innerText 只显示**当日一次报价**）。
2026-10-15 实测发现该页**内联 echarts 走势图**，时间选择器为
1个月 / 3个月 / 12个月，数据来自：

    POST https://www.asianmetal.cn/price/priceChartExpectation.am
    body: ppId=<价格参数ID>&chartDate=<1|2|4>     # 1=1月 2=3月 4=12月
    → JS 数组 chartList，元素 PDate / PLNum(低) / PHNum(高) / PNum(中间)

ppId 取自 `POST /price/ajax/findParamList.am`（body `pId=<英文品名>`）的
`PriceParam_Id` 字段。实测 chartDate=4 → **250 点 / 12 个月**。

已定位（口径与蜂巢现用一致：中国出厂 + 人民币）
------------------------------------------------------------------
    PRND  526  镨钕混合金属 Pr 25%, Nd 75% 中国出厂   元/吨
    DYFE  504  镝铁 80% 中国出厂                     元/公斤
    TB    532  金属铽 99.9%min 中国出厂              元/公斤
    （对照）金属镝 499 / 氧化镝 501 / 氧化镨钕 525

⚠️ 三个坑
------------------------------------------------------------------
  1. **尾部含预测值**：接口名为 Expectation，series 含「7/14/28 天预测价格」，
     序列末端到**未来日期**（实测止于 2026-10-22）。回填**必须按 PDate 截断至当日**。
  2. 预测行 `PLNum/PHNum` 为 `null`，**不能靠字段空值判断**，只能靠 PDate 过滤。
  3. `PNum == (PLNum+PHNum)/2`（实测相等）—— 与蜂巢/曼德现用取法一致，
     回填时沿用该取法即可保持口径连续。
  4. 💡 **不限稀土**：镁锭（精工/曼德在用）应同样适用，可作精工历史回填备选通道。

用法（须在**仓库根目录**执行，cookie 相对路径按 cwd 解析）
------------------------------------------------------------------
    python3 tools/probes/probe_am_chart_history.py             # 探默认三品种
    python3 tools/probes/probe_am_chart_history.py 526 504 532 # 指定 ppId
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

os.environ.pop("NODE_OPTIONS", None)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

COOKIE_FILE = ROOT / "data" / "asianmetal_cookies.json"
# 入口页（任取其一即可，仅为建立登录态；ppId 与页面无关）
ENTRY = "https://www.asianmetal.cn/PraseodymiumPriceIndex"
DEFAULT_PPIDS = [526, 504, 532]
LABEL = {526: "镨钕混合金属 Pr25/Nd75 中国出厂 元/吨",
         504: "镝铁 80% 中国出厂 元/公斤",
         532: "金属铽 99.9%min 中国出厂 元/公斤"}

_JS = r"""
async (ppids) => {
  const out = {curves: {}};
  for (const id of ppids) {
    for (const cd of [1, 2, 4]) {
      const r = await fetch('/price/priceChartExpectation.am', {
        method: 'POST', credentials: 'include',
        headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                  'X-Requested-With': 'XMLHttpRequest'},
        body: 'ppId=' + id + '&chartDate=' + cd
      });
      const txt = await r.text();
      let arr = null;
      try { arr = eval(txt); } catch (e) { arr = null; }
      if (Array.isArray(arr)) {
        const dates = arr.map(x => x.PDate);
        out.curves[id + '_cd' + cd] = {
          len: arr.length,
          first: dates[0], last: dates[dates.length - 1],
          sample: arr[Math.floor(arr.length / 2)],
        };
      } else {
        out.curves[id + '_cd' + cd] = {raw: String(txt).slice(0, 160)};
      }
    }
  }
  return out;
}
"""


async def main() -> int:
    from playwright.async_api import async_playwright

    ppids = [int(x) for x in sys.argv[1:]] or DEFAULT_PPIDS
    if not COOKIE_FILE.exists():
        print(f"[FATAL] 缺少 cookie：{COOKIE_FILE}")
        return 1
    cks = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
    print(f"[i] cookie {len(cks)} 个  目标 ppId={ppids}")

    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await b.new_context(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"))
        await ctx.add_cookies(cks)
        pg = await ctx.new_page()
        await pg.goto(ENTRY, wait_until="domcontentloaded", timeout=45000)
        await pg.wait_for_timeout(6000)

        # 登录态确认
        logged = await pg.evaluate("""async () => {
            const r = await fetch('/login/ifLogin.am', {method:'POST', credentials:'include'});
            return (await r.text()).trim();
        }""")
        print(f"[i] 登录态 ifLogin.am → {logged!r}（末段为用户名/公司名，空则未登录）")

        res = await pg.evaluate(_JS, ppids)
        print(f"\n{'='*80}")
        for key, v in res["curves"].items():
            pid = int(key.split("_")[0])
            tag = f"{key:10s} {LABEL.get(pid, '')}"
            if "len" in v:
                print(f"  {tag}")
                print(f"      点数={v['len']:>4}  {v['first']} ~ {v['last']}")
                print(f"      中段样本={json.dumps(v['sample'], ensure_ascii=False)[:220]}")
            else:
                print(f"  {tag}  → 非数组：{v['raw']}")
        await b.close()

    print("\n[提示] 尾部日期 > 今日者即 7/14/28 天**预测值**，回填须按 PDate 截断至当日。")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
