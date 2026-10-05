"""Run on the strategy developer's machine: source and signing key stay here."""

import argparse
import hashlib
import json
import os
import runpy
import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)


def canonical(body):
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def write_private(path, content):
    with open(path, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as file:
        file.write(content)


def initialize(args):
    directory = args.directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    source = args.strategy.expanduser().resolve()
    data = source.read_bytes()
    salt = os.urandom(32)
    key = Ed25519PrivateKey.generate()
    commitment = hashlib.sha256(salt + data).hexdigest()
    metadata = {
        "name": args.name,
        "strategy_id": "private_" + uuid4().hex[:16],
        "source_kind": "private_runner",
        "execution_mode": "private_runner",
        "runner_public_key": key.public_key().public_bytes_raw().hex(),
        "code_commitment": commitment,
        "markets": ["CRYPTO"],
        "published": True,
        "description": "开发者本地执行，源码不上传；签名信号接入平台模拟成交。",
    }
    write_private(
        directory / "runner.key",
        key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex(),
    )
    write_private(
        directory / "local.json",
        json.dumps(
            {
                "source": str(source),
                "salt": salt.hex(),
                "code_commitment": commitment,
            }
        ),
    )
    write_private(
        directory / "release.public.json",
        json.dumps(metadata, ensure_ascii=False, indent=2),
    )
    print(f"只在页面选择公开登记文件：{directory / 'release.public.json'}")


def run(args):
    directory = args.directory.expanduser().resolve()
    local = json.loads((directory / "local.json").read_text())
    config = json.loads(args.config.read_text())
    key = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex((directory / "runner.key").read_text())
    )
    expected_hash = hashlib.sha256(
        canonical(
            {
                "execution_mode": "private_runner",
                "runner_public_key": key.public_key().public_bytes_raw().hex(),
                "code_commitment": local["code_commitment"],
            }
        )
    ).hexdigest()
    if config["content_hash"] != expected_hash:
        raise RuntimeError("连接配置与本地代码承诺及签名公钥不匹配")
    source = Path(local["source"])

    # Local source is executed only on the developer's own machine.
    def check_source():
        if (
            hashlib.sha256(
                bytes.fromhex(local["salt"]) + source.read_bytes()
            ).hexdigest()
            != local["code_commitment"]
        ):
            raise RuntimeError("本地源码已修改，请登记新版本后再运行")

    check_source()
    strategy = runpy.run_path(str(source))["decide"]
    endpoint = config["api_url"].rstrip("/") + "/api/v1/private-runner/signals"
    parsed = urlparse(endpoint)
    local_endpoint = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if not local_endpoint and parsed.scheme != "https":
        raise RuntimeError("远程平台连接必须使用HTTPS")
    with (
        httpx.Client(timeout=20) as client,
        httpx.Client(timeout=20, trust_env=not local_endpoint) as platform,
    ):
        step = 0
        while args.continuous or step < args.steps:
            check_source()
            try:
                response = client.get(
                    "https://api.binance.com/api/v3/ticker/bookTicker",
                    params={"symbol": "BTCUSDT"},
                    headers={"Cache-Control": "no-cache"},
                )
                response.raise_for_status()
            except httpx.HTTPError:
                if not args.continuous:
                    raise
                print("行情读取暂不可用，30秒后重新获取；本轮没有发送信号。", flush=True)
                time.sleep(30)
                continue
            target = str(strategy({"step": step, "book": response.json()}))
            payload = {
                "domain": "atlas.private-decision/v1",
                "run_id": config["run_id"],
                "release_id": config["release_id"],
                "content_hash": config["content_hash"],
                "nonce": uuid4().hex,
                "issued_at": time.time(),
                "target": target,
            }
            payload["signature"] = key.sign(canonical(payload)).hex()
            result = platform.post(endpoint, json=payload)
            if not result.is_success:
                raise RuntimeError(
                    f"平台拒绝本次信号（HTTP {result.status_code}），已停止，不重试成交"
                )
            if not result.json().get("accepted"):
                raise RuntimeError("本次信号未执行，已停止；请检查实例状态")
            print(
                f"{step + 1}/{'持续' if args.continuous else args.steps}：签名信号已接收，目标仓位 {target}",
                flush=True,
            )
            step += 1
            if args.continuous or step < args.steps:
                time.sleep(args.interval)
    print(
        "本地执行结束。请在策略交易核对成交和仓位；没有新信号时平台不会自行执行策略。"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--strategy", type=Path, required=True)
    init.add_argument("--directory", type=Path, required=True)
    init.add_argument("--name", default="私有本地测试策略")
    execute = sub.add_parser("run")
    execute.add_argument("--directory", type=Path, required=True)
    execute.add_argument("--config", type=Path, required=True)
    execute.add_argument("--continuous", action="store_true", help="持续运行直到手动停止或发生异常；仅适用于平台模拟")
    execute.add_argument("--steps", type=int, choices=range(1, 101), default=12)
    execute.add_argument("--interval", type=int, choices=range(10, 3601), default=12)
    args = parser.parse_args()
    initialize(args) if args.command == "init" else run(args)
