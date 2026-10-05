"""Import a pinned, independently generated receipt into an Atlas data copy.

This is a local Proof import, not a cloud Proof job or a production BKC payment.
Run against a stopped candidate API's copied data volume, then start the API.
"""
import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from zipfile import ZipFile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--expected-receipt-sha256', required=True)
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--verifier', type=Path)
    args = parser.parse_args()
    if args.data_dir:
        os.environ['ATLAS_DATA_DIR'] = str(args.data_dir.resolve())
    expected_hash = args.expected_receipt_sha256.lower()
    if len(expected_hash) != 64 or any(c not in '0123456789abcdef' for c in expected_hash):
        raise ValueError('Expected receipt hash must be 64 hex characters')
    if args.bundle.stat().st_size > 20_000_000:
        raise ValueError('Bundle exceeds 20 MB limit')
    with ZipFile(args.bundle) as archive:
        names = set(archive.namelist())
        allowed = {'manifest.json', 'journal.json', 'proof.r0', 'market.json',
                   'verify-proof-bundle.py', 'README.txt'}
        if names != allowed or len(archive.namelist()) != len(allowed):
            raise ValueError('Unexpected bundle members')
        if sum(item.file_size for item in archive.infolist()) > 25_000_000:
            raise ValueError('Expanded bundle exceeds 25 MB limit')
        manifest = json.loads(archive.read('manifest.json'))
        journal = json.loads(archive.read('journal.json'))
        market = json.loads(archive.read('market.json'))
        receipt = archive.read('proof.r0')
    receipt_hash = hashlib.sha256(receipt).hexdigest()
    if receipt_hash != expected_hash or manifest.get('proof_hash') != expected_hash:
        raise ValueError('Receipt does not match the pinned SHA-256')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
    from app.config import DATA_DIR, DB_PATH
    from app.quantjudge import QuantJudgeStore
    from app.zkp import (Risc0ReceiptVerifier, ZkProofError, ZkProofStore,
                         load_profiles, market_commitment)
    from app.zkp_models import ZkPublicStatement

    statement = ZkPublicStatement.model_validate(journal)
    profile = load_profiles()[statement.proof_profile]
    if profile['status'] != 'active' or manifest.get('image_id') != profile['image_id']:
        raise ValueError('Bundle does not match the active pinned image ID')
    if market_commitment(market['dataset']) != statement.market_data_hash:
        raise ValueError('Market dataset does not match the receipt journal')
    verifier_path = args.verifier or Path(__file__).resolve().parents[1] / 'strategy/zkvm/target/release/atlas-zkvm'
    verifier = Risc0ReceiptVerifier(verifier_path)
    with tempfile.NamedTemporaryFile(dir=DATA_DIR, suffix='.r0') as temporary:
        temporary.write(receipt)
        temporary.flush()
        verified = verifier.verify(Path(temporary.name), profile['image_id'])
    if verified.journal != statement.model_dump(mode='json', by_alias=True):
        raise ValueError('Public journal does not match the verified receipt')

    quant = QuantJudgeStore(DB_PATH, seed_demo=False)
    proofs = ZkProofStore(verifier=verifier)
    quant.bind_proof_store(proofs)
    with proofs._connect() as connection:
        existing = connection.execute(
            'SELECT proof_id FROM qj_proof_imports WHERE source_proof_hash = ?',
            (expected_hash,),
        ).fetchone()
        if existing:
            proof_id = existing['proof_id']
            verified_again = proofs.reverify(proof_id)
            proof = proofs.get(proof_id)
            agent = connection.execute(
                'SELECT status,is_demo FROM qj_agents WHERE id=?', (proof['agent_id'],)
            ).fetchone()
            dataset, _ = proofs.market_dataset(verified_again.journal['market_data_hash'])
            if (proof['proof_hash'] != expected_hash or not agent or agent['status'] != 'active'
                    or agent['is_demo'] != 1 or dataset['status'] != 'trusted'
                    or not proof['import_origin'] or not proof['id']):
                raise ValueError('Existing import is incomplete or inconsistent')
            report_id = connection.execute(
                'SELECT id FROM qj_reports WHERE zk_proof_id=?', (proof_id,)
            ).fetchone()
            if not report_id or quant.verify_report(report_id['id'], refresh_chain=False).get('external_proof_verified') is not True:
                raise ValueError('Existing imported report failed verification')
            print(json.dumps({'proof_id': proof_id, 'already_imported': True}))
            return
        collision = connection.execute(
            'SELECT id,status,developer_alias,strategy_commitment FROM qj_agents WHERE id = ?',
            (statement.agent_id,),
        ).fetchone()
        if collision:
            if (collision['status'] != 'importing_local_proof'
                    or collision['developer_alias'] != 'Atlas 验收'
                    or collision['strategy_commitment'] != statement.strategy_commitment):
                raise ValueError('Agent ID already exists; refusing to overwrite production data')
            stale = connection.execute(
                'SELECT proof_hash FROM qj_zk_proofs WHERE agent_id=?', (statement.agent_id,)
            ).fetchall()
            if any(row['proof_hash'] != expected_hash for row in stale):
                raise ValueError('Incomplete Agent contains an unexpected receipt')
            connection.execute('DELETE FROM qj_agents WHERE id=?', (statement.agent_id,))
    # A prior interrupted import may leave the receipt file after its row was
    # removed. Only discard this exact pinned content when no row references it.
    orphan = proofs.receipt_root / f'{expected_hash}.r0'
    if orphan.exists():
        with proofs._connect() as connection:
            referenced = connection.execute(
                'SELECT 1 FROM qj_zk_proofs WHERE proof_hash=?', (expected_hash,)
            ).fetchone()
        if referenced or hashlib.sha256(orphan.read_bytes()).hexdigest() != expected_hash:
            raise ValueError('Receipt file collision in target data directory')
        orphan.unlink()
    if statement.previous_receipt_hash is not None:
        raise ValueError('Import requires the first receipt of a new isolated Agent')

    dataset = market['dataset']
    fetched_at = datetime.now(UTC)
    registered = proofs.register_market_dataset(
        dataset, fetched_at=fetched_at,
        trust_model='imported_public_test_input_origin_unverified',
    )
    if registered['market_data_hash'] != statement.market_data_hash:
        raise ZkProofError('Market registration does not match the receipt')
    token = 'qjt_' + secrets.token_urlsafe(32)
    now = datetime.now(UTC).isoformat()
    with quant._connect() as connection:
        connection.execute(
            '''INSERT INTO qj_agents (
                id,name,developer_alias,agent_type,category,asset_classes_json,
                description,risk_level,monthly_price,price_currency,strategy_commitment,
                developer_token_hash,status,is_demo,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (statement.agent_id, '本机隔离输入 · 真实 ZKP', 'Atlas 验收', 'traditional',
             'timing', '["crypto"]',
             '本机独立生成并导入验证的历史回测 Proof；输入来自隔离测试，'
             '测试链付款不等同正式网站付款，未证明行情来源或实盘收益。',
             'medium', 0, 'BKC', statement.strategy_commitment,
             quant._token_hash(token), 'importing_local_proof', 0, now, now),
        )
    proof = proofs.register_receipt(statement.agent_id, statement.proof_profile, receipt, token)
    report = quant.publish_zk_report(statement.agent_id, proof['id'], token)
    proofs.reverify(proof['id'])
    checked = quant.verify_report(report['id'], refresh_chain=False)
    if checked.get('external_proof_verified') is not True:
        raise ZkProofError('Imported report failed independent stored verification')
    with proofs._connect() as connection:
        connection.execute(
            '''INSERT INTO qj_proof_imports
               (proof_id, origin_kind, payment_scope, source_proof_hash, imported_at)
               VALUES (?, 'local_isolated_proof', 'test_chain_only', ?, ?)''',
            (proof['id'], expected_hash, now),
        )
        connection.execute(
            "UPDATE qj_agents SET status='active',is_demo=1,updated_at=? "
            "WHERE id=? AND status='importing_local_proof'",
            (now, statement.agent_id),
        )
    print(json.dumps({'proof_id': proof['id'], 'report_id': report['id'],
                      'agent_id': statement.agent_id, 'already_imported': False,
                      'payment_scope': 'test_chain_only'}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Proof import failed: {type(error).__name__}: {error}', file=sys.stderr)
        sys.exit(1)
