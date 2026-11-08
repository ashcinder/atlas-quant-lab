"""Immutable public/private objects; the root may be an object-storage mount.

Only public objects have CDN URLs. Private objects always require application
authorization; their keys alone are never download credentials.
"""
import hashlib
import json
import os
import re
import tempfile
import subprocess
from pathlib import Path

from app.config import DATA_DIR


def canonical_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class ComputeObjects:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(os.environ.get("ATLAS_OBJECT_ROOT", str(DATA_DIR / "objects")))
        for visibility in ("public", "private"):
            (self.root / visibility).mkdir(mode=0o700, parents=True, exist_ok=True)

    def path(self, visibility: str, digest: str) -> Path:
        if visibility not in {"public", "private"} or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("无效对象标识")
        return self.root / visibility / f"{digest}.json"

    def put(self, visibility: str, value) -> str:
        body = canonical_bytes(value)
        if len(body) > 16 * 1024 * 1024:
            raise ValueError("结果对象超过16MiB")
        digest = hashlib.sha256(body).hexdigest()
        destination = self.path(visibility, digest)
        if destination.exists():
            self.read(visibility, digest)
            self._publish_public(visibility, destination)
            return digest
        fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".publishing-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
        self._publish_public(visibility, destination)
        return digest

    def _publish_public(self, visibility: str, path: Path) -> None:
        destination = os.environ.get("ATLAS_PUBLIC_S3_URI", "")
        if visibility != "public" or not destination:
            return
        if not re.fullmatch(r"s3://[a-zA-Z0-9.-]+(?:/[a-zA-Z0-9_./-]*)?", destination):
            raise ValueError("公共对象存储地址必须是明确的 s3://bucket/prefix")
        command = ["aws"]
        endpoint = os.environ.get("ATLAS_S3_ENDPOINT_URL")
        if endpoint:
            if not endpoint.startswith("https://"):
                raise ValueError("对象存储端点需要HTTPS")
            command.extend(["--endpoint-url", endpoint])
        command.extend(["s3", "cp", str(path), f"{destination.rstrip('/')}/{path.name}",
                        "--content-type", "application/json", "--cache-control", "public,max-age=31536000,immutable", "--only-show-errors"])
        # Only an explicitly configured publisher invokes AWS CLI. API readers do
        # not call this method; credentials are supplied by deployment, never code.
        try:
            subprocess.run(command, check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            raise ValueError("公共对象上传失败，未发布新数据清单") from None

    def read(self, visibility: str, digest: str):
        body = self.path(visibility, digest).read_bytes()
        if len(body) > 16 * 1024 * 1024 or hashlib.sha256(body).hexdigest() != digest:
            raise ValueError("存储对象完整性检查失败")
        return json.loads(body)

    def public_url(self, digest: str) -> str:
        self.path("public", digest)
        prefix = os.environ.get("ATLAS_PUBLIC_DATA_URL", "/api/v1/market/files").rstrip("/")
        return f"{prefix}/{digest}.json"
