"""Author-local Proof entry point. Source and witness stay on this device."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("check-install", help="Inspect local tool/binary availability without proving or rebuilding")
    prepare = commands.add_parser("prepare", help="Compile supported Python and prepare a private witness")
    prepare.add_argument("--dataset", type=Path, required=True)
    prepare.add_argument("--python-source", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--agent", default="qja_author_draft")
    prepare.add_argument("--capital-micros", type=int, default=100_000_000)
    prepare.add_argument("--commission-bps", type=int, default=10)
    prepare.add_argument("--slippage-bps", type=int, default=5)
    prove = commands.add_parser("prove", help="Generate and verify a real receipt on the author device")
    prove.add_argument("--witness", type=Path, required=True)
    prove.add_argument("--output", type=Path, required=True)
    prove.add_argument("--resume", action="store_true")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    binary = ROOT / "strategy/zkvm/target/release/atlas-zkvm"
    scripts = ROOT / "scripts"
    available = binary.is_file() and os.access(binary, os.X_OK)
    if args.command == "check-install":
        tools_available = all((scripts / name).is_file() for name in ("prepare-zk-witness.py", "prove-private-program.py"))
        print(json.dumps({"binary_path": str(binary), "binary_available": available,
                          "scripts_available": tools_available, "profile_changed": False,
                          "cryptographic_verification_performed": False,
                          "message": "检查仅确认文件可用性；二进制来源和平台兼容性需另行核对。"}, ensure_ascii=False))
        return 0 if available and tools_available else 1
    if not available:
        print("缺少作者本机可执行证明器；请提供已审查且匹配本机平台的二进制，工具不会自动重建。", file=sys.stderr)
        return 1
    if args.command == "prepare":
        command = [sys.executable, str(scripts / "prepare-zk-witness.py"), "--dataset", str(args.dataset.resolve()),
                   "--python-source", str(args.python_source.resolve()), "--output", str(args.output.resolve()),
                   "--agent", args.agent, "--capital-micros", str(args.capital_micros),
                   "--commission-bps", str(args.commission_bps), "--slippage-bps", str(args.slippage_bps)]
    else:
        command = [sys.executable, str(scripts / "prove-private-program.py"), "--witness", str(args.witness.resolve()),
                   "--output", str(args.output.resolve())]
        if args.resume:
            command.append("--resume")
    try:
        return subprocess.run(command, check=False).returncode
    except OSError:
        print("作者本机工具无法启动；未上传策略或witness。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
