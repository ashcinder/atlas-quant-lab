#!/usr/bin/env python3
"""Load the explicit ignored JSON config and start only the demo backend."""

import json
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "backend/.env.demo.json"
ALLOWED = {
    "ATLAS_TRADING_OWNER_ID",
    "ATLAS_BINANCE_API_KEY",
    "ATLAS_BINANCE_API_SECRET",
    "ATLAS_OKX_API_KEY",
    "ATLAS_OKX_API_SECRET",
    "ATLAS_OKX_PASSPHRASE",
}


def demo_environment(values, inherited):
    if not isinstance(values, dict) or set(values) - ALLOWED:
        raise ValueError("配置字段无效")
    if not values.get("ATLAS_TRADING_OWNER_ID"):
        raise ValueError("缺少用户 ID")
    if any(
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or any(ch.isspace() for ch in value)
        for value in values.values()
    ):
        raise ValueError("配置值格式无效")
    ready = 0
    for venue in ("BINANCE", "OKX"):
        fields = [f"ATLAS_{venue}_API_KEY", f"ATLAS_{venue}_API_SECRET"]
        if venue == "OKX":
            fields.append("ATLAS_OKX_PASSPHRASE")
        if any(field in values for field in fields):
            if not all(field in values for field in fields):
                raise ValueError("账户配置不完整")
            ready += 1
    if not ready:
        raise ValueError("未配置模拟账户")
    # Never inherit unrelated exchange credentials or an existing live switch.
    environment = {
        key: value
        for key, value in inherited.items()
        if not key.startswith(("ATLAS_TRADING_", "ATLAS_BINANCE_", "ATLAS_OKX_"))
    }
    environment.update(values)
    environment.update(
        ATLAS_TRADING_ENABLED="1",
        ATLAS_TRADING_LIVE_ENABLED="0",
        ATLAS_BINANCE_MODE="demo",
        ATLAS_OKX_MODE="demo",
        ATLAS_TRADING_MAX_ORDER_USDT="100",
    )
    return environment


def main():
    if not CONFIG.is_file():
        raise SystemExit("请先运行 scripts/configure-demo.py 配置本机模拟账户")
    if CONFIG.is_symlink() or stat.S_IMODE(CONFIG.stat().st_mode) & 0o077:
        raise SystemExit("配置必须是非符号链接的0600权限文件")
    try:
        environment = demo_environment(json.loads(CONFIG.read_text()), os.environ)
    except (ValueError, OSError):
        raise SystemExit("模拟配置无效；未启动，未输出凭据") from None
    os.chdir(ROOT / "backend")
    os.execve(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        environment,
    )


if __name__ == "__main__":
    main()
