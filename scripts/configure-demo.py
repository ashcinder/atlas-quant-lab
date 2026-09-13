#!/usr/bin/env python3
"""Interactive local-only configuration. Never prints or validates secrets remotely."""

import getpass
import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "backend/.env.demo.json"


def main():
    print("仅配置 Binance Spot Testnet / OKX 模拟交易。不要使用实盘密钥。")
    owner = input("策略交易页面显示的用户 ID: ").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", owner):
        raise SystemExit("用户 ID 格式无效")
    values = {"ATLAS_TRADING_OWNER_ID": owner}
    for venue in ("BINANCE", "OKX"):
        key = getpass.getpass(f"{venue} 模拟 API Key（留空跳过）: ").strip()
        if not key:
            continue
        secret = getpass.getpass(f"{venue} 模拟 API Secret: ").strip()
        phrase = (
            getpass.getpass("OKX 模拟 Passphrase: ").strip() if venue == "OKX" else ""
        )
        if not secret or (venue == "OKX" and not phrase):
            raise SystemExit("缺少必填凭据，未保存")
        values[f"ATLAS_{venue}_API_KEY"] = key
        values[f"ATLAS_{venue}_API_SECRET"] = secret
        if phrase:
            values["ATLAS_OKX_PASSPHRASE"] = phrase
    if len(values) == 1:
        raise SystemExit("没有配置任何模拟账户，未保存")
    if (
        DESTINATION.exists()
        and input("覆盖已有本机模拟配置？输入 yes: ").strip() != "yes"
    ):
        raise SystemExit("未更改已有配置")
    fd, temporary = tempfile.mkstemp(prefix=".env.demo-", dir=DESTINATION.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(values, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, DESTINATION)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f"已保存权限 0600 的本机配置：{DESTINATION}")
    print("停止原后端后运行：backend/.venv/bin/python scripts/run-demo.py")
    print("前端仍可运行 npm run dev。启动器固定测试环境、关闭实盘、单笔上限100 USDT。")


if __name__ == "__main__":
    main()
