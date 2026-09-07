"""Operator-owned container launcher. Never import uploaded code in this process.

gVisor is mandatory. This protects the platform, NOT secrets from its operator.
No automatic fallback to host Python or a weaker OCI runtime is permitted.
"""

from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import subprocess
import tempfile
import time
import zipfile
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from app.strategy_studio import inspect_strategy_package


class RunnerUnavailable(RuntimeError):
    pass


class RunnerFailure(ValueError):
    pass


class DockerSandbox:
    """One stateful process per run; only past bars cross the JSONL channel."""

    def __init__(self, archive: bytes, parameters: dict):
        self.archive, self.parameters = archive, parameters
        self.name = "atlas-run-" + uuid4().hex
        self.process = None
        self.directory = None
        self.buffer = bytearray()
        self.deadline = time.monotonic() + 180
        self.docker = shutil.which("docker")
        self.socket = os.environ.get("ATLAS_RUNNER_SOCKET", "/var/run/docker.sock")
        self.image = os.environ.get("ATLAS_RUNNER_IMAGE", "")

    def _command(self, *args: str) -> list[str]:
        if not self.docker or not Path(self.socket).is_socket():
            raise RunnerUnavailable("独立 gVisor Runner 的本地 Docker socket 未就绪")
        return [self.docker, "--host", "unix://" + self.socket, *args]

    @staticmethod
    def environment() -> dict[str, str]:
        # No developer keys, cloud credentials, Docker remote endpoints or proxy env.
        return {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}

    def __enter__(self):
        if os.environ.get("ATLAS_RUNNER_ENABLED") != "1":
            raise RunnerUnavailable("Python 隔离执行默认关闭；需部署独立 gVisor Runner")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.image):
            raise RunnerUnavailable("Runner 镜像必须固定为本地 sha256 image ID")
        try:
            info = subprocess.run(
                self._command("info", "--format", "{{json .Runtimes}}"),
                capture_output=True,
                timeout=5,
                env=self.environment(),
            )
            runtimes = json.loads(info.stdout) if not info.returncode else {}
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise RunnerUnavailable("隔离执行服务不可用；不会降级执行") from exc
        if not isinstance(runtimes, dict) or "runsc" not in runtimes:
            raise RunnerUnavailable("未安装 gVisor runsc；不会降级为宿主机执行")
        inspection = inspect_strategy_package(self.archive)
        if inspection.manifest.language != "python":
            raise RunnerFailure("此执行器仅接受 atlas.strategy/v1 Python 策略包")
        self.directory = tempfile.TemporaryDirectory(prefix="atlas-private-run-")
        root = Path(self.directory.name) / "package"
        root.mkdir(mode=0o755)
        try:
            # Inspection has rejected traversal, duplicate paths and symlinks.
            with zipfile.ZipFile(BytesIO(self.archive)) as archive:
                for member in archive.infolist():
                    if not member.is_dir():
                        archive.extract(member, root)
            # Private ancestor stays 0700; only the mounted directory is visible in guest.
            os.chmod(root, 0o755)
            for path in root.rglob("*"):
                os.chmod(path, 0o755 if path.is_dir() else 0o444)
            command = self._command(
                "run",
                "--rm",
                "-i",
                "--name",
                self.name,
                "--pull=never",
                "--runtime=runsc",
                "--network=none",
                "--read-only",
                "--user=65532:65532",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=32",
                "--memory=512m",
                "--memory-swap=512m",
                "--cpus=1",
                "--ulimit=nofile=64:64",
                "--ulimit=core=0:0",
                "--log-driver=none",
                "--tmpfs=/tmp:rw,noexec,nosuid,size=32m",
                "--mount",
                f"type=bind,src={root},dst=/strategy,readonly",
                self.image,
            )
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                env=self.environment(),
            )
            self.exchange(
                {
                    "kind": "init",
                    "entrypoint": inspection.manifest.entrypoint,
                    "parameters": self.parameters,
                }
            )
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def exchange(self, payload: dict) -> dict:
        if not self.process or self.process.poll() is not None:
            raise RunnerFailure("策略执行器已退出")
        request_id = uuid4().hex
        message = (
            json.dumps({**payload, "request_id": request_id}, allow_nan=False).encode() + b"\n"
        )
        if len(message) > 2_000_000:
            raise RunnerFailure("策略上下文超出大小限制")
        limit = min(self.deadline, time.monotonic() + 10)
        # Both directions are non-blocking: a strategy may stop reading stdin.
        with selectors.DefaultSelector() as selector:
            os.set_blocking(self.process.stdin.fileno(), False)
            os.set_blocking(self.process.stdout.fileno(), False)
            selector.register(self.process.stdin, selectors.EVENT_WRITE)
            selector.register(self.process.stdout, selectors.EVENT_READ)
            sent = 0
            while b"\n" not in self.buffer:
                remaining = limit - time.monotonic()
                if remaining <= 0:
                    raise RunnerFailure("策略执行超过单步或总时限")
                for key, _ in selector.select(remaining):
                    if key.fileobj is self.process.stdin:
                        try:
                            sent += os.write(key.fd, message[sent : sent + 65536])
                        except BrokenPipeError as exc:
                            raise RunnerFailure("策略提前关闭输入通道") from exc
                        if sent == len(message):
                            selector.unregister(self.process.stdin)
                    else:
                        chunk = os.read(key.fd, 8192)
                        if not chunk:
                            raise RunnerFailure("策略未返回完整响应")
                        self.buffer.extend(chunk)
                        if len(self.buffer) > 65536:
                            raise RunnerFailure("策略输出超出大小限制")
        line, _, rest = self.buffer.partition(b"\n")
        self.buffer = bytearray(rest)
        try:
            result = json.loads(line)
        except (ValueError, UnicodeDecodeError) as exc:
            raise RunnerFailure("策略未返回有效 JSON 响应") from exc
        if not isinstance(result, dict) or result.get("request_id") != request_id:
            raise RunnerFailure("策略响应与请求不匹配")
        if result.get("ok") is not True:
            raise RunnerFailure("策略运行失败；私密异常内容不会写入公共日志")
        return result

    def __exit__(self, *_):
        try:
            if self.process:
                try:
                    self._remove_container()
                finally:
                    if self.process.poll() is None:
                        self.process.kill()
                    self.process.wait(timeout=5)
                    self.process.stdin.close()
                    self.process.stdout.close()
        finally:
            if self.directory:
                self.directory.cleanup()

    def _remove_container(self):
        try:
            subprocess.run(
                self._command("rm", "--force", self.name),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                env=self.environment(),
                check=False,
            )
        except (RunnerUnavailable, OSError, subprocess.SubprocessError) as exc:
            # Do not silently report successful cleanup when Docker is unavailable.
            raise RunnerUnavailable("执行器清理失败；需检查隔离主机残留容器") from exc
