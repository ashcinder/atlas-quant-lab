"""Generate and independently verify a real, local RISC Zero program receipt.

No cloud prover, no development receipts, no source/witness upload. Publication
is an explicit local-project operation and requires an already registered market.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.zkp import Risc0ReceiptVerifier, ZkProofError, ZkProofStore, load_profiles
from app.zkp_models import ZkPublicStatement

PROFILE = 'atlas_program_backtest_risc0_v2'
BINARY = ROOT / 'strategy/zkvm/target/release/atlas-zkvm'


def write_private(path, data):
    with open(path, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)


def prover_environment():
    # Do not inherit BONSAI credentials, remote prover URLs, dev flags or hooks.
    return {'PATH': os.environ.get('PATH', ''), 'RISC0_PROVER': 'local',
            'RISC0_DEV_MODE': '0', 'RAYON_NUM_THREADS': '4'}


def invoke(args, timeout=3600):
    result = subprocess.run([str(BINARY), *args], env=prover_environment(),
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # Prover diagnostics can include private witness values; never echo them.
        raise RuntimeError('本地证明程序失败；没有登记证明或收益。请在作者机器检查输入与工具链。')
    return json.loads(result.stdout)


def check_bundle(witness, verified):
    statement = ZkPublicStatement.model_validate(verified.journal)
    if statement.proof_profile != PROFILE or statement.agent_id != witness['agent_id']:
        raise ZkProofError('证明没有绑定指定程序和策略身份')
    if statement.initial_equity_micros != witness['initial_equity_micros']:
        raise ZkProofError('证明的初始资金不匹配')
    return statement


def execute(args):
    profile = load_profiles()[PROFILE]
    if profile['status'] != 'active':
        raise ZkProofError('证明程序已停用')
    built = invoke(['profile', '--profile', PROFILE], timeout=30)
    if built['image_id'] != profile['image_id']:
        raise ZkProofError('本地执行器与已登记image ID不同；不会覆盖登记值')
    output = args.output.expanduser().resolve()
    if args.resume:
        witness = json.loads((output / 'witness.private.json').read_text())
    else:
        witness = json.loads(args.witness.read_text())
        if args.python_source:
            from app.zk_python import compile_strategy
            witness['strategy']['program'] = compile_strategy(args.python_source.read_text())
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
    # A copy stays on the AUTHOR machine, never in the platform database.
    draft = output / 'draft.private.json'
    if not args.resume:
        write_private(draft, witness)
    inspect_path = output / 'witness.private.json' if args.resume else draft
    inspected = invoke(['inspect', '--profile', PROFILE, '--witness', str(inspect_path)], timeout=60)
    # inspect is preflight computation, NOT proof verification.
    quant = proofs = None
    token = None
    if args.publish_local:
        from app.quantjudge import QuantJudgeStore
        from app.quantjudge_models import QuantAgentCreate
        proofs = ZkProofStore()
        proofs.market_dataset(inspected['market_data_hash'])  # Do not trust author-supplied data roots.
        # Advisory preflight saves expensive proving work. The atomic check in
        # register_receipt remains authoritative against concurrent replays.
        with proofs._connect() as connection:
            replay = connection.execute('SELECT 1 FROM qj_zk_proofs WHERE nullifier = ?',
                                        (inspected['nullifier'],)).fetchone()
        if replay:
            raise ZkProofError('该报告nonce已使用；新报告须在作者端生成新nonce，禁止重放')
        if witness.get('previous_receipt_hash'):
            raise ZkProofError('新建策略身份不能声明旧报告；后续报告使用现有身份流程')
        quant = QuantJudgeStore(seed_demo=False)
        quant.bind_proof_store(proofs)
        if args.resume:
            author = json.loads((output / 'author.private.json').read_text())
            if author['agent_id'] != witness['agent_id']:
                raise ZkProofError('恢复身份不匹配')
            token = author['developer_token']
        else:
            created = quant.create_agent(QuantAgentCreate(
                name=args.name, developer_alias='本地作者', category='timing',
                agent_type='traditional', asset_classes=['crypto'],
                description='真实RISC Zero有界程序回测证明；不代表实盘收益或TEE保密托管。',
                strategy_commitment=inspected['strategy_commitment']))
            witness['agent_id'] = created['agent']['id']
            token = created['developer_token']
            write_private(output / 'author.private.json', {'agent_id': witness['agent_id'], 'developer_token': token})
    private = output / 'witness.private.json'
    if not args.resume:
        write_private(private, witness)
    receipt = output / 'proof.r0'
    started = time.monotonic()
    if not args.resume:
        print('开始本地真实证明；策略与witness不会发送给远程证明服务。', flush=True)
        invoke(['prove', '--profile', PROFILE, '--witness', str(private), '--receipt', str(receipt)])
    os.chmod(receipt, 0o600)
    verifier = Risc0ReceiptVerifier()
    verified = verifier.verify(receipt, profile['image_id'])
    statement = check_bundle(witness, verified)
    # Ensure native preflight and proved computation agree apart from identity.
    for field, expected in inspected.items():
        if field not in {'agent_id', 'nullifier'} and verified.journal.get(field) != expected:
            raise ZkProofError(f'已证明结果与预执行不一致：{field}')
    rejected = []
    damaged = output / 'corrupted-test.r0'
    content = bytearray(receipt.read_bytes())
    content[len(content) // 2] ^= 1
    damaged.write_bytes(content)
    os.chmod(damaged, 0o600)
    try:
        for path, image_id, name in [(damaged, profile['image_id'], 'corrupted_receipt'),
                                     (receipt, 'ab' * 32, 'wrong_image_id')]:
            try:
                verifier.verify(path, image_id)
            except ZkProofError:
                rejected.append(name)
            else:
                raise ZkProofError(f'反例未被拒绝：{name}')
    finally:
        damaged.unlink()
    result = {'proof_system': 'risc0-zkvm', 'proof_profile': PROFILE,
              'image_id': profile['image_id'], 'cryptographically_verified': True,
              'proof_sha256': hashlib.sha256(receipt.read_bytes()).hexdigest(),
              'receipt_bytes': receipt.stat().st_size, 'elapsed_seconds': round(time.monotonic() - started, 2),
              'resumed_existing_receipt': args.resume,
              'rejected_cases': rejected, 'statement': statement.model_dump(mode='json', by_alias=True),
              'scope': 'execution_and_net_backtest_performance_of_private_bounded_program',
              'confidential_hosting_verified': False, 'exchange_fills_verified': False,
              'market_origin_cryptographically_verified': False, 'onchain_verified': False}
    if quant is not None:
        proof = proofs.register_receipt(witness['agent_id'], PROFILE, receipt.read_bytes(), token)
        report = quant.publish_zk_report(witness['agent_id'], proof['id'], token)
        recheck = quant.verify_report(report['id'], refresh_chain=False)
        if recheck.get('external_proof_verified') is not True:
            raise ZkProofError('已发布报告重新验证失败')
        try:
            proofs.register_receipt(witness['agent_id'], PROFILE, receipt.read_bytes(), token)
        except ZkProofError:
            rejected.append('duplicate_receipt')
        else:
            raise ZkProofError('重复证明未被拒绝')
        result.update(agent_id=witness['agent_id'], proof_id=proof['id'], report_id=report['id'])
    write_private(output / 'verification.public.json', result)
    print(json.dumps({key: result[key] for key in ('cryptographically_verified', 'proof_sha256', 'receipt_bytes', 'elapsed_seconds', 'rejected_cases')}, ensure_ascii=False))
    print(f'公开验收文件：{output / "verification.public.json"}')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--witness', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New directory on author machine; never overwritten')
    parser.add_argument('--publish-local', action='store_true', help='Create a real local-project Agent and publish only its proof and public statement')
    parser.add_argument('--resume', action='store_true', help='Re-verify an unpublished existing receipt and saved author identity; never bypass cryptographic verification')
    parser.add_argument('--python-source', type=Path, help='Author-local restricted Python source; only compiled integer program is proved, not CPython or this compiler')
    parser.add_argument('--name', default='私有程序 · 真实ZKP回测验收')
    args = parser.parse_args()
    if args.resume and args.python_source:
        parser.error('--resume不可替换已证明程序')
    try:
        execute(args)
    except Exception as error:
        print(f'未完成证明验收：{type(error).__name__}。不会标记成功。', file=sys.stderr)
        sys.exit(1)
