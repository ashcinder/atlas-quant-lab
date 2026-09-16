"""Public example-code binding; no unverified source is advertised as proved."""
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from app.zk_python import compile_strategy, UnsupportedStrategy
from app.zkp import DEFAULT_VERIFIER, ZkProofError


def init_public_programs(store):
    with store._connect() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS qj_public_programs (
            proof_id TEXT PRIMARY KEY REFERENCES qj_zk_proofs(id) ON DELETE CASCADE,
            source TEXT NOT NULL, witness_json TEXT NOT NULL)''')


def check_public_program(store, proof_id, journal):
    with store._connect() as conn:
        row = conn.execute('SELECT source,witness_json FROM qj_public_programs WHERE proof_id=?', (proof_id,)).fetchone()
    if row is None:
        return None
    source, witness = row['source'], json.loads(row['witness_json'])
    try:
        compiled = compile_strategy(source)
    except UnsupportedStrategy as exc:
        raise ZkProofError('公开策略源码不符合证明协议') from exc
    if compiled != witness['strategy']['program']:
        raise ZkProofError('公开策略源码与承诺的程序不一致')
    with tempfile.TemporaryDirectory(prefix='atlas-public-binding-') as directory:
        path = Path(directory)/'witness.json'; path.write_text(json.dumps(witness))
        checked = subprocess.run([str(DEFAULT_VERIFIER), 'inspect', '--profile', journal['proof_profile'], '--witness', str(path)],
                                 capture_output=True, text=True, timeout=60, env={'PATH': os.environ.get('PATH',''), 'RISC0_DEV_MODE':'0'})
    if checked.returncode or json.loads(checked.stdout) != journal:
        raise ZkProofError('公开策略、标的、区间或成本与证明结果不一致')
    return {'source': source, 'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'language': 'atlas-python-subset-v2', 'compiled_program_commitment_verified': True,
            'compiler_inside_zkvm': False, 'public_test_strategy': True,
            'commission_bps': witness['strategy']['commission_bps'], 'slippage_bps': witness['strategy']['slippage_bps']}
