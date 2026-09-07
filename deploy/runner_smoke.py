"""Real gVisor integration tests. No weaker runtime or fake success fallback."""
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.execution import run_private_strategy  # noqa: E402
from app.execution_models import ExecutionRequest  # noqa: E402
from app.sandbox import RunnerFailure  # noqa: E402


def package(source):
    manifest = {"id": "sandbox_probe", "name": "Sandbox probe", "version": "1.0.0",
                "language": "python", "entrypoint": "strategy.py:Probe",
                "description": "Non-private fixture for actual sandbox integration tests",
                "asset_classes": ["crypto"], "intervals": ["1d"]}
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("strategy.json", json.dumps(manifest))
        archive.writestr("strategy.py", source)
    return output.getvalue()


def main():
    assert os.environ.get("ATLAS_RUNNER_ENABLED") == "1"
    data = {"symbol": "BTC-USD", "interval": "1d", "bars": [
        {"time": 1700000000 + i * 86400, "open_micros": (100 + i) * 1_000_000,
         "close_micros": (101 + i) * 1_000_000, "high_micros": (102 + i) * 1_000_000,
         "low_micros": (99 + i) * 1_000_000, "volume_micros": 1_000_000_000_000}
        for i in range(5)]}
    request = ExecutionRequest(market_data_hash="ab" * 32, acknowledge_host_visibility=True)
    prefix = "from atlas_strategy_sdk import BaseStrategy, TargetPosition\n"
    valid = prefix + """
class Probe(BaseStrategy):
    def generate_targets(self, ctx):
        import os, socket
        assert not os.environ.get('AWS_SECRET_ACCESS_KEY')
        assert not os.path.exists('/var/run/docker.sock')
        assert all(b.timestamp <= ctx.now for b in ctx.history('BTC-USD', 100))
        try:
            open('/strategy/strategy.py', 'w')
        except OSError:
            pass
        else:
            raise AssertionError('strategy mount writable')
        try:
            socket.create_connection(('1.1.1.1', 443), timeout=0.2)
        except OSError:
            pass
        else:
            raise AssertionError('network not isolated')
        return [TargetPosition('BTC-USD', 0.5, 1, 'FIXTURE')]
"""
    with tempfile.TemporaryDirectory(prefix="atlas-host-canary-") as directory:
        canary = Path(directory) / "private"
        canary.write_text("do not expose host data")
        valid = valid.replace("import os, socket", f"import os, socket\n        assert not os.path.exists({str(canary)!r})")
        result = run_private_strategy(package(valid), data, request)
        assert result["metrics"]["trade_count"] > 0 and not result["zk_verified"]
    for name, attack in [
        ("timeout", "while True: pass"),
        ("memory", "x = bytearray(2_000_000_000)"),
        ("output", "import os; os.write(1, b'x' * 100000)"),
    ]:
        source = prefix + f"class Probe(BaseStrategy):\n    def generate_targets(self, ctx):\n        {attack}\n        return []\n"
        try:
            run_private_strategy(package(source), data, request)
        except RunnerFailure:
            print(f"Rejected actual sandbox {name} attack", flush=True)
        else:
            raise AssertionError(f"{name} attack was not rejected")
    print("Real gVisor sandbox passed: SDK execution, causal data, network/host/mount isolation, time, memory and output limits.")


if __name__ == "__main__":
    main()
