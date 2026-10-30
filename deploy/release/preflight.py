#!/usr/bin/env python3
"""Fail-closed checks for the offline linux/amd64 laboratory release."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import platform
import shutil
import socket
import subprocess
import re
from pathlib import Path

EXPECTED_VERIFIER_SHA256 = "b62a2d6ed3dd49e0f02762f8291aab2f075c4f0686290844113779d797d582b3"
EXPECTED_IMAGE_ID = "02b08452a95d405b82b52dd475fc448639da4465123324711b369d7e18c27cd4"
PROFILE = "atlas_program_backtest_risc0_v2"
MIN_FREE_BYTES = 2 * 1024**3
REPO = Path(__file__).resolve().parents[2]


def run(*command: str) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in values:
            raise ValueError(f"{path}:{number}: invalid or duplicate key {key!r}")
        values[key] = value.strip().strip("'").strip('"')
    return values


def required(values: dict[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} must be set")
    return value


def compose_files(values: dict[str, str]) -> list[str]:
    files = ["-f", str(REPO / "compose.release.yaml")]
    if values.get("ATLAS_CHAIN_MODE") == "isolated_lab":
        files.extend(["-f", str(REPO / "compose.chain.yaml")])
    return files


def validate_chain(values: dict[str, str]) -> None:
    if values.get("ATLAS_CHAIN_MODE") != "isolated_lab":
        raise ValueError("ATLAS_CHAIN_MODE must be empty or isolated_lab")
    if required(values, "QUANTJUDGE_SUPERVISOR_RPC_URL") != "http://supervisor:42515":
        raise ValueError("isolated chain RPC must address the private supervisor service")
    for key in ("ATLAS_SUPERVISOR_PAYER_ADDRESS", "ATLAS_SUPERVISOR_RECIPIENT_ADDRESS", "ATLAS_SUPERVISOR_FEE_ADDRESS", "TRINE_PROOF_RECIPIENT"):
        value = required(values, key)
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", value) or int(value, 16) == 0:
            raise ValueError(f"{key} must be a nonzero test-chain address")
    roles=[values[key].lower() for key in ("ATLAS_SUPERVISOR_PAYER_ADDRESS", "ATLAS_SUPERVISOR_RECIPIENT_ADDRESS", "ATLAS_SUPERVISOR_FEE_ADDRESS")]
    if len(set(roles))!=3 or values['TRINE_PROOF_RECIPIENT'].lower()!=roles[1]:
        raise ValueError("test-chain addresses must be distinct and Proof recipient must match chain recipient")
    from decimal import Decimal
    price = required(values, "TRINE_PROOF_PRICE_BKC")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,18})?", price) or Decimal(price) <= 0:
        raise ValueError("test-chain Proof price must be positive")
    directory = Path(required(values, "ATLAS_CHAIN_SECRETS_DIR"))
    if not directory.is_absolute() or not directory.is_dir() or directory.stat().st_mode & 0o077:
        raise ValueError("chain secrets directory must be absolute and mode 0700")
    for name in ("mysql-password", "mysql-root-password"):
        path = directory / name
        if not path.is_file() or path.stat().st_mode & 0o077 or path.stat().st_size < 32:
            raise ValueError(f"{name} must be a private, initialized secret file")
    wallet_path=directory/'wallet.json'
    if not wallet_path.is_file() or wallet_path.stat().st_mode & 0o077:
        raise ValueError("test wallet must exist as a private file")
    wallet=json.loads(wallet_path.read_text())
    if wallet.get('chainId')!=1051 or wallet.get('testOnly') is not True:
        raise ValueError("wallet must be for isolated test chain 1051")
    if [wallet.get(role,{}).get('address','').lower() for role in ('payer','recipient','feeSink')]!=roles:
        raise ValueError("wallet addresses do not match the chain configuration")
    if not re.fullmatch(r'0x[0-9a-fA-F]{64}',wallet.get('payer',{}).get('privateKey','')):
        raise ValueError("test payer signing key is unavailable")
    ip = ipaddress.ip_address(required(values, "ATLAS_SUPERVISOR_IP"))
    subnet = ipaddress.ip_network(required(values, "ATLAS_NETWORK_SUBNET"))
    reserved = {ipaddress.ip_address(required(values, key)) for key in ("ATLAS_NETWORK_GATEWAY", "ATLAS_API_IP", "ATLAS_WEB_IP", "ATLAS_TLS_PROXY_IP")}
    if ip not in subnet or ip in reserved or ip in (subnet.network_address, subnet.broadcast_address):
        raise ValueError("Supervisor must have a unique usable address in the deployment subnet")


def validate_config(values: dict[str, str]) -> None:
    domain = required(values, "ATLAS_DOMAIN")
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", domain):
        raise ValueError("ATLAS_DOMAIN must be a hostname or IPv4 address without a port")
    if domain == "atlas.example.com" or ".example." in domain or domain.endswith(".example.com"):
        raise ValueError("ATLAS_DOMAIN still contains an example value")
    https_port = int(required(values, "ATLAS_HTTPS_PORT"))
    origin = f"https://{domain}" + (f":{https_port}" if https_port != 443 else "")
    if required(values, "ATLAS_ALLOWED_ORIGINS") != origin:
        raise ValueError("ATLAS_ALLOWED_ORIGINS must be the single HTTPS deployment origin")
    if values.get("ATLAS_ALLOW_REGISTRATION", "").lower() != "false":
        raise ValueError("ATLAS_ALLOW_REGISTRATION must be false")
    if values.get("ATLAS_COOKIE_SECURE", "").lower() != "true":
        raise ValueError("ATLAS_COOKIE_SECURE must be true")
    if values.get("VITE_TRINE_DEMO_MODE", "").lower() != "false":
        raise ValueError("VITE_TRINE_DEMO_MODE must be false")
    if values.get("VITE_TRINE_TEST_PRIVATE_KEY", ""):
        raise ValueError("VITE_TRINE_TEST_PRIVATE_KEY must be empty")
    if values.get("ATLAS_CHAIN_MODE"):
        validate_chain(values)
    elif values.get("TRINE_PROOF_PRICE_BKC", "") or values.get("TRINE_PROOF_RECIPIENT", ""):
        raise ValueError("paid Proof must remain disabled in this release")
    secret = values.get("ATLAS_SESSION_SECRET", "")
    if secret and len(secret) < 32:
        raise ValueError("ATLAS_SESSION_SECRET must be empty or at least 32 characters")

    subnet = ipaddress.ip_network(required(values, "ATLAS_NETWORK_SUBNET"))
    gateway = ipaddress.ip_address(required(values, "ATLAS_NETWORK_GATEWAY"))
    api_ip = ipaddress.ip_address(required(values, "ATLAS_API_IP"))
    web_ip = ipaddress.ip_address(required(values, "ATLAS_WEB_IP"))
    tls_ip = ipaddress.ip_address(required(values, "ATLAS_TLS_PROXY_IP"))
    if subnet.version != 4 or any(ip not in subnet for ip in (gateway, api_ip, web_ip, tls_ip)):
        raise ValueError("gateway, API, Web and TLS proxy IPs must be in the IPv4 subnet")
    if any(ip in (subnet.network_address, subnet.broadcast_address) for ip in (gateway, api_ip, web_ip)):
        raise ValueError("network and broadcast addresses cannot be assigned")
    if len({gateway, api_ip, web_ip}) != 3 or tls_ip != gateway:
        raise ValueError("gateway/API/Web must be unique and TLS proxy IP must equal the gateway")
    if required(values, "ATLAS_TRUSTED_PROXY_IPS") != str(web_ip):
        raise ValueError("ATLAS_TRUSTED_PROXY_IPS must contain only ATLAS_WEB_IP")

    for name in ("ATLAS_HTTP_PORT", "ATLAS_HTTPS_PORT"):
        port = int(required(values, name))
        if not 1 <= port <= 65535:
            raise ValueError(f"{name} is outside 1..65535")
    for name in ("ATLAS_TLS_CERT_FILE", "ATLAS_TLS_KEY_FILE"):
        value = required(values, name)
        if not re.fullmatch(r"/[A-Za-z0-9_./-]+", value) or not Path(value).is_file():
            raise ValueError(f"{name} does not point to a file")


def inspect_images(values: dict[str, str]) -> None:
    manifest_path = REPO / 'release-manifest.json'
    expected = json.loads(manifest_path.read_text())['images'] if manifest_path.exists() else None
    keys = {"ATLAS_API_IMAGE": "api", "ATLAS_WEB_IMAGE": "web"}
    if values.get("ATLAS_CHAIN_MODE") == "isolated_lab":
        keys.update(ATLAS_SUPERVISOR_IMAGE="supervisor", ATLAS_MYSQL_IMAGE="mysql")
    for name, component in keys.items():
        image = required(values, name)
        details = json.loads(run("docker", "image", "inspect", image))[0]
        if details.get("Os") != "linux" or details.get("Architecture") != "amd64":
            raise ValueError(f"{image} is not linux/amd64")
        if expected:
            record = expected[component]
            if image != record['name'] or details.get('Id') != record['id']:
                raise ValueError(f"{name} does not match the reviewed release manifest")

    api_image = required(values, "ATLAS_API_IMAGE")
    script = (
        "import hashlib,json,subprocess;"
        "p='/app/strategy/zkvm/target/release/atlas-zkvm';"
        f"assert hashlib.sha256(open(p,'rb').read()).hexdigest()=='{EXPECTED_VERIFIER_SHA256}';"
        f"d=json.loads(subprocess.check_output([p,'profile','--profile','{PROFILE}']));"
        f"assert d['image_id']=='{EXPECTED_IMAGE_ID}'"
    )
    run("docker", "run", "--rm", "--platform", "linux/amd64", "--entrypoint", "python", api_image, "-c", script)
    if values.get("ATLAS_CHAIN_MODE") == "isolated_lab":
        secret = str(Path(required(values, "ATLAS_CHAIN_SECRETS_DIR")) / "mysql-password")
        run("docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none", "--read-only", "--user", "101:101", "--entrypoint", "test", "-v", secret + ":/run/db-password:ro", required(values, "ATLAS_SUPERVISOR_IMAGE"), "-r", "/run/db-password")
        wallet=str(Path(required(values,"ATLAS_CHAIN_SECRETS_DIR"))/'wallet.json')
        code="const {Wallet}=require('ethers');const w=JSON.parse(require('fs').readFileSync('/run/wallet.json'));if(new Wallet(w.payer.privateKey).address.toLowerCase()!==w.payer.address.toLowerCase())process.exit(1)"
        run("docker","run","--rm","--platform","linux/amd64","--network","none","--read-only","--user","0:0","--entrypoint","node","-w","/app/contracts","-v",wallet+":/run/wallet.json:ro",api_image,"-e",code)


def inspect_networks(values: dict[str, str]) -> None:
    expected = ipaddress.ip_network(required(values, "ATLAS_NETWORK_SUBNET"))
    project = values.get("COMPOSE_PROJECT_NAME", "atlas-quant-lab")
    allowed_name = f"{project}_atlas-internal"
    identifiers = run("docker", "network", "ls", "--quiet").splitlines()
    if not identifiers:
        return
    for record in json.loads(run("docker", "network", "inspect", *identifiers)):
        if record.get("Name") == allowed_name:
            continue
        for config in record.get("IPAM", {}).get("Config", []):
            subnet = config.get("Subnet")
            if subnet and ipaddress.ip_network(subnet).overlaps(expected):
                raise ValueError(f"Docker network {record.get('Name')} overlaps {expected}")


def inspect_volume(values: dict[str, str]) -> None:
    project = values.get("COMPOSE_PROJECT_NAME", "atlas-quant-lab")
    volume = f"{project}_atlas-data"
    try:
        run("docker", "volume", "inspect", volume)
    except subprocess.CalledProcessError:
        return
    image = required(values, "ATLAS_API_IMAGE")
    owner = run(
        "docker", "run", "--rm", "--user", "0:0", "--entrypoint", "stat",
        "-v", f"{volume}:/data:ro", image, "-c", "%u:%g", "/data",
    )
    if owner != "10001:10001":
        raise ValueError(f"{volume} owner is {owner}, expected 10001:10001")


def check_http_port(values: dict[str, str]) -> None:
    project = values.get("COMPOSE_PROJECT_NAME", "atlas-quant-lab")
    running = run(
        "docker", "compose", "--env-file", str(ARGS.env_file),
        *compose_files(values), "-p", project, "ps", "--quiet",
    )
    if running:
        return
    port = int(required(values, "ATLAS_HTTP_PORT"))
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise ValueError(f"ATLAS_HTTP_PORT {port} is unavailable: {exc}") from exc


def main() -> int:
    values = read_env(ARGS.env_file)
    validate_config(values)
    os.environ.update(values)
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise ValueError("release server must be Linux amd64")
    if shutil.disk_usage(REPO).free < MIN_FREE_BYTES:
        raise ValueError("less than 2 GiB free disk space")
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        memory[key] = int(value.strip().split()[0]) * 1024
    minimum = 8 if values.get('ATLAS_CHAIN_MODE') == 'isolated_lab' else 2.25
    if memory.get('MemAvailable', 0) < int(minimum * 1024**3):
        raise ValueError(f"less than {minimum} GiB available RAM for this release profile")
    run("docker", "info", "--format", "{{.ServerVersion}}")
    run(
        "docker", "compose", "--env-file", str(ARGS.env_file),
        *compose_files(values), "config", "--quiet",
    )
    inspect_images(values)
    inspect_networks(values)
    inspect_volume(values)
    check_http_port(values)
    print("preflight passed: linux/amd64 images, verifier, config, network, volume and port")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    ARGS = parser.parse_args()
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise SystemExit(f"preflight failed: {exc}") from exc
