"""Prepare an author-private witness from a downloaded dataset and supported Python.

Compiles supported Python without executing it. Default mode prints public
preflight commitments only; inspect is not a cryptographic proof. Optional
--proof-output generates a native local proof; --publish-local publishes its
verified public report to this project database. Source stays on this machine.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.zk_author import prepare_witness, PROFILE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--python-source', type=Path, required=True)
    parser.add_argument('--name', default='我的可验证策略')
    parser.add_argument('--agent', default='qja_author_draft')
    parser.add_argument('--capital-micros', type=int, default=100_000_000)
    parser.add_argument('--commission-bps', type=int, default=10)
    parser.add_argument('--slippage-bps', type=int, default=5)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--proof-output', type=Path, help='Generate and verify a real proof into a new author-local directory')
    parser.add_argument('--publish-local', action='store_true', help='Publish verified public proof to this local project; needs a platform-registered dataset')
    args = parser.parse_args()
    if args.publish_local and not args.proof_output:
        parser.error('--publish-local requires --proof-output')
    witness = prepare_witness(json.loads(args.dataset.read_text()), args.python_source.read_text(),
                              args.agent, args.capital_micros, args.commission_bps, args.slippage_bps)
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(args.output, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as handle:
        json.dump(witness, handle)
    result = subprocess.run([str(ROOT / 'strategy/zkvm/target/release/atlas-zkvm'), 'inspect', '--profile', PROFILE,
                             '--witness', str(args.output.resolve())], capture_output=True, text=True, timeout=60,
                            env={'PATH': os.environ.get('PATH', ''), 'RISC0_DEV_MODE': '0'})
    if result.returncode:
        raise SystemExit('固定guest预检失败；私有witness保留在作者设备，未上传。')
    print(json.dumps({'preflight_only': True, 'statement': json.loads(result.stdout)}, ensure_ascii=False))
    if args.proof_output:
        command = [sys.executable, str(ROOT / 'scripts/prove-private-program.py'), '--witness', str(args.output.resolve()), '--output', str(args.proof_output.resolve())]
        if args.publish_local:
            command.extend(['--publish-local', '--name', args.name])
        subprocess.run(command, check=True)

if __name__ == '__main__':
    main()
