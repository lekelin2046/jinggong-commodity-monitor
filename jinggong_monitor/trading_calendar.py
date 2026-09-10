#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trading_calendar.py — 项目统一交易日历
====================================================================
全项目「是否应抓取」的唯一判定入口，供以下脚本共用，避免多处各写一份
节假日表导致失同步：
  - daily_update_all.py（15:00 全品种主抓取）
  - jinggong_monitor/daily_plastic.py（15:30 塑料牌号抓取）
  - daily_check_missed.py（17:00 补抓检查）

判定规则：非周六/周日，且不在法定节假日集合内 → 应抓取。
调休补班日（如 1/4、2/14、2/28、5/9、9/20、10/10）均为周末，
大宗现货市场同样休市，故由 weekday()>=5 一并排除，无需单列。

⚠️ 跨年维护：每年国务院办公厅公布次年放假安排后，需更新 HOLIDAYS 集合。
"""
import datetime

# 中国法定节假日（2026 年）—— (月, 日)
HOLIDAYS_2026 = {
    # 元旦 1/1-1/3
    (1, 1), (1, 2), (1, 3),
    # 春节 2/15-2/23（2/15、2/21、2/22 为周末，已覆盖）
    (2, 15), (2, 16), (2, 17), (2, 18), (2, 19), (2, 20), (2, 21), (2, 22), (2, 23),
    # 清明 4/4-4/6（4/4、4/5 为周末，已覆盖）
    (4, 4), (4, 5), (4, 6),
    # 劳动节 5/1-5/5（5/2、5/3 为周末，已覆盖）
    (5, 1), (5, 2), (5, 3), (5, 4), (5, 5),
    # 端午 6/19-6/21（6/20、6/21 为周末，已覆盖）
    (6, 19), (6, 20), (6, 21),
    # 中秋 9/25-9/27（9/26、9/27 为周末，已覆盖）
    (9, 25), (9, 26), (9, 27),
    # 国庆 10/1-10/7
    (10, 1), (10, 2), (10, 3), (10, 4), (10, 5), (10, 6), (10, 7),
}

# 按年分组，便于跨年扩展（2027 年发布后补入）
HOLIDAYS = {
    2026: HOLIDAYS_2026,
}


def holidays_of(year: int) -> set:
    """取某年法定节假日集合；未收录的年份返回空集（仅按周末判定）"""
    return HOLIDAYS.get(year, set())


def is_trading_day(d: datetime.date = None) -> bool:
    """是否为应抓取的交易日（非周末且非法定节假日）"""
    if d is None:
        d = datetime.date.today()
    if d.weekday() >= 5:            # 周六(5) / 周日(6)
        return False
    if (d.month, d.day) in holidays_of(d.year):
        return False
    return True


def skip_reason(d: datetime.date = None) -> str:
    """非交易日原因描述；交易日返回空串。用于日志输出。"""
    if d is None:
        d = datetime.date.today()
    if d.weekday() >= 5:
        return "周六" if d.weekday() == 5 else "周日"
    if (d.month, d.day) in holidays_of(d.year):
        return f"法定节假日（{d.month}月{d.day}日）"
    return ""


if __name__ == "__main__":
    t = datetime.date.today()
    print(f"{t} ({t.strftime('%A')}) 交易日={is_trading_day(t)} 原因={skip_reason(t) or '正常交易日'}")
