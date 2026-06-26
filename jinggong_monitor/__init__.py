"""精工板块大宗原材料监控 - 核心包"""

import os
import yaml
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).parent.parent
_CONFIG_DIR = _PROJECT_ROOT / "config"


def load_yaml(filename: str) -> dict[str, Any]:
    """加载 YAML 配置文件"""
    path = _CONFIG_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_varieties() -> list[dict]:
    """获取品种配置列表"""
    cfg = load_yaml("varieties.yaml")
    return cfg.get("commodities", [])


def get_sources() -> dict:
    """获取数据源配置"""
    cfg = load_yaml("sources.yaml")
    return cfg.get("sources", {})


def get_project_root() -> Path:
    return _PROJECT_ROOT


def get_data_dir() -> Path:
    return _PROJECT_ROOT / "data"
