"""Public proof inspection: stored status is never sufficient for verification."""
from datetime import UTC, datetime
import subprocess
import json
from threading import BoundedSemaphore
from time import monotonic
from fastapi import APIRouter, HTTPException
from app.zkp import ZkProofError, ZkVerifierUnavailable
from app.zkp_bindings import init_public_programs, check_public_program

SOURCE = 'https://github.com/ashcinder/atlas-quant-lab/blob/7e38e0930690de8952f1fb2e3f6004321c717907'

def proof_inspection_router(store):
    router = APIRouter(prefix='/api/v1/quantjudge')
    init_public_programs(store)
    slots = BoundedSemaphore(2)

    @router.get('/zk-proofs/{proof_id}/public-example')
    def public_example(proof_id: str):
        # Only deliberately published fixtures are stored in this table.
        # Never read an author's private witness from the filesystem.
        with store._connect() as conn:
            row = conn.execute('SELECT source,witness_json FROM qj_public_programs WHERE proof_id=?', (proof_id,)).fetchone()
        if row is None:
            raise HTTPException(404, '作者未公开测试输入')
        return {'source': row['source'], 'witness': json.loads(row['witness_json']),
                'public_test_strategy': True}

    @router.get('/zk-proofs/{proof_id}/bundle')
    def bundle(proof_id: str):
        from fastapi.responses import Response
        from app.zkp_bundle import export_bundle
        verify(proof_id)
        return Response(export_bundle(store, proof_id), media_type='application/zip',
                        headers={'Content-Disposition': 'attachment; filename=atlas-proof.zip'})

    @router.post('/zk-proofs/{proof_id}/verify')
    def verify(proof_id: str):
        if not slots.acquire(blocking=False):
            raise HTTPException(429, '验证器繁忙，请稍后重试')
        started = monotonic()
        try:
            verified = store.reverify(proof_id)
            record = store.get(proof_id)
            metadata, dataset_path = store.market_dataset(verified.journal['market_data_hash'])
            dataset = json.loads(dataset_path.read_text())['dataset']
            market = {k: dataset[k] for k in ('symbol', 'interval', 'source')}
            market.update(period_start=dataset['bars'][0]['time'], period_end=dataset['bars'][-1]['time'], bar_count=len(dataset['bars']), trust_model=metadata['trust_model'])
            if market['period_start'] != verified.journal['period_start'] or market['period_end'] != verified.journal['period_end']:
                raise ZkProofError('历史数据区间与证明不一致')
            program = check_public_program(store, proof_id, verified.journal)
            with store._connect() as conn:
                reports = [row['id'] for row in conn.execute('SELECT id FROM qj_reports WHERE zk_proof_id=?', (proof_id,))]
            from app.quantjudge import QuantJudgeStore
            quant = QuantJudgeStore(store.path, proof_store=store, seed_demo=False)
            report_checks = []
            for report_id in reports:
                result = quant.verify_report(report_id, refresh_chain=False)
                if not result.get('verification_claims', {}).get('bounded_program_backtest'):
                    raise ZkProofError('市场公开收益与证明报告不一致')
                report_checks.append({'report_id': report_id, 'published_return_verified': True})
            return {'valid': True, 'proof_id': proof_id, 'proof_hash': record['proof_hash'],
                    'image_id': verified.image_id, 'journal': verified.journal,
                    'verified_at': datetime.now(UTC).isoformat(),
                    'verification_seconds': round(monotonic()-started, 3),
                    'market_origin_verified': False,
                    'onchain_verification_checked': False,
                    'market': market,
                    'program': program, 'reports': report_checks,
                    'verifier_source': SOURCE + '/strategy/zkvm/host/src/main.rs',
                    'guest_source': SOURCE + ('/strategy/zkvm/core/src/lib.rs' if record['proof_profile'] == 'atlas_sma_backtest_risc0_v1' else '/strategy/zkvm/program-core/src/lib.rs')}
        except KeyError as exc:
            raise HTTPException(404, '证明不存在') from exc
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise HTTPException(503, '程序绑定验证暂不可用') from exc
        except ZkVerifierUnavailable as exc:
            raise HTTPException(503, '真实证明验证器不可用') from exc
        except ZkProofError as exc:
            raise HTTPException(409, str(exc)) from exc
        finally:
            slots.release()
    return router
