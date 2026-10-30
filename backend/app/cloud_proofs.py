"""Paid, durable native zkVM jobs. Local author tools remain independent."""
import json, os, re, secrets, signal, subprocess, sys, tempfile, threading, time
from pathlib import Path
from uuid import uuid4
from decimal import Decimal, ROUND_CEILING
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from app.bkc_payments import BkcStore, CHAIN_ID, canonical
from app.config import DATA_DIR
from app.zk_author import PROFILE, WORKFLOW
from app.zkp import load_profiles
from app.work_limits import work_limits


def prover_memory_ready():
    """Do not accept payment in the verification-only 2 GiB API profile."""
    for path in ('/sys/fs/cgroup/memory.max', '/sys/fs/cgroup/memory/memory.limit_in_bytes'):
        try:
            value = Path(path).read_text().strip()
        except OSError:
            continue
        if value.isdigit() and int(value) < 6 * 1024**3:
            return False
    return True


def run_proof(command, pass_fds=(), timeout=7200):
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               pass_fds=pass_fds, start_new_session=True)
    try:
        return process.wait(timeout=timeout)
    except BaseException:
        try:os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait()
        raise


def ensure_job_witness(path, proposed, result_dir):
    required=set(proposed)
    def read(candidate):
        try:
            value=json.loads(candidate.read_text())
            return value if isinstance(value,dict) and required<=set(value) else None
        except (OSError,ValueError):return None
    saved=read(path)
    candidate=saved or read(result_dir/'witness.private.json') or proposed
    for key in ('strategy','market','initial_equity_micros','workflow_commitment'):
        if candidate[key]!=proposed[key]:raise RuntimeError('persisted job witness inputs changed')
    if saved is not None:return
    if path.exists():path.rename(path.with_name('incomplete-witness-'+uuid4().hex+'.private.json'))
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,prefix='.witness-',delete=False) as handle:
        temporary=Path(handle.name)
        try:
            json.dump(candidate,handle);handle.flush();os.fsync(handle.fileno())
            os.replace(temporary,path)
        finally:temporary.unlink(missing_ok=True)

def check_paid_proof(proofs, proof_id, result_dir, witness_path, inputs, market_hash):
    verified=proofs.reverify(proof_id)
    saved=json.loads((result_dir/'witness.private.json').read_text())
    original=json.loads(witness_path.read_text())
    for key in ('strategy','market','initial_equity_micros','strategy_salt','nullifier_nonce','workflow_commitment'):
        if saved[key]!=original[key]:raise RuntimeError('job witness mismatch')
    if (saved['strategy']['program']!=inputs['program'] or saved['initial_equity_micros']!=inputs['initial_equity_micros']
            or saved['strategy']['commission_bps']!=inputs['commission_bps'] or saved['strategy']['slippage_bps']!=inputs['slippage_bps']):
        raise RuntimeError('job input mismatch')
    binary=Path(__file__).resolve().parents[2]/'strategy/zkvm/target/release/atlas-zkvm'
    inspected=subprocess.run([str(binary),'inspect','--profile',PROFILE,'--witness',str(result_dir/'witness.private.json')],
                             capture_output=True,text=True,check=True,timeout=60)
    if verified.journal != json.loads(inspected.stdout) or verified.journal['market_data_hash']!=market_hash:
        raise RuntimeError('proof does not bind paid job')


def proof_quote(program, bars, base_bkc):
    """Deterministic work tariff, not a measured cloud-provider bill.

    One base unit covers 32 bars and 64 JSON program nodes. Larger inputs
    scale continuously; the final price rounds up to a micro-BKC.
    """
    def nodes(value):
        if isinstance(value, dict): return 1 + sum(nodes(v) for v in value.values())
        if isinstance(value, list): return 1 + sum(nodes(v) for v in value)
        return 1
    count = nodes(program)
    units = max(Decimal(1), Decimal(bars) / 32 * max(Decimal(1), Decimal(count) / 64))
    amount = (Decimal(base_bkc) * units).quantize(Decimal('0.000001'), rounding=ROUND_CEILING)
    return {'model': 'work-v1', 'bars': bars, 'program_nodes': count,
            'base_bkc': str(base_bkc), 'work_units': str(units.quantize(Decimal('0.0001'))),
            'amount_bkc': format(amount, 'f'), 'amount_wei': str(int(amount * 10**18)),
            'basis': '32 bars × 64 program nodes per base unit', 'locked': True}

class ProofJobInput(BaseModel):
    market_data_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    address: str = Field(pattern=r'^0x[0-9a-fA-F]{40}$')
    initial_equity_micros: int = Field(default=10_000_000_000,gt=0,le=10**15)
    commission_bps: int = Field(default=10,ge=0,le=1000)
    slippage_bps: int = Field(default=5,ge=0,le=1000)
    consent_cloud_source: bool = False

class CloudProofService:
    def __init__(self,runtime,runs,proofs):
        self.runtime,self.proofs=runtime,proofs
        self.payments=BkcStore(runtime,runs)
        self.stop_event=threading.Event();self.thread=None
        self._readiness_cache = None
        self.root=DATA_DIR/'cloud-proofs';self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        with runtime._connect() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS cloud_proof_jobs (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, release_id TEXT NOT NULL,
            market_hash TEXT NOT NULL, inputs TEXT NOT NULL, order_id TEXT UNIQUE,
            status TEXT NOT NULL, proof_id TEXT, error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL)''')
    def config(self):
        recipient=os.getenv('TRINE_PROOF_RECIPIENT','')
        price=os.getenv('TRINE_PROOF_PRICE_BKC','')
        valid=bool(re.fullmatch(r'0x[0-9a-fA-F]{40}',recipient) and int(recipient,16) and re.fullmatch(r'[0-9]+(?:\.[0-9]{1,18})?',price) and Decimal(price)>0)
        binary=Path(__file__).resolve().parents[2]/'strategy/zkvm/target/release/atlas-zkvm'
        ready = False
        reason = '请配置 Proof 服务价格与收款地址'
        if valid:
            cached = self._readiness_cache
            if cached and time.monotonic() - cached[0] < 30:
                ready = cached[1]
            else:
                try:
                    profile = load_profiles()[PROFILE]
                    result = subprocess.run([str(binary), 'profile', '--profile', PROFILE],
                        env={'PATH':os.environ.get('PATH',''), 'RISC0_DEV_MODE':'0', 'RISC0_PROVER':'local'},
                        capture_output=True, text=True, timeout=10, check=True)
                    ready = profile['status'] == 'active' and json.loads(result.stdout)['image_id'] == profile['image_id']
                except (OSError, subprocess.SubprocessError, ValueError, KeyError):
                    ready = False
                self._readiness_cache = (time.monotonic(), ready)
            reason = None if ready else '证明执行器不可用或与已登记程序不匹配'
            if ready and not prover_memory_ready():
                ready = False
                reason = '生成新证明需要至少 6 GiB 的 API 容器内存限额，请先调整部署资源'
        return {'configured':valid and ready,'unavailable_reason':reason,'price_bkc':price if valid else None,'recipient':recipient if valid else None,'currency':'BKC','max_bars':20000,'location':'server','local_tools_preserved':True,'pricing_model':'work-v1','pricing_basis':'每 32 根 K 线 × 64 个程序节点为一个基础计价单位，最低一个单位'}
    def get(self,owner,identifier):
        with self.runtime._connect() as c: row=c.execute('SELECT * FROM cloud_proof_jobs WHERE id=? AND owner_id=?',(identifier,owner)).fetchone()
        if not row: raise HTTPException(404,'证明任务不存在')
        result = {k:v for k,v in dict(row).items() if k not in {'owner_id','inputs'}}
        result['quote'] = json.loads(row['inputs']).get('quote')
        return result
    def list(self,owner,release):
        with self.runtime._connect() as c: rows=c.execute('SELECT id FROM cloud_proof_jobs WHERE owner_id=? AND release_id=? ORDER BY created_at DESC',(owner,release)).fetchall()
        return [self.get(owner,r['id']) for r in rows]
    def create(self,owner,release_id,body):
        config=self.config()
        if not config['configured']: raise HTTPException(503,'云端证明价格、收款地址或证明执行器尚未配置')
        if not body.consent_cloud_source: raise HTTPException(422,'请确认服务器将读取策略程序以生成 Proof')
        release=self.payments.release(owner,release_id,True)
        snapshot=json.loads(release['snapshot'])
        program=snapshot.get('python_program')
        if not program: raise HTTPException(422,'当前 zkVM 支持受限 Python 程序；请将策略保存为可证明 Python 版本')
        try: _,dataset_path=self.proofs.market_dataset(body.market_data_hash)
        except KeyError as exc: raise HTTPException(404,'请先登记有效的历史行情数据集') from exc
        dataset=json.loads(dataset_path.read_text())['dataset']
        if not 3<=len(dataset['bars'])<=20000: raise HTTPException(422,'云端单次证明需要 3–20000 根 K 线')
        quote = proof_quote(program, len(dataset['bars']), config['price_bkc'])
        _,genesis=self.payments.network()
        identifier='cpj_'+uuid4().hex;order='bkc_'+uuid4().hex;now=time.time()
        inputs=body.model_dump();inputs['program']=program;inputs['quote']=quote
        payload={'domain':'trine.cloud-proof/v1','order_id':order,'job_id':identifier,'release_id':release_id,'content_hash':release['content_hash'],'market_data_hash':body.market_data_hash,'chain_id':CHAIN_ID,'genesis_hash':genesis,'initial_equity_micros':body.initial_equity_micros,'commission_bps':body.commission_bps,'slippage_bps':body.slippage_bps,'quote':quote}
        with self.runtime._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            pending=c.execute("SELECT id FROM cloud_proof_jobs WHERE owner_id=? AND release_id=? AND status IN ('awaiting_payment','queued','proving','failed')",(owner,release_id)).fetchone()
            if pending: return self.get(owner,pending['id'])
            c.execute('INSERT INTO bkc_orders (id,owner_id,kind,resource_id,signer,recipient,amount_wei,data,genesis) VALUES (?,?,?,?,?,?,?,?,?)',(order,owner,'proof',identifier,body.address.lower(),config['recipient'].lower(),quote['amount_wei'],'0x'+canonical(payload).encode().hex(),genesis))
            c.execute('INSERT INTO cloud_proof_jobs VALUES (?,?,?,?,?,?,?,NULL,NULL,?,?)',(identifier,owner,release_id,body.market_data_hash,json.dumps(inputs),order,'awaiting_payment',now,now))
        return self.get(owner,identifier)
    def enqueue(self,owner,identifier):
        job=self.get(owner,identifier);order=self.payments.get(owner,job['order_id'])
        if job['status'] in ('queued','proving','verified'):return job
        if not order['transaction_hash']: raise HTTPException(402,'请先支付证明服务费用')
        checked=self.payments.confirm(owner,job['order_id'],order['transaction_hash'])
        if checked['status']!='confirmed': raise HTTPException(402,'BKC 支付尚未确认')
        with self.runtime._connect() as c:
            c.execute("UPDATE cloud_proof_jobs SET status='queued',error=NULL,updated_at=? WHERE id=? AND status IN ('awaiting_payment','failed')",(time.time(),identifier))
        return self.get(owner,identifier)
    def tick(self):
        with self.runtime._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute("SELECT j.* FROM cloud_proof_jobs j JOIN bkc_orders o ON o.id=j.order_id WHERE j.status='queued' AND o.status='confirmed' ORDER BY j.created_at LIMIT 1").fetchone()
            if not row:return
            try:
                work_limits.acquire(row['owner_id'])
            except HTTPException as exc:
                if exc.status_code == 429:return
                raise
            try:
                c.execute("UPDATE cloud_proof_jobs SET status='proving',updated_at=? WHERE id=?",(time.time(),row['id']))
            except Exception:
                work_limits.release(row['owner_id'])
                raise
        directory=self.root/row['id']
        result_dir=directory/'result'
        try:
            directory.mkdir(mode=0o700,exist_ok=True)
            inputs=json.loads(row['inputs']);_,market_path=self.proofs.market_dataset(row['market_hash'])
            witness={'agent_id':'qja_cloud_draft','workflow_commitment':WORKFLOW,'previous_receipt_hash':None,'strategy_salt':list(secrets.token_bytes(32)),'nullifier_nonce':list(secrets.token_bytes(32)),'initial_equity_micros':inputs['initial_equity_micros'],'strategy':{'program':inputs['program'],'commission_bps':inputs['commission_bps'],'slippage_bps':inputs['slippage_bps']},'market':json.loads(market_path.read_text())['dataset']}
            witness_path=directory/'witness.private.json'
            ensure_job_witness(witness_path,witness,result_dir)
            with self.runtime._connect() as c: release=self.runtime._release_for(c,row['release_id'])
            # Incomplete markers are not completion evidence; recover using the same paid job.
            marker=result_dir/'verification.public.json'
            try:result=json.loads(marker.read_text())
            except (OSError,ValueError):result={}
            if not result.get('cryptographically_verified') or not result.get('proof_id'):
                if marker.exists():marker.unlink()
                command=[sys.executable,str(Path(__file__).resolve().parents[2]/'scripts/prove-private-program.py'),'--witness',str(witness_path),'--output',str(result_dir),'--publish-local','--name',release['name']]
                if result_dir.exists():
                    if (result_dir/'author.private.json').is_file() and (result_dir/'witness.private.json').is_file():
                        command.append('--resume')
                    elif not (result_dir/'proof.r0').exists():
                        result_dir.rename(directory/('incomplete-'+uuid4().hex))
                    else:raise RuntimeError('receipt identity missing')
                if run_proof(command,pass_fds=(self.lock_fd,) if hasattr(self,'lock_fd') else ()):
                    raise RuntimeError('prover')
            result=json.loads((result_dir/'verification.public.json').read_text())
            if result.get('cryptographically_verified') is not True or not result.get('proof_id'): raise RuntimeError('verify')
            # Recheck the genuine stored proof rather than trusting a success marker.
            check_paid_proof(self.proofs,result['proof_id'],result_dir,witness_path,inputs,row['market_hash'])
            with self.runtime._connect() as c:
                exists=c.execute('SELECT 1 FROM qj_zk_proofs WHERE id=?',(result['proof_id'],)).fetchone()
                if not exists:raise RuntimeError('missing proof')
                c.execute("UPDATE cloud_proof_jobs SET status='verified',proof_id=?,error=NULL,updated_at=? WHERE id=?",(result['proof_id'],time.time(),row['id']))
        except Exception:
            with self.runtime._connect() as c:c.execute("UPDATE cloud_proof_jobs SET status='failed',error=?,updated_at=? WHERE id=?",('证明生成未完成；费用订单保留，请联系服务方恢复任务，勿重复支付。',time.time(),row['id']))
        finally:
            work_limits.release(row['owner_id'])
    def start(self):
        def run():
            import fcntl
            with open(self.root/'worker.lock','a') as lock:
                while not self.stop_event.is_set():
                    try:
                        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                    except BlockingIOError:self.stop_event.wait(3)
                if self.stop_event.is_set():return
                self.lock_fd=lock.fileno()
                with self.runtime._connect() as c:c.execute("UPDATE cloud_proof_jobs SET status='queued' WHERE status='proving'")
                while not self.stop_event.is_set():
                    try:self.tick()
                    except Exception:pass
                    self.stop_event.wait(3)
        self.thread=threading.Thread(target=run,daemon=True,name='trine-proof-worker');self.thread.start()
    def stop(self):self.stop_event.set()

def cloud_proof_router(service):
    router=APIRouter(prefix='/api/v1')
    @router.get('/cloud-proofs/config')
    def config():return service.config()
    @router.get('/strategy-releases/{release_id}/proof-jobs')
    def jobs(release_id:str,request:Request):return service.list(request.state.user.id,release_id)
    @router.post('/strategy-releases/{release_id}/proof-jobs')
    def create(release_id:str,body:ProofJobInput,request:Request):return service.create(request.state.user.id,release_id,body)
    @router.post('/cloud-proofs/{identifier}/start')
    def start(identifier:str,request:Request):return service.enqueue(request.state.user.id,identifier)
    @router.get('/cloud-proofs/{identifier}')
    def get(identifier:str,request:Request):return service.get(request.state.user.id,identifier)
    return router
