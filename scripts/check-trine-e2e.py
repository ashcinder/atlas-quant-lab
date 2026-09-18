"""Read-only inspection of the last real local Trine end-to-end acceptance."""
import json, sqlite3, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.config import DB_PATH
from app.zkp import ZkProofStore
summary=json.loads((ROOT/'docs/TRINE_E2E_LIVE_STATUS.json').read_text())
c=sqlite3.connect(DB_PATH);c.row_factory=sqlite3.Row
job=c.execute('SELECT status,proof_id,error,updated_at-created_at AS seconds FROM cloud_proof_jobs WHERE id=?',(summary['job_id'],)).fetchone()
run=c.execute('SELECT status,environment,symbol,quantity,cash,latest_error FROM strategy_runs WHERE id=?',(summary['run_id'],)).fetchone()
proof_valid=False
if job and job['status']=='verified':
 ZkProofStore().reverify(job['proof_id']);proof_valid=True
payments=[dict(r) for r in c.execute('SELECT kind,status,amount_wei,transaction_hash FROM bkc_orders WHERE transaction_hash IN (?,?)',(summary['proof_payment'],summary['subscription_payment']))]
fills=[dict(r) for r in c.execute('SELECT * FROM strategy_external_fills WHERE run_id=?',(summary['run_id'],))]
for item in fills:item.pop('owner_id',None)
print(json.dumps({'proof':dict(job) if job else None,'proof_reverified':proof_valid,'payments':payments,'run':dict(run) if run else None,'exchange_fills':fills},ensure_ascii=False,indent=2))
