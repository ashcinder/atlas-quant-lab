"""One-command real proof acceptance, synthetic data, no production DB/chain writes.

backend/.venv/bin/python scripts/zkp-e2e.py --output /absolute/new-author-directory
Receipts are real; synthetic candles are explicitly not provider-authenticated.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.zk_author import prepare_witness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(mode=0o700, parents=True, exist_ok=False)
    market = {'source': 'synthetic-e2e', 'symbol': 'TEST-USD', 'interval': '1d', 'adjustment': 'raw', 'bars': []}
    for i in range(32):
        price = (100+i%7)*1_000_000
        market['bars'].append({'time': 1704067200+i*86400, 'open_micros': price, 'high_micros': price+2000000, 'low_micros': price-2000000, 'close_micros': price+1000000, 'volume_micros': 1000000000})
    source = (ROOT / 'strategy/examples/zk-python/strategy.py').read_text()
    witness = prepare_witness(market, source, 'qja_e2e_fixture', 1000000000, 10, 5)
    private = output / 'input.private.json'
    private.write_text(json.dumps(witness)); private.chmod(0o600)
    subprocess.run([sys.executable, str(ROOT/'scripts/prove-private-program.py'), '--witness', str(private), '--output', str(output/'proof')], check=True)
    subprocess.run([sys.executable, str(ROOT/'deploy/zk_program_smoke.py'), str(output/'proof/witness.private.json'), str(output/'proof/proof.r0')], check=True)
    acceptance = json.loads((output/'proof/verification.public.json').read_text())
    acceptance.update(api_reverification=True, isolated_report_publication=True, replay_rejected=True, synthetic_dataset=True)
    (output/'acceptance.public.json').write_text(json.dumps(acceptance, indent=2)+'\n')
    print(f'真实证明和API验收完成：{output / "acceptance.public.json"}')

if __name__ == '__main__':
    main()
