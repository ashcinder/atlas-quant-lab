"""Build three genuinely proved public examples before replacing local QuantJudge data.

Only --replace-market mutates the existing database, after a full backup and
verification of all new reports. Auth, journal, runtime accounts and chain stay.
"""
import argparse
from datetime import UTC, datetime
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.config import DB_PATH, DATA_DIR
from app.zk_author import prepare_witness
from app.zkp import ZkProofStore
from app.quantjudge import QuantJudgeStore
from app.zkp_bindings import init_public_programs, check_public_program


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--datasets',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--replace-market',action='store_true')
    args=parser.parse_args()
    root=args.output.resolve();root.mkdir(parents=True,exist_ok=False,mode=0o700)
    staging=root/'database';staging.mkdir()
    if (DATA_DIR/'quantjudge_attestation.key').exists():
        shutil.copy2(DATA_DIR/'quantjudge_attestation.key',staging/'quantjudge_attestation.key')
    db=staging/'atlas_quant.db'
    quant=QuantJudgeStore(db,seed_demo=False)
    proofs=ZkProofStore(db,receipt_root=staging/'receipts',market_root=staging/'market')
    init_public_programs(proofs)
    quant.bind_proof_store(proofs)
    spec=importlib.util.spec_from_file_location('author_prove',ROOT/'scripts/prove-private-program.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    # Redirect the existing local-publish factory to the staging stores.
    import app.zkp, app.quantjudge
    app.zkp.ZkProofStore=lambda:proofs
    app.quantjudge.QuantJudgeStore=lambda **kw:quant
    module.ZkProofStore=lambda:proofs
    strategies=[
        ('BTC-USD','BTC · 双均线趋势 3/7','def target_bps(index, close, sma):\n    return (5000 if sma(3) > sma(7) else 0) if index >= 7 else 0\n'),
        ('BTC-USD','BTC · 均线回归 5日','def target_bps(index, close, sma):\n    return (3000 if close(0) < sma(5) else 0) if index >= 5 else 0\n'),
        ('ETH-USD','ETH · 价格动量 3日','def target_bps(index, close, sma):\n    return (4000 if close(0) > close(3) else 0) if index >= 4 else 0\n'),
    ]
    records=[]
    for index,(symbol,name,source) in enumerate(strategies):
        market=json.loads((args.datasets/(symbol+'.json')).read_text())
        proofs.register_market_dataset(market,fetched_at=datetime.now(UTC),trust_model='platform_fetched_binance_public_api_not_provider_signed')
        witness=prepare_witness(market,source,'qja_author_draft',10000000000,10,5)
        folder=root/f'strategy-{index+1}';folder.mkdir(mode=0o700)
        private=folder/'input.private.json';private.write_text(json.dumps(witness));private.chmod(0o600)
        (folder/'strategy.py').write_text(source)
        print(f'[{index+1}/3] {name}: 开始真实证明',flush=True)
        result=module.execute(argparse.Namespace(witness=private,output=folder/'proof',resume=False,python_source=None,publish_local=True,name=name))
        proven=json.loads((folder/'proof/witness.private.json').read_text())
        with proofs._connect() as conn:
            conn.execute('INSERT INTO qj_public_programs VALUES (?,?,?)',(result['proof_id'],source,json.dumps(proven)))
        check_public_program(proofs,result['proof_id'],result['statement'])
        records.append({k:result[k] for k in ('agent_id','proof_id','report_id','proof_sha256','elapsed_seconds','statement')})
    # Restore factories before final integration checks.
    app.zkp.ZkProofStore=ZkProofStore;app.quantjudge.QuantJudgeStore=QuantJudgeStore
    for record in records:
        assert quant.verify_report(record['report_id'],refresh_chain=False)['external_proof_verified']
    (root/'market-acceptance.public.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
    if args.replace_market:
        backup=root/'previous-market.sqlite3'
        with sqlite3.connect(DB_PATH) as live,sqlite3.connect(backup) as dest:live.backup(dest)
        backup.chmod(0o600)
        # Copy immutable receipts/data to the application's fixed storage roots.
        for table, column, source_root, target_root in [('qj_zk_proofs','receipt_path',staging/'receipts',DATA_DIR/'zk_receipts'),('qj_market_datasets','dataset_path',staging/'market',DATA_DIR/'zk_market')]:
            target_root.mkdir(exist_ok=True,parents=True)
            with sqlite3.connect(db) as staged:
                for (source_path,) in staged.execute(f'SELECT {column} FROM {table}').fetchall():
                    source_path=Path(source_path);destination=target_root/source_path.name
                    if destination.exists() and destination.read_bytes()!=source_path.read_bytes():
                        raise ValueError('Content-addressed file collision')
                    shutil.copy2(source_path,destination)
                    staged.execute(f'UPDATE {table} SET {column}=? WHERE {column}=?',(str(destination.resolve()),str(source_path)))
        # Keep all previous files for rollback.
        with sqlite3.connect(DB_PATH) as live:
            live.execute('PRAGMA foreign_keys=OFF')
            live.execute('ATTACH DATABASE ? AS staged',(str(db),))
            live.execute('BEGIN IMMEDIATE')
            live.execute('CREATE TABLE IF NOT EXISTS qj_public_programs (proof_id TEXT PRIMARY KEY REFERENCES qj_zk_proofs(id) ON DELETE CASCADE,source TEXT NOT NULL,witness_json TEXT NOT NULL)')
            tables=[r[0] for r in live.execute("SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'qj_*'")]
            for table in tables:live.execute(f'DELETE FROM "{table}"')
            for table in ['qj_agents','qj_market_datasets','qj_zk_proofs','qj_reports','qj_public_programs']:
                columns=[r[1] for r in live.execute(f'PRAGMA table_info("{table}")')]
                quoted=','.join('"'+c+'"' for c in columns)
                live.execute(f'INSERT INTO "{table}" ({quoted}) SELECT {quoted} FROM staged."{table}"')
            live.commit()
        print(f'本地策略市场已替换为3个真实证明策略。备份：{backup}',flush=True)
    print(root/'market-acceptance.public.json',flush=True)

if __name__=='__main__':main()
