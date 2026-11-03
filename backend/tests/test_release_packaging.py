import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile


ROOT = Path(__file__).resolve().parents[2]
IMAGES = {
    "api": "registry.test/atlas/api:custom-api",
    "web": "registry.test/atlas/web:custom-web",
    "supervisor": "registry.test/atlas/supervisor:custom-supervisor",
    "mysql": "registry.test/atlas/mysql:custom-mysql",
}
IMAGE_IDS = {
    component: "sha256:" + digit * 64
    for component, digit in zip(IMAGES, "1234")
}


def write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def fake_commands(tmp_path: Path, fingerprint: str) -> tuple[Path, Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_log = tmp_path / "docker.jsonl"
    openssl_log = tmp_path / "openssl.log"
    write_executable(
        bin_dir / "docker",
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
with Path(os.environ["FAKE_DOCKER_LOG"]).open("a") as stream:
    stream.write(json.dumps(args) + "\\n")
images = json.loads(os.environ["FAKE_IMAGES"])
ids = json.loads(os.environ["FAKE_IMAGE_IDS"])
by_name = {name: component for component, name in images.items()}

if args[:2] == ["image", "inspect"]:
    name = args[-1]
    component = by_name[name]
    if "--format" in args:
        template = args[args.index("--format") + 1]
        if ".Os" in template:
            print("linux/amd64")
        elif "source-snapshot" in template:
            print(os.environ["FAKE_SOURCE_FINGERPRINT"])
        elif ".Id" in template:
            print(ids[component])
        else:
            raise SystemExit("unexpected inspect format: " + template)
    else:
        print(json.dumps([{
            "Id": ids[component],
            "Os": "linux",
            "Architecture": "amd64",
            "Config": {"Labels": {
                "org.atlas.source-snapshot": os.environ["FAKE_SOURCE_FINGERPRINT"],
                "org.atlas.supervisor.binary-sha256": "b" * 64,
            }},
        }]))
elif args and args[0] == "save":
    sys.stdout.buffer.write(b"mock image archive")
elif args and args[0] == "run":
    if "./create-wallet.mjs" in args:
        mount = next(args[index + 1] for index, value in enumerate(args) if value == "--volume" and args[index + 1].endswith(":/out"))
        output = Path(mount.removesuffix(":/out")) / "wallet.json"
        output.write_text(json.dumps({
            "chainId": 1051,
            "testOnly": True,
            "payer": {"address": "0x" + "1" * 40, "privateKey": "0x" + "a" * 64},
            "recipient": {"address": "0x" + "2" * 40},
            "feeSink": {"address": "0x" + "3" * 40},
        }))
else:
    raise SystemExit("unexpected docker command: " + repr(args))
""",
    )
    write_executable(
        bin_dir / "openssl",
        """#!/usr/bin/env python3
import os
from pathlib import Path
with Path(os.environ["FAKE_OPENSSL_LOG"]).open("a") as stream:
    stream.write("rand\\n")
print("f" * 64)
""",
    )
    return bin_dir, docker_log, openssl_log


def command_env(bin_dir: Path, docker_log: Path, openssl_log: Path, fingerprint: str):
    env = os.environ.copy()
    env.update(
        PATH=str(bin_dir) + os.pathsep + env["PATH"],
        FAKE_DOCKER_LOG=str(docker_log),
        FAKE_OPENSSL_LOG=str(openssl_log),
        FAKE_SOURCE_FINGERPRINT=fingerprint,
        FAKE_IMAGES=json.dumps(IMAGES),
        FAKE_IMAGE_IDS=json.dumps(IMAGE_IDS),
        ATLAS_CHAIN_MODE="isolated_lab",
        ATLAS_API_IMAGE=IMAGES["api"],
        ATLAS_WEB_IMAGE=IMAGES["web"],
        ATLAS_SUPERVISOR_IMAGE=IMAGES["supervisor"],
        ATLAS_MYSQL_IMAGE=IMAGES["mysql"],
    )
    return env


def test_custom_four_image_package_and_manifest_bound_chain_initialization(tmp_path):
    fingerprint = json.loads(
        subprocess.run(
            [sys.executable, str(ROOT / "deploy/release/source-manifest.py")],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )["snapshot_sha256"]
    bin_dir, docker_log, openssl_log = fake_commands(tmp_path, fingerprint)
    env = command_env(bin_dir, docker_log, openssl_log, fingerprint)
    archive = tmp_path / "release.tar.gz"
    subprocess.run(
        ["bash", str(ROOT / "deploy/release/package-release.sh"), str(archive)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    extracted = tmp_path / "extracted"
    extracted.mkdir()
    with tarfile.open(archive) as release:
        release.extractall(extracted, filter="data")
    bundle = extracted / "atlas-quant-lab-release"
    manifest = json.loads((bundle / "release-manifest.json").read_text())
    for component, name in IMAGES.items():
        assert manifest["images"][component] == {
            "name": name,
            "id": IMAGE_IDS[component],
            **({"binary_sha256": "b" * 64} if component == "supervisor" else {}),
        }
    assert manifest["chain"]["minimum_total_ram_gib"] == 7.5
    assert manifest["chain"]["minimum_available_ram_gib"] == 7
    assert f'ATLAS_API_IMAGE={IMAGES["api"]}' in (bundle / ".env.lab.example").read_text()
    assert f'ATLAS_WEB_IMAGE={IMAGES["web"]}' in (bundle / ".env.lab.example").read_text()
    assert f'ATLAS_SUPERVISOR_IMAGE={IMAGES["supervisor"]}' in (bundle / ".env.chain.lab.example").read_text()
    assert f'ATLAS_MYSQL_IMAGE={IMAGES["mysql"]}' in (bundle / ".env.chain.lab.example").read_text()

    init_env = env.copy()
    for key in (
        "ATLAS_API_IMAGE", "ATLAS_WEB_IMAGE", "ATLAS_SUPERVISOR_IMAGE", "ATLAS_MYSQL_IMAGE"
    ):
        init_env.pop(key)
    docker_log.write_text("")
    secrets = tmp_path / "secrets"
    subprocess.run(
        ["bash", str(bundle / "deploy/chain/init-secrets.sh"), str(secrets)],
        check=True,
        capture_output=True,
        text=True,
        env=init_env,
    )
    chain_env = (secrets / "chain.env").read_text()
    assert f'ATLAS_API_IMAGE={IMAGES["api"]}' in chain_env
    assert f'ATLAS_SUPERVISOR_IMAGE={IMAGES["supervisor"]}' in chain_env
    assert f'ATLAS_MYSQL_IMAGE={IMAGES["mysql"]}' in chain_env
    calls = [json.loads(line) for line in docker_log.read_text().splitlines()]
    wallet_call = next(call for call in calls if "./create-wallet.mjs" in call)
    assert IMAGES["api"] in wallet_call

    openssl_calls = openssl_log.read_text()
    mismatched_env = init_env | {"ATLAS_API_IMAGE": "registry.test/atlas/api:unreviewed"}
    rejected = subprocess.run(
        ["bash", str(bundle / "deploy/chain/init-secrets.sh"), str(tmp_path / "mismatch")],
        capture_output=True,
        text=True,
        env=mismatched_env,
    )
    assert rejected.returncode != 0
    assert "does not match release manifest" in rejected.stderr
    assert openssl_log.read_text() == openssl_calls

    manifest["platform"] = "linux/arm64"
    (bundle / "release-manifest.json").write_text(json.dumps(manifest))
    rejected = subprocess.run(
        ["bash", str(bundle / "deploy/chain/init-secrets.sh"), str(tmp_path / "bad-manifest")],
        capture_output=True,
        text=True,
        env=init_env,
    )
    assert rejected.returncode != 0
    assert "platform must be linux/amd64" in rejected.stderr
    assert openssl_log.read_text() == openssl_calls


def test_source_tree_initialization_still_accepts_explicit_image_overrides(tmp_path):
    bin_dir, docker_log, openssl_log = fake_commands(tmp_path, "a" * 64)
    env = command_env(bin_dir, docker_log, openssl_log, "a" * 64)
    source_root = tmp_path / "source"
    script = source_root / "deploy/chain/init-secrets.sh"
    script.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "deploy/chain/init-secrets.sh", script)
    secrets = tmp_path / "source-secrets"
    subprocess.run(
        ["bash", str(script), str(secrets)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    chain_env = (secrets / "chain.env").read_text()
    assert f'ATLAS_API_IMAGE={IMAGES["api"]}' in chain_env
    assert f'ATLAS_SUPERVISOR_IMAGE={IMAGES["supervisor"]}' in chain_env
    assert f'ATLAS_MYSQL_IMAGE={IMAGES["mysql"]}' in chain_env
