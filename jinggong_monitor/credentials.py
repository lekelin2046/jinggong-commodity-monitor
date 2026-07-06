"""统一凭据管理

所有需要 SMM / 亚洲金属网账号密码的模块都应从此处导入，
避免凭据散落在多个文件、方便统一审计与轮换。

读取顺序：
1. 环境变量 SMM_ACCOUNT / SMM_PASSWORD / ASIANMETAL_ACCOUNT / ASIANMETAL_PASSWORD
2. .env 文件（若 python-dotenv 已安装）

缺失任一凭据时，require_*() 抛 RuntimeError，列出缺失项。
不在代码中保留任何默认密码。

注意：凭据在调用时动态读取（非模块 import 时固化），
便于运行中轮换密码或测试时注入临时环境变量。
"""

import os
from pathlib import Path

# 尝试加载项目根目录的 .env（一次性，加载到 os.environ）
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    # python-dotenv 未安装时静默跳过，靠环境变量即可
    pass


def _get(name: str) -> str:
    """读取环境变量，返回空字符串而非 None，便于类型标注。"""
    return os.environ.get(name, "")


def require_smm() -> tuple[str, str]:
    """需要 SMM 凭据时调用。缺失则抛 RuntimeError，列出缺失项。"""
    account = _get("SMM_ACCOUNT")
    password = _get("SMM_PASSWORD")
    missing = [n for n, v in [("SMM_ACCOUNT", account), ("SMM_PASSWORD", password)] if not v]
    if missing:
        raise RuntimeError(
            f"缺少 SMM 凭据: {', '.join(missing)}。"
            f"请在 .env 或环境变量中设置（参考 .env.example）。"
        )
    return account, password


def require_asianmetal() -> tuple[str, str]:
    """需要亚洲金属网凭据时调用。缺失则抛 RuntimeError。"""
    account = _get("ASIANMETAL_ACCOUNT")
    password = _get("ASIANMETAL_PASSWORD")
    missing = [
        n for n, v in [
            ("ASIANMETAL_ACCOUNT", account),
            ("ASIANMETAL_PASSWORD", password),
        ] if not v
    ]
    if missing:
        raise RuntimeError(
            f"缺少亚洲金属网凭据: {', '.join(missing)}。"
            f"请在 .env 或环境变量中设置（参考 .env.example）。"
        )
    return account, password
