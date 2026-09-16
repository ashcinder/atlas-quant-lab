"""Offline verification against the verifier and fixed profiles in your trusted checkout.
No network calls, database writes, or prover calls. Never executes strategy Python.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def verify_bundle(folder, repository, expected_agent=None, expected_return_ppm=None):
    folder, repository = Path(folder).resolve(), Path(repository).resolve()
    sys.path.insert(0, str(repository / 'backend'))
    from app.zkp import market_commitment
    from app.zk_python import compile_strategy
    manifest = json.loads((folder / 'manifest.json').read_text())
    statement = json.loads((folder / 'journal.json').read_text())
    profiles = json.loads((repository / 'strategy/zkvm/profiles.json').read_text())['profiles']
    profile = profiles[statement['proof_profile']]
    if profile['status'] != 'active' or manifest['image_id'] != profile['image_id']:
        raise ValueError('固定程序版本不匹配')
    receipt = folder / 'proof.r0'
    if hashlib.sha256(receipt.read_bytes()).hexdigest() != manifest['proof_hash']:
        raise ValueError('receipt 文件已改变')
    binary = repository / 'strategy/zkvm/target/release/atlas-zkvm'
    environment = {'PATH': os.environ.get('PATH', ''), 'RISC0_DEV_MODE': '0'}
    def invoke(arguments):
        process = subprocess.run([str(binary), *arguments], capture_output=True, text=True, env=environment, timeout=60)
        if process.returncode:
            raise ValueError('独立验证器拒绝该证明或输入')
        return json.loads(process.stdout)
    actual = invoke(['verify', '--receipt', str(receipt), '--expected-image-id', profile['image_id']])
    if actual.get('valid') is not True or actual.get('image_id') != profile['image_id'] or actual.get('journal') != statement:
        raise ValueError('证明与公开结果不一致')
    dataset = json.loads((folder / 'market.json').read_text())['dataset']
    if market_commitment(dataset) != statement['market_data_hash']:
        raise ValueError('历史数据或标的已改变')
    if [dataset['bars'][0]['time'], dataset['bars'][-1]['time']] != [statement['period_start'], statement['period_end']]:
        raise ValueError('证明区间不一致')
    if expected_agent is not None and statement['agent_id'] != expected_agent:
        raise ValueError('策略身份不符合预期')
    if expected_return_ppm is not None and statement['metrics']['total_return_ppm'] != expected_return_ppm:
        raise ValueError('公开收益不符合预期')
    public_code_verified = False
    if manifest.get('public_example'):
        source = (folder / 'strategy.py').read_text()
        witness_path = folder / 'witness.public.json'
        witness = json.loads(witness_path.read_text())
        if compile_strategy(source) != witness['strategy']['program']:
            raise ValueError('公开策略源码与程序不一致')
        if invoke(['inspect', '--profile', statement['proof_profile'], '--witness', str(witness_path)]) != statement:
            raise ValueError('公开输入重放结果与证明不一致')
        public_code_verified = True
    return {'valid': True, 'agent_id': statement['agent_id'], 'symbol': dataset['symbol'],
            'period_start': statement['period_start'], 'period_end': statement['period_end'],
            'total_return_ppm': statement['metrics']['total_return_ppm'],
            'public_code_verified': public_code_verified, 'market_origin_verified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--expected-agent')
    parser.add_argument('--expected-return-ppm', type=int)
    args = parser.parse_args()
    try:
        result = verify_bundle(args.bundle, args.repository, args.expected_agent, args.expected_return_ppm)
    except (ValueError, KeyError, OSError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f'验证失败：{error}') from error
    print(json.dumps(result, ensure_ascii=False))
