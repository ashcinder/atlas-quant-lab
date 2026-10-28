"""Export a verified report's exact Supervisor anchor, or submit wallet-signed bytes.

No private keys, funding, invented transaction hashes, or local fake confirmations.
An anchor commits hashes; it does not run a ZK verifier contract on-chain.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.quantjudge import QuantJudgeStore
from app.zkp import ZkProofStore


def anchor_intent(quant, report_id):
    checked = quant.verify_report(report_id, refresh_chain=False)
    if not all(checked.get(key) is True for key in (
            'external_proof_verified', 'proof_cryptographic_valid',
            'receipt_hash_valid', 'record_integrity_valid')):
        raise ValueError('报告尚未通过真实ZKP与绑定验证，拒绝准备锚定')
    with quant._connect() as connection:
        row = connection.execute('SELECT * FROM qj_reports WHERE id = ?', (report_id,)).fetchone()
    data = quant._expected_anchor_input(row)
    if not data.startswith('0x' + b'ATLASZK2'.hex()) or len(bytes.fromhex(data[2:])) != 136:
        raise ValueError('报告没有完整的ATLASZK2锚定承诺')
    return {'report_id': report_id, 'chainId': 1051, 'value': '0x0', 'data': data,
            'purpose': 'commitment_anchor_only', 'onchain_zk_verification': False,
            'wallet_fields_required': ['from', 'to', 'nonce', 'gas', 'gasPrice'],
            'note': '由钱包补全交易字段并签名；这是未签名锚定内容，不是已上链凭证。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True)
    parser.add_argument('--signed-transaction', type=Path)
    parser.add_argument('--author-file', type=Path)
    args = parser.parse_args()
    quant = QuantJudgeStore(seed_demo=False)
    quant.bind_proof_store(ZkProofStore())
    intent = anchor_intent(quant, args.report)
    if args.signed_transaction:
        if not args.author_file:
            parser.error('提交需要作者本地身份文件；不要把令牌或私钥粘贴到聊天')
        author = json.loads(args.author_file.read_text())
        if author['agent_id'] != quant.get_report(args.report)['agent_id']:
            raise ValueError('作者身份与报告不一致')
        raw = args.signed_transaction.read_text().strip()
        # The chain validates the signed transaction. Report verification then
        # checks its exact input; a tx hash alone never counts as confirmation.
        checked = quant.submit_anchor(args.report, raw, author['developer_token'])
        print(json.dumps(checked, ensure_ascii=False, indent=2))
        return 0 if checked.get('chain', {}).get('status') == 'confirmed' else 2
    print(json.dumps({'intent': intent, 'observed_chain': vars(quant.supervisor.status())},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print(f'未完成锚定：{type(error).__name__}。没有标记链上确认。', file=sys.stderr)
        sys.exit(1)
