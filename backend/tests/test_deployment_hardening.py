from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = spec_from_file_location("deployment_preflight", ROOT / "deploy/release/preflight.py")
preflight = module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


def release_config(tmp_path: Path) -> dict[str, str]:
    values = preflight.read_env(ROOT / ".env.lab.example")
    cert = tmp_path / "fullchain.pem"
    key = tmp_path / "private-key.pem"
    cert.write_text("certificate placeholder")
    key.write_text("private key placeholder")
    key.chmod(0o600)
    backup = tmp_path / "backups"
    backup.mkdir()
    values.update(
        ATLAS_DOMAIN="lab.test",
        ATLAS_ALLOWED_ORIGINS="https://lab.test:9443",
        ATLAS_HTTPS_PORT="9443",
        ATLAS_TLS_CERT_FILE=str(cert),
        ATLAS_TLS_KEY_FILE=str(key),
        ATLAS_BACKUP_DIR=str(backup),
    )
    return values


def manifest(image_suffix: str = "1") -> dict:
    image_id = "sha256:" + image_suffix * 64
    return {
        "schema": "atlas.quantjudge.offline-release.v1",
        "platform": "linux/amd64",
        "source_snapshot": {"snapshot_sha256": "a" * 64},
        "images": {
            "api": {"name": "api:reviewed", "id": image_id},
            "web": {"name": "web:reviewed", "id": "sha256:" + "2" * 64},
        },
        "verifier": {
            "sha256": preflight.EXPECTED_VERIFIER_SHA256,
            "profile": preflight.PROFILE,
            "image_id": preflight.EXPECTED_IMAGE_ID,
        },
    }


@pytest.mark.parametrize(
    ("port", "origin"), (("443", "https://lab.test"), ("9443", "https://lab.test:9443"))
)
def test_tls_template_uses_validated_origin_and_preserves_request_uri(tmp_path, port, origin):
    values = release_config(tmp_path)
    values.update(ATLAS_HTTPS_PORT=port, ATLAS_ALLOWED_ORIGINS=origin)
    env_file = tmp_path / "release.env"
    env_file.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    output = tmp_path / "nginx.conf"
    subprocess.run(
        [sys.executable, str(ROOT / "deploy/release/render-tls-proxy.py"),
         "--env-file", str(env_file), "--output", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    rendered = output.read_text()
    assert f"return 301 {origin}$request_uri;" in rendered
    assert "proxy_set_header Host lab.test;" in rendered
    assert "$host$request_uri" not in rendered


def test_tls_preflight_checks_lifetime_san_chain_key_and_nginx(tmp_path, monkeypatch):
    values = release_config(tmp_path)
    nginx = tmp_path / "nginx.conf"
    nginx.write_text("events {}")
    values["ATLAS_NGINX_CONFIG"] = str(nginx)
    calls = []

    def run(*command):
        calls.append(command)
        return "PUBLIC KEY" if "-pubkey" in command or "-pubout" in command else ""

    monkeypatch.setattr(preflight, "run", run)
    preflight.validate_tls(values)
    assert any(command[:3] == ("openssl", "x509", "-checkend") for command in calls)
    assert any("-checkhost" in command and "lab.test" in command for command in calls)
    assert any(command[:3] == ("openssl", "verify", "-purpose") for command in calls)
    assert ("nginx", "-t", "-c", str(nginx)) in calls


def test_tls_private_key_permissions_fail_before_openssl(tmp_path, monkeypatch):
    values = release_config(tmp_path)
    Path(values["ATLAS_TLS_KEY_FILE"]).chmod(0o644)
    monkeypatch.setattr(preflight, "run", lambda *_: pytest.fail("openssl must not run"))
    with pytest.raises(ValueError, match="group or other"):
        preflight.validate_tls(values)


def test_release_backup_and_local_docker_storage_are_checked_separately(tmp_path, monkeypatch):
    values = release_config(tmp_path)
    docker_root = tmp_path / "docker-root"
    docker_root.mkdir()
    checked = []
    monkeypatch.setattr(
        preflight.shutil, "disk_usage",
        lambda path: checked.append(Path(path)) or SimpleNamespace(free=3 * 1024**3),
    )

    def run(*command):
        if command[:3] == ("docker", "context", "inspect"):
            return "unix:///var/run/docker.sock"
        if command[:3] == ("docker", "info", "--format"):
            return str(docker_root)
        if command[:3] == ("docker", "volume", "inspect"):
            raise subprocess.CalledProcessError(1, command)
        if command[:3] == ("docker", "run", "--rm"):
            return "Filesystem 1024-blocks Used Available Capacity Mounted on\nvolume 4000000 1 3999999 1% /probe"
        raise AssertionError(command)

    monkeypatch.setattr(preflight, "run", run)
    preflight.validate_local_storage(values)
    preflight.validate_docker_storage(values)
    assert preflight.REPO in checked
    assert Path(values["ATLAS_BACKUP_DIR"]) in checked
    assert docker_root in checked


def test_remote_docker_never_checks_its_root_as_a_local_path(tmp_path, monkeypatch):
    values = release_config(tmp_path)
    monkeypatch.setattr(
        preflight.shutil, "disk_usage", lambda *_: pytest.fail("no local DockerRootDir check")
    )

    def run(*command):
        if command[:3] == ("docker", "context", "inspect"):
            return "ssh://release.example"
        if command[:3] == ("docker", "volume", "inspect"):
            return "[]"
        if command[:3] == ("docker", "run", "--rm"):
            return "Filesystem 1024-blocks Used Available Capacity Mounted on\nvolume 4000000 1 3999999 1% /probe"
        raise AssertionError(command)

    monkeypatch.setattr(preflight, "run", run)
    preflight.validate_docker_storage(values)


def test_eight_gib_class_host_with_seven_gib_available_passes(capsys):
    preflight.validate_memory(
        {"MemTotal": 8_320_565_248, "MemAvailable": 7 * 1024**3}
    )
    assert "minimum test profile" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("memory", "message"),
    [
        (
            {"MemTotal": preflight.MIN_TOTAL_MEMORY_BYTES - 1,
             "MemAvailable": 7 * 1024**3},
            "8 GiB-class",
        ),
        (
            {"MemTotal": 12 * 1024**3,
             "MemAvailable": preflight.MIN_AVAILABLE_MEMORY_BYTES - 1},
            "7 GiB MemAvailable",
        ),
    ],
)
def test_memory_preflight_rejects_low_spec_or_low_headroom(memory, message):
    with pytest.raises(ValueError, match=message):
        preflight.validate_memory(memory)


def test_release_manifest_and_rollback_record_bind_exact_artifacts(tmp_path):
    values = release_config(tmp_path)
    previous = manifest("1")
    current = manifest("3")
    path = tmp_path / "previous.json"
    path.write_text(json.dumps(previous))
    assert preflight.load_release_manifest(path, values) == previous
    record = {
        "schema": "atlas.quantjudge.rollback-compatibility.v1",
        "current_api_image_id": current["images"]["api"]["id"],
        "previous_api_image_id": previous["images"]["api"]["id"],
        "schema_compatible": True,
        "verified_backup_sha256": "b" * 64,
    }
    preflight.validate_rollback_compatibility(current, previous, record)
    record["previous_api_image_id"] = "sha256:" + "4" * 64
    with pytest.raises(ValueError, match="does not bind"):
        preflight.validate_rollback_compatibility(current, previous, record)


def test_unapproved_image_tag_is_rejected_before_any_container_runs(tmp_path, monkeypatch):
    values = release_config(tmp_path)
    values.update(ATLAS_API_IMAGE="api:arbitrary", ATLAS_WEB_IMAGE="web:reviewed")
    approved = manifest("1")
    path = tmp_path / "approved.json"
    path.write_text(json.dumps(approved))
    calls = []

    def run(*command):
        calls.append(command)
        if command[:3] == ("docker", "image", "inspect"):
            return json.dumps([{
                "Os": "linux", "Architecture": "amd64",
                "Id": approved["images"]["api"]["id"],
                "Config": {"Labels": {"org.atlas.source-snapshot": "a" * 64}},
            }])
        raise AssertionError(command)

    monkeypatch.setattr(preflight, "run", run)
    with pytest.raises(ValueError, match="reviewed release manifest"):
        preflight.inspect_images(values, path)
    assert not any(command[:3] == ("docker", "run", "--rm") for command in calls)


def test_rollback_runs_explicit_previous_manifest_preflight_before_compose():
    script = (ROOT / "deploy/release/rollback-images.sh").read_text()
    assert "ENV_FILE PREVIOUS_RELEASE_MANIFEST COMPATIBILITY_RECORD" in script
    assert '"--release-manifest", str(previous_path)' in script
    assert script.index('"deploy/release/preflight.py"') < script.index('"deploy/release/compose.py"')
    assert "PREVIOUS_API_IMAGE" not in script


def test_api_compatibility_cannot_authorize_a_chain_engine_rollback():
    current, previous = manifest('1'), manifest('2')
    current['images']['supervisor']={'id':'sha256:'+'3'*64}
    previous['images']['supervisor']={'id':'sha256:'+'4'*64}
    record={'schema':'atlas.quantjudge.rollback-compatibility.v1',
            'current_api_image_id':current['images']['api']['id'],
            'previous_api_image_id':previous['images']['api']['id'],
            'schema_compatible':True,'verified_backup_sha256':'b'*64}
    with pytest.raises(ValueError,match='coordinated migration'):
        preflight.validate_rollback_compatibility(current,previous,record)


@pytest.mark.parametrize("name", ["build.sh", "start.sh"])
def test_retired_deploy_entrypoints_fail_without_invoking_docker(name):
    path = ROOT / "deploy" / name
    script = path.read_text()
    assert "docker " not in script
    result = subprocess.run(["bash", str(path)], capture_output=True, text=True)
    assert result.returncode == 2
    assert "retired" in result.stderr
