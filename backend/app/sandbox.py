"""Operator-owned container launcher. Never import uploaded code in this process.

gVisor is mandatory. This protects the platform, NOT secrets from its operator.
No automatic fallback to host Python or a weaker OCI runtime is permitted.
"""

from __future__ import annotations

import json
import math
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


class RunnerCleanupFailure(RunnerUnavailable):
    pass


PORTFOLIO_PROTOCOL = "atlas.portfolio/v1"
PORTFOLIO_CHECKPOINT_BYTES = 4 * 1024 * 1024


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
        self.input_limit = 2_000_000
        self.output_limit = 65_536
        self.memory = "512m"

    def _command(self, *args: str) -> list[str]:
        if not self.docker or not Path(self.socket).is_socket():
            raise RunnerUnavailable("独立 gVisor Runner 的本地 Docker socket 未就绪")
        return [self.docker, "--host", "unix://" + self.socket, *args]

    @staticmethod
    def environment() -> dict[str, str]:
        # No developer keys, cloud credentials, Docker remote endpoints or proxy env.
        return {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}

    def _check_runtime(self):
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

    def _init(self, entrypoint):
        self.exchange({"kind": "init", "entrypoint": entrypoint, "parameters": self.parameters})

    def _cancelled(self):
        return False

    def __enter__(self):
        self._check_runtime()
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
                f"--memory={self.memory}",
                f"--memory-swap={self.memory}",
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
            self._init(inspection.manifest.entrypoint)
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
        if len(message) > self.input_limit:
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
                if self._cancelled():
                    raise RunnerFailure("策略执行已取消")
                remaining = limit - time.monotonic()
                if remaining <= 0:
                    raise RunnerFailure("策略执行超过单步或总时限")
                for key, _ in selector.select(min(remaining, 0.2)):
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
                        if len(self.buffer) > self.output_limit:
                            raise RunnerFailure("策略输出超出大小限制")
        line, _, rest = self.buffer.partition(b"\n")
        self.buffer = bytearray(rest)
        try:
            result = json.loads(line)
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
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


class PortfolioSandbox(DockerSandbox):
    """The multi-stock wire protocol uses a separately pinned Python image."""

    def __init__(self, archive, parameters, checkpoint=None, *, save_state=True, cancelled=None):
        super().__init__(archive, parameters)
        self.socket = os.environ.get("ATLAS_RUNNER_SOCKET", "")
        self.image = os.environ.get("ATLAS_PORTFOLIO_RUNNER_IMAGE", "")
        self.memory = "1g"
        self.input_limit = PORTFOLIO_CHECKPOINT_BYTES + 262_144
        self.output_limit = PORTFOLIO_CHECKPOINT_BYTES + 65_536
        self.deadline = time.monotonic() + 600
        self.save_state = save_state
        self._checkpoint = checkpoint
        self._should_cancel = cancelled
        self.stateful = False

    def _check_runtime(self):
        if not self.socket:
            raise RunnerUnavailable("多标的策略需要配置独立 gVisor Runner 的 Docker socket")
        super()._check_runtime()
        try:
            image = subprocess.run(
                self._command("image", "inspect", "--format", "{{.Id}}", self.image),
                capture_output=True, timeout=5, env=self.environment(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RunnerUnavailable("多标的 Runner 镜像无法检查") from exc
        if image.returncode or image.stdout.decode(errors="replace").strip() != self.image:
            raise RunnerUnavailable("多标的 Runner 的固定镜像尚未安装")

    def _cancelled(self):
        return self._should_cancel is not None and self._should_cancel()

    def _init(self, entrypoint):
        response = super().exchange({
            "kind": "init", "protocol": PORTFOLIO_PROTOCOL, "entrypoint": entrypoint,
            "parameters": self.parameters, "checkpoint": self._checkpoint,
        })
        if response.get("protocol") != PORTFOLIO_PROTOCOL or type(response.get("stateful")) is not bool:
            raise RunnerUnavailable("Runner 镜像不支持多标的策略协议")
        self.stateful = response["stateful"]

    def seed_history(self, history):
        # Restore each symbol separately, keeping frames bounded even for a large stock pool.
        for symbol, rows in history.items():
            if rows:
                super().exchange({"kind": "portfolio_history", "bars": {symbol: rows}})

    def exchange(self, payload):
        response = super().exchange({**payload, "kind": "portfolio_step", "save_state": self.save_state})
        if self.stateful and self.save_state:
            if response.get("checkpoint") is None:
                raise RunnerFailure("有状态策略未返回检查点")
            checkpoint = response["checkpoint"]
            try:
                valid_size = len(json.dumps(checkpoint, allow_nan=False).encode()) <= PORTFOLIO_CHECKPOINT_BYTES
            except (ValueError, RecursionError, TypeError):
                valid_size = False
            if not valid_size:
                raise RunnerFailure("策略检查点超出 4 MiB 或含无效 JSON")
            self._checkpoint = checkpoint
        return response

    def checkpoint(self):
        return self._checkpoint


def portfolio_runner_status() -> tuple[bool, str | None]:
    try:
        PortfolioSandbox(b"", {})._check_runtime()
    except RunnerUnavailable as exc:
        return False, str(exc)
    return True, None


RQALPHA_PROTOCOL = "atlas.rqalpha/v1"
RQALPHA_REPORT_SCHEMA = "atlas.rqalpha.raw-report/v1"
RQALPHA_REPORT_TABLES = ("positions", "accounts", "benchmark")
RQALPHA_CHANNEL_BYTES = 64 * 1024 * 1024
RQALPHA_MAX_RECORDS = 250_000
RQALPHA_LOG_BYTES = 1024 * 1024
RQALPHA_MAX_LOGS = 2000


class RqalphaSandbox(DockerSandbox):
    def __init__(self, bundle: Path, *, cancelled=None):
        super().__init__(b"", {})
        self.socket = os.environ.get("ATLAS_RQALPHA_RUNNER_SOCKET", "")
        self.image = os.environ.get("ATLAS_RQALPHA_RUNNER_IMAGE", "")
        self.bundle = Path(bundle)
        self._should_cancel = cancelled
        self.input_limit = 131_072
        self.output_limit = 16 * 1024 * 1024
        self.channel_limit = RQALPHA_CHANNEL_BYTES
        self.report_logs = []
        self.logs_truncated = False
        self._report_log_bytes = 0
        self.deadline = time.monotonic() + 600

    def _attach_logs(self, exc):
        exc.report_logs = list(self.report_logs)
        exc.logs_truncated = self.logs_truncated
        return exc

    def _check_runtime(self):
        try:
            self._check_rqalpha_runtime()
        except (RunnerFailure, RunnerUnavailable) as exc:
            self._attach_logs(exc)
            raise

    def _check_rqalpha_runtime(self):
        if not self.socket:
            raise RunnerUnavailable("RQAlpha 需要配置独立 Linux gVisor 的 Docker socket")
        super()._check_runtime()
        try:
            image = subprocess.run(
                self._command("image", "inspect", "--format", "{{.Id}}", self.image),
                capture_output=True, timeout=5, env=self.environment(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RunnerUnavailable("RQAlpha 固定镜像无法检查") from exc
        if image.returncode or image.stdout.decode(errors="replace").strip() != self.image:
            raise RunnerUnavailable("RQAlpha 固定镜像尚未安装")

    def _cancelled(self):
        return self._should_cancel is not None and self._should_cancel()

    def __enter__(self):
        try:
            return self._open_rqalpha()
        except (RunnerFailure, RunnerUnavailable) as exc:
            self._attach_logs(exc)
            raise
        except OSError as exc:
            raise self._attach_logs(RunnerUnavailable("RQAlpha 隔离执行器无法启动")) from exc

    def _open_rqalpha(self):
        self._check_runtime()
        if not self.bundle.is_dir() or any(c in str(self.bundle) for c in ",\n\r"):
            raise RunnerUnavailable("RQAlpha 日线包目录未就绪")
        command = self._command(
            "run", "--rm", "-i", "--name", self.name, "--pull=never", "--runtime=runsc",
            "--network=none", "--read-only", "--user=65532:65532", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--pids-limit=32", "--memory=1g",
            "--memory-swap=1g", "--cpus=1", "--ulimit=nofile=64:64", "--ulimit=core=0:0",
            "--log-driver=none", "--tmpfs=/tmp:rw,noexec,nosuid,size=32m", "--mount",
            f"type=bind,src={self.bundle},dst=/bundle,readonly", self.image,
        )
        try:
            self.process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0, env=self.environment(),
            )
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _remove_container(self):
        try:
            removed = subprocess.run(
                self._command("rm", "--force", self.name), capture_output=True,
                timeout=10, env=self.environment(),
            )
            if removed.returncode:
                remaining = subprocess.run(
                    self._command("ps", "-a", "--filter", f"name=^/{self.name}$",
                                  "--format", "{{.Names}}"),
                    capture_output=True, timeout=5, env=self.environment(),
                )
                if remaining.returncode or remaining.stdout.strip():
                    raise self._attach_logs(RunnerCleanupFailure(
                        "RQAlpha 容器清理未确认，请检查隔离执行主机",
                    ))
        except (RunnerUnavailable, OSError, subprocess.SubprocessError) as exc:
            raise self._attach_logs(RunnerCleanupFailure(
                "RQAlpha 容器清理失败，请检查隔离执行主机",
            )) from exc

    def __exit__(self, exc_type, exc, traceback):
        if isinstance(exc, (RunnerFailure, RunnerUnavailable)):
            self._attach_logs(exc)
        try:
            return super().__exit__(exc_type, exc, traceback)
        except (RunnerFailure, RunnerUnavailable) as failure:
            self._attach_logs(failure)
            raise
        except (OSError, subprocess.SubprocessError) as failure:
            raise self._attach_logs(RunnerCleanupFailure(
                "RQAlpha 执行器清理未完成，请检查隔离主机",
            )) from failure

    def run(self, payload):
        try:
            return self._run_request(payload)
        except (RunnerFailure, RunnerUnavailable) as exc:
            self._attach_logs(exc)
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            raise self._attach_logs(RunnerFailure("RQAlpha 执行通道不可用")) from exc

    @staticmethod
    def _protocol_number(value, *, nullable=False):
        return (nullable and value is None or type(value) is int and abs(value) <= 10**18
                or type(value) is float and math.isfinite(value))

    @staticmethod
    def _invalid_constant(_):
        raise ValueError("Non-finite JSON constant")

    def _accept_log(self, row):
        if (not isinstance(row, dict) or set(row) - {
            "sequence", "time", "level", "source", "message", "line",
        } or type(row.get("sequence")) is not int
                or row["sequence"] != len(self.report_logs)
                or row.get("level") not in ("INFO", "WARN", "DEBUG", "ERROR")
                or row.get("source") not in ("strategy", "engine", "system")
                or not self._protocol_number(row.get("time"), nullable=True)
                or not isinstance(row.get("message"), str) or len(row["message"]) > 4096
                or row.get("line") is not None and (
                    type(row["line"]) is not int or not 1 <= row["line"] <= 60_000
                )):
            raise RunnerFailure("RQAlpha 日志帧无效或顺序不一致")
        try:
            size = len(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":"), allow_nan=False).encode()) + 1
        except (ValueError, UnicodeError) as exc:
            raise RunnerFailure("RQAlpha 日志文本编码无效") from exc
        if (len(self.report_logs) >= RQALPHA_MAX_LOGS
                or self._report_log_bytes + size > RQALPHA_LOG_BYTES):
            self.logs_truncated = True
            raise RunnerFailure("RQAlpha 日志超过安全限制")
        self._report_log_bytes += size
        self.report_logs.append(row)

    def _accept_rows(self, frame, tables):
        table, rows, offset = frame.get("table"), frame.get("rows"), frame.get("offset")
        if (set(frame) != {"protocol", "request_id", "event", "table", "offset", "rows"}
                or not isinstance(table, str) or table not in tables
                or not isinstance(rows, list) or not 1 <= len(rows) <= 1000
                or type(offset) is not int or offset != len(tables[table])
                or any(not isinstance(row, dict) for row in rows)):
            raise RunnerFailure("RQAlpha 报告批次缺失、重复或结构无效")
        for row in rows:
            if not self._protocol_number(row.get("time")):
                raise RunnerFailure("RQAlpha 报告日期无效")
            if table == "positions" and row.get("direction") not in ("long", None):
                raise RunnerFailure("RQAlpha 持仓方向无效")
            if table == "accounts" and row.get("account_type") != "stock":
                raise RunnerFailure("RQAlpha 账户类别无效")
            if table == "benchmark" and (not self._protocol_number(row.get("net_value"))
                                          or row["net_value"] <= 0):
                raise RunnerFailure("RQAlpha 基准净值无效")
        if sum(map(len, tables.values())) + len(rows) > RQALPHA_MAX_RECORDS:
            raise RunnerFailure("RQAlpha 报告记录超过 250,000 条限制")
        tables[table].extend(rows)

    def _report_metadata(self, report, tables):
        if (not isinstance(report, dict) or report.get("schema_version") != RQALPHA_REPORT_SCHEMA
                or type(report.get("logs_truncated")) is not bool
                or any(key in report for key in (*RQALPHA_REPORT_TABLES, "logs"))):
            raise RunnerFailure("RQAlpha 报告终止元数据无效")
        self.logs_truncated = report["logs_truncated"]
        counts = report.get("counts")
        expected = {key: len(value) for key, value in tables.items()} | {
            "logs": len(self.report_logs),
        }
        if (not isinstance(counts, dict) or set(counts) != set(expected)
                or any(type(counts[key]) is not int or counts[key] != value
                       for key, value in expected.items())):
            raise RunnerFailure("RQAlpha 报告计数与已接收记录不一致")
        return {**report, **tables, "logs": list(self.report_logs)}

    def _run_request(self, payload):
        if self.process is None:
            raise RunnerUnavailable("RQAlpha 执行器尚未启动")
        streaming = payload.get("op") == "run"
        request_id = uuid4().hex
        message = json.dumps(
            {**payload, **({"stream": True} if streaming else {}),
             "protocol": RQALPHA_PROTOCOL, "request_id": request_id},
            allow_nan=False, ensure_ascii=False,
        ).encode() + b"\n"
        if len(message) > self.input_limit:
            raise RunnerFailure("RQAlpha 输入超过大小限制")
        sent, received, output = 0, 0, bytearray()
        tables = {table: [] for table in RQALPHA_REPORT_TABLES}
        terminal, last_table = None, -1

        def accept(line):
            nonlocal terminal, last_table
            if len(line) + 1 > self.output_limit:
                raise RunnerFailure("RQAlpha 单帧输出超过 16 MiB 限制")
            try:
                frame = json.loads(line, parse_constant=self._invalid_constant)
            except (ValueError, UnicodeDecodeError, RecursionError) as exc:
                raise RunnerFailure("RQAlpha 未返回有效 JSON 帧") from exc
            if (not isinstance(frame, dict) or frame.get("protocol") != RQALPHA_PROTOCOL
                    or frame.get("request_id") != request_id):
                raise RunnerFailure("RQAlpha 响应与任务不匹配")
            if terminal is not None:
                raise RunnerFailure("RQAlpha 终止响应之后仍有数据")
            event = frame.get("event")
            if event == "log":
                if last_table >= 0 or set(frame) != {"protocol", "request_id", "event", "row"}:
                    raise RunnerFailure("RQAlpha 日志帧顺序或结构无效")
                self._accept_log(frame["row"])
            elif event == "rows":
                table = frame.get("table")
                if table not in RQALPHA_REPORT_TABLES:
                    raise RunnerFailure("RQAlpha 报告表名无效")
                rank = RQALPHA_REPORT_TABLES.index(table)
                if rank < last_table:
                    raise RunnerFailure("RQAlpha 报告批次顺序无效")
                self._accept_rows(frame, tables)
                last_table = rank
            elif "event" in frame:
                raise RunnerFailure("RQAlpha 返回未知流式事件")
            elif type(frame.get("ok")) is not bool:
                raise RunnerFailure("RQAlpha 终止响应无效")
            else:
                terminal = frame

        with selectors.DefaultSelector() as selector:
            os.set_blocking(self.process.stdin.fileno(), False)
            os.set_blocking(self.process.stdout.fileno(), False)
            selector.register(self.process.stdin, selectors.EVENT_WRITE)
            selector.register(self.process.stdout, selectors.EVENT_READ)
            eof = False
            while not eof:
                if self._cancelled():
                    raise RunnerFailure("RQAlpha 执行已取消")
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise RunnerFailure("RQAlpha 执行超过 600 秒时限")
                for key, _ in selector.select(min(remaining, .2)):
                    if key.fileobj is self.process.stdin:
                        try:
                            sent += os.write(key.fd, message[sent:sent + 65_536])
                        except BrokenPipeError as exc:
                            raise RunnerFailure("RQAlpha 提前关闭输入通道") from exc
                        if sent == len(message):
                            selector.unregister(self.process.stdin)
                            self.process.stdin.close()
                    else:
                        chunk = os.read(key.fd, 65_536)
                        if not chunk:
                            eof = True
                            break
                        received += len(chunk)
                        limit = self.channel_limit if streaming else self.output_limit
                        if received > limit:
                            raise RunnerFailure("RQAlpha 通道输出超过大小限制")
                        output.extend(chunk)
                        if streaming:
                            while b"\n" in output:
                                line, _, rest = output.partition(b"\n")
                                output = bytearray(rest)
                                accept(line)
                        if len(output) > self.output_limit:
                            raise RunnerFailure("RQAlpha 单帧输出超过 16 MiB 限制")
        self.process.wait(timeout=5)
        if streaming:
            if output or terminal is None:
                raise RunnerFailure("RQAlpha 流式响应缺少完整终止帧")
            if terminal["ok"] is not True:
                self._report_metadata(terminal.get("report_data"), tables)
                raise RunnerFailure("RQAlpha 策略执行失败，请检查输出日志和冻结行情")
            result = terminal.get("result")
            if not isinstance(result, dict):
                raise RunnerFailure("RQAlpha 结果结构无效")
            report = self._report_metadata(result.get("report_data"), tables)
            base = ("equity", "trades", "positions", "rejections", "corporate_actions")
            if any(not isinstance(result.get(key), list) for key in base):
                raise RunnerFailure("RQAlpha 结果缺少经济记录")
            if (sum(len(result[key]) for key in base)
                    + sum(map(len, tables.values())) > RQALPHA_MAX_RECORDS):
                raise RunnerFailure("RQAlpha 总记录超过 250,000 条限制")
            if self.process.returncode:
                raise RunnerFailure("RQAlpha 执行器未正常结束")
            return {**result, "report_data": report}
        try:
            response = json.loads(output, parse_constant=self._invalid_constant)
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            raise RunnerFailure("RQAlpha 未返回完整的有效 JSON 响应") from exc
        if (not isinstance(response, dict) or response.get("protocol") != RQALPHA_PROTOCOL
                or response.get("request_id") != request_id):
            raise RunnerFailure("RQAlpha 响应与任务不匹配")
        if self.process.returncode or response.get("ok") is not True:
            raise RunnerFailure("RQAlpha 策略执行失败，请检查源码和冻结行情")
        if not isinstance(response.get("result"), dict):
            raise RunnerFailure("RQAlpha 结果结构无效")
        return response["result"]


def rqalpha_runner_status() -> tuple[bool, str | None]:
    try:
        RqalphaSandbox(Path("."))._check_runtime()
    except RunnerUnavailable as exc:
        return False, str(exc)
    return True, None
