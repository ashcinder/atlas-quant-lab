"""Run from an independently reviewed local checkout with the AUTHOR AWS profile."""
import argparse
import json
import os
from pathlib import Path
from protocol import seal, validate_payload

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True, help='private-strategy-runner init directory')
    parser.add_argument('--config', type=Path, required=True, help='run connection JSON from strategy trading')
    parser.add_argument('--key-arn', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--interval', type=int, default=30)
    args = parser.parse_args()
    import boto3
    local = json.loads((args.directory / 'local.json').read_text())
    payload = {'source': Path(local['source']).read_text(), 'salt': local['salt'],
        'signing_key': (args.directory / 'runner.key').read_text().strip(),
        'config': json.loads(args.config.read_text()), 'interval': args.interval}
    validate_payload(payload)
    envelope = seal(payload, args.key_arn, boto3.client('kms', region_name=args.key_arn.split(':')[3]))
    with open(args.output, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
        json.dump(envelope, stream)
    print('Encrypted package written. Only this output may be copied to the platform.')

if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Packaging failed; no plaintext or diagnostic details were emitted.') from None
