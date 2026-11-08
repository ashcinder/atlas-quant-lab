"""Reverify two existing public receipts on the real Linux verifier, without proving."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--api-image', required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--compat-receipt', type=Path, default=root / '.artifacts/comprehensive-20261108/linux-supplements-r2/receipt-input/proof.r0')
args = parser.parse_args()
output = args.output.resolve()
output.mkdir(exist_ok=False, parents=True)
image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', args.api_image], text=True))[0]['Id']
samples = [
    (root / 'docs/zkp-acceptance-20260916/proof.r0',
     '29c2bcf7d465c4d2e520973d33781401d8b52f3abb281853076345cc246adc42'),
    (args.compat_receipt.resolve(),
     '6c85feec41f6ad8bd64f3520984a9886ff877df1eac5f41298993157d58bd2d3'),
]
profile = json.loads((root / 'strategy/zkvm/profiles.json').read_text())['profiles']['atlas_program_backtest_risc0_v2']
binary = '/app/strategy/zkvm/target/release/atlas-zkvm'
records = []
for index, (path, sha) in enumerate(samples):
    before = path.read_bytes()
    assert hashlib.sha256(before).hexdigest() == sha
    corrupt = output / f'corrupt-{index}.r0'
    changed = bytearray(before)
    changed[len(changed)//2] ^= 255
    corrupt.write_bytes(changed)
    base = ['docker', 'run', '--rm', '--network', 'none', '--read-only', '--platform', 'linux/amd64',
            '--cpus', '1', '--memory', '768m', '-e', 'RISC0_DEV_MODE=0', '--entrypoint', binary]
    states = {}
    for name, receipt, expected_image in [
        ('valid', path, profile['image_id']),
        ('wrong_image', path, '00' * 32),
        ('corrupt', corrupt, profile['image_id']),
    ]:
        process = subprocess.run(base + ['-v', str(receipt) + ':/sample.r0:ro', image,
                                        'verify', '--receipt', '/sample.r0', '--expected-image-id', expected_image],
                                 capture_output=True, text=True, timeout=60)
        if name == 'valid':
            result = json.loads(process.stdout)
            assert process.returncode == 0 and result['valid'] is True and result['image_id'] == expected_image
            states[name] = True
        else:
            assert process.returncode != 0, name
            states[name + '_rejected'] = True
    assert path.read_bytes() == before
    records.append({'sha256': sha, 'size': len(before), 'source': str(path.relative_to(root)) if path.is_relative_to(root) else path.name, **states})
result = {'passed': True, 'proof_profile': 'atlas_program_backtest_risc0_v2',
          'image': image, 'generated_proofs': 0, 'records': records,
          'v1_real_receipt': 'blocked_no_existing_public_sample'}
(output/'result.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result))
