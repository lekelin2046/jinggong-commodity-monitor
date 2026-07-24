// 品种显示名 / 单位 / 数据来源 / 分类分组（与 docs/index.html 保持一致）

const VARIETY_NAMES = {
  "ADC12": "ADC12", "A380": "A380", "AlSi9Cu3": "AlSi9Cu3", "A356": "A356",
  "A00_AL": "A00铝", "CU": "铜", "SI_441": "硅441", "SI_3303": "硅3303", "SI_331": "硅331",
  "MG": "镁", "MN": "电解锰", "Wenxi_MG": "闻喜镁锭", "AM60B": "AM60B", "AZ91D": "AZ91D",
  "W": "钨粉", "WTI": "WTI原油", "IRON_ORE": "卡粉65%京唐港", "COKE": "一级冶金焦MT<7",
  "SS_304": "304不锈钢", "SS_409": "409不锈钢", "SS_439": "439不锈钢", "SS_441": "441不锈钢",
  "NICKEL_IRON": "镍铁", "HIGH_CARBON_FECR": "高碳铬铁", "ADC12_JAPAN_CIF": "ADC12日本CIF"
};

const VARIETY_UNITS = {
  "W": "元/千克", "WTI": "美元/桶", "IRON_ORE": "元/湿吨", "COKE": "元/吨", "ADC12_JAPAN_CIF": "美元/吨"
};

const DEFAULT_UNIT = "元/吨";

const VARIETY_SOURCES = {
  "ADC12": "上海有色", "A380": "上海有色", "AlSi9Cu3": "上海有色", "A356": "上海有色",
  "A00_AL": "长江现货", "CU": "长江现货", "SI_441": "长江现货", "SI_3303": "长江现货",
  "MG": "长江现货", "MN": "长江现货", "SI_331": "长江现货",
  "Wenxi_MG": "亚洲金属网", "AM60B": "上海有色", "AZ91D": "上海有色",
  "W": "中钨在线", "WTI": "NYMEX CL", "IRON_ORE": "上海有色", "COKE": "上海有色",
  "SS_304": "卓创资讯", "SS_409": "卓创资讯", "SS_439": "卓创资讯", "SS_441": "卓创资讯",
  "NICKEL_IRON": "卓创资讯", "HIGH_CARBON_FECR": "卓创资讯", "ADC12_JAPAN_CIF": "上海有色"
};

const CATEGORIES = [
  { "name": "铝及铝合金", "codes": ["ADC12", "A380", "AlSi9Cu3", "A356", "A00_AL"] },
  { "name": "铜硅镁锰", "codes": ["CU", "SI_441", "SI_3303", "SI_331", "MG", "MN"] },
  { "name": "镁合金", "codes": ["Wenxi_MG", "AM60B", "AZ91D"] },
  { "name": "钢材及铁合金", "codes": ["SS_304", "SS_409", "SS_439", "SS_441", "NICKEL_IRON", "HIGH_CARBON_FECR"], "noTrend": true },
  { "name": "钨粉及原油", "codes": ["W", "WTI"] },
  { "name": "钢铁原料", "codes": ["IRON_ORE", "COKE", "ADC12_JAPAN_CIF"], "noTrend": true }
];

const COLORS = ["#2563eb", "#dc2626", "#16a34a", "#ca8a04", "#9333ea", "#0891b2", "#ea580c", "#4f46e5", "#be123c", "#0d9488", "#d97706", "#7c3aed"];

// 2026 年中国法定节假日（硬编码，不依赖外部 API）
const HOLIDAYS_2026 = new Set([
  "2026-01-01","2026-01-02","2026-01-03",
  "2026-01-28","2026-01-29","2026-01-30","2026-01-31","2026-02-01","2026-02-02","2026-02-03",
  "2026-04-04","2026-04-05","2026-04-06",
  "2026-05-01","2026-05-02","2026-05-03","2026-05-04","2026-05-05",
  "2026-06-19","2026-06-20","2026-06-21",
  "2026-10-01","2026-10-02","2026-10-03","2026-10-04","2026-10-05","2026-10-06","2026-10-07","2026-10-08"
]);

module.exports = {
  VARIETY_NAMES, VARIETY_UNITS, DEFAULT_UNIT, VARIETY_SOURCES, CATEGORIES, COLORS, HOLIDAYS_2026
};
