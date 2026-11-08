"""Publication policy tests. Trusted verifier responses are stubbed; no new Proof is generated."""
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.compute_objects import ComputeObjects
from app.public_artifacts import PublicArtifacts, public_artifact_router
from app.quantjudge import QuantJudgeStore, ReceiptAttestor
from app.quantjudge_models import PerformanceReportCreate, QuantAgentCreate
from app.zkp_models import ZkPublicStatement

SECRET = 'NEVER_EXPORT_AUTHOR_PRIVATE_WITNESS_TOKEN_SNAPSHOT'


class PublishedReports:
    def __init__(self, path, linked=True):
        self.path = path
        self.report = {'id': 'qjr_public', 'report_type': 'backtest', 'period_start': '2025-01-01T00:00:00Z',
                       'period_end': '2025-01-02T00:00:00Z', 'metrics': {'total_return': .1, 'snapshot': SECRET},
                       'public_curve': [{'time': 1735689600, 'return': 0., 'benchmark_return': 0., 'private': SECRET}],
                       'receipt_integrity_valid': True, 'public_curve_integrity_valid': True,
                       'receipt_hash': 'a' * 64, 'evidence_level': 'zk_verified' if linked else 'platform_computed',
                       'zk_proof_id': 'qzp_public' if linked else None, 'developer_token': SECRET,
                       'author.private.json': SECRET, 'witness': SECRET, 'snapshot': SECRET}
        self.verification = {key: True for key in ('receipt_hash_valid', 'attestation_signature_valid',
                                                  'record_integrity_valid', 'public_curve_integrity_valid',
                                                  'external_proof_verified', 'proof_file_integrity_valid', 'proof_cryptographic_valid')}
        self.verification['report_id'] = 'qjr_public'
        self.calls = []

    def get_report(self, identifier):
        if identifier != self.report['id']:
            raise KeyError(identifier)
        return deepcopy(self.report)

    def verify_report(self, identifier, *, refresh_chain):
        self.calls.append((identifier, refresh_chain))
        return deepcopy(self.verification)


class PublishedProofs:
    def __init__(self, root, database):
        self.path = database
        self.receipt = root / 'original.r0'
        self.receipt.write_bytes(b'opaque-existing-verified-receipt-bytes')
        statement = ZkPublicStatement.model_validate({
            'schema': 'atlas.quantjudge.zk.statement.v1', 'proof_profile': 'atlas_sma_backtest_risc0_v1',
            'agent_id': 'qja_fixture', 'strategy_commitment': '1' * 64, 'workflow_commitment': '2' * 64,
            'market_data_hash': '3' * 64, 'cost_model_hash': '4' * 64, 'report_type': 'backtest',
            'period_start': 1735689600, 'period_end': 1735776000, 'initial_equity_micros': 100000000,
            'final_equity_micros': 110000000, 'decision_count': 2, 'decision_merkle_root': '5' * 64,
            'equity_curve_hash': '0' * 64, 'previous_receipt_hash': None, 'nullifier': '6' * 64,
            'metrics': {'total_return_ppm': 100000, 'annualized_return_ppm': 100000,
                        'max_drawdown_ppm': 0, 'annualized_volatility_ppm': 1, 'sharpe_milli': 1000,
                        'win_rate_ppm': 1000000, 'benchmark_return_ppm': 0, 'observation_count': 2},
            'public_curve': [{'time': 1735689600, 'return_ppm': 0, 'benchmark_return_ppm': 0},
                             {'time': 1735776000, 'return_ppm': 100000, 'benchmark_return_ppm': 0}],
        })
        statement = statement.model_copy(update={'equity_curve_hash': statement.curve_commitment()})
        self.proof = {'id': 'qzp_public', 'status': 'verified', 'agent_id': 'qja_fixture',
                      'proof_hash': hashlib.sha256(self.receipt.read_bytes()).hexdigest(),
                      'public_statement': {**statement.model_dump(mode='json', by_alias=True), 'witness': SECRET},
                      'receipt_path': SECRET, 'developer_token': SECRET, 'snapshot': SECRET}
        with self._connect() as db:
            db.execute('CREATE TABLE qj_zk_proofs (id TEXT PRIMARY KEY,status TEXT,report_id TEXT)')
            db.execute("INSERT INTO qj_zk_proofs VALUES ('qzp_public','verified','qjr_public')")

    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def get(self, identifier):
        if identifier != self.proof['id']:
            raise KeyError(identifier)
        return deepcopy(self.proof)

    def receipt_path(self, identifier):
        assert identifier == self.proof['id']
        return self.receipt


@pytest.fixture
def publication(tmp_path, monkeypatch):
    for variable in ('ATLAS_PUBLIC_ARTIFACT_URL', 'ATLAS_PUBLIC_ARTIFACT_S3_URI', 'ATLAS_S3_ENDPOINT_URL'):
        monkeypatch.delenv(variable, raising=False)
    reports = PublishedReports(tmp_path / 'state.sqlite')
    proofs = PublishedProofs(tmp_path, reports.path)
    store = PublicArtifacts(reports, proofs, ComputeObjects(tmp_path / 'objects'))
    return SimpleNamespace(store=store, reports=reports, proofs=proofs)


def test_publishes_only_safe_public_report_statement_and_exact_raw_receipt(publication):
    result = publication.store.publish_report('qjr_public')
    assert publication.reports.calls == [('qjr_public', False)]
    assert result['report_url'].endswith('.json') and result['receipt_url'].endswith('.r0')
    report_path, media = publication.store.file(result['report_sha256'], 'json')
    assert media == 'application/json'
    assert SECRET not in report_path.read_text()
    document = json.loads(report_path.read_text())
    assert document['report']['metrics'] == {'total_return': .1}
    assert 'witness' not in document['proof']['public_statement']
    assert 'bundle_url' not in result
    receipt_path, media = publication.store.file(result['receipt_sha256'], 'r0')
    assert media == 'application/octet-stream'
    assert receipt_path.read_bytes() == publication.proofs.receipt.read_bytes()
    assert hashlib.sha256(receipt_path.read_bytes()).hexdigest() == result['receipt_sha256']
    assert publication.store.for_proof('qzp_public') == result
    assert publication.store.publish_report('qjr_public') == result


def test_unpublished_or_unlinked_proof_never_has_public_url(publication):
    assert publication.store.for_proof('qzp_public') is None
    with pytest.raises(KeyError):
        publication.store.publish_report('not-published')
    with publication.proofs._connect() as db:
        db.execute("UPDATE qj_zk_proofs SET report_id=NULL")
    with pytest.raises(ValueError, match='不属于'):
        publication.store.publish_report('qjr_public')
    assert publication.store.for_report('qjr_public') is None


@pytest.mark.parametrize('key', ['receipt_hash_valid', 'attestation_signature_valid', 'record_integrity_valid',
                                  'public_curve_integrity_valid', 'external_proof_verified',
                                  'proof_file_integrity_valid', 'proof_cryptographic_valid'])
def test_integrity_or_real_verification_failure_prevents_export(publication, key):
    publication.reports.verification[key] = False
    with pytest.raises(ValueError):
        publication.store.publish_report('qjr_public')
    assert publication.store.for_report('qjr_public') is None
    assert list(publication.store.root.iterdir()) == []


def test_receipt_mutation_rejected_even_after_verified_report_response(publication):
    publication.proofs.receipt.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='哈希'):
        publication.store.publish_report('qjr_public')
    assert publication.store.for_proof('qzp_public') is None


def test_download_registry_cache_cors_hash_and_corruption(publication):
    result = publication.store.publish_report('qjr_public')
    app = FastAPI()
    app.include_router(public_artifact_router(publication.store))
    client = TestClient(app)
    for key in ('report', 'receipt'):
        response = client.get(result[f'{key}_url'])
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'public, max-age=31536000, immutable'
        assert response.headers['access-control-allow-origin'] == '*'
        assert response.headers['etag'] == f'"{result[f"{key}_sha256"]}"'
        assert hashlib.sha256(response.content).hexdigest() == result[f'{key}_sha256']
    unregistered = publication.store._put(b'{"private":"still-not-downloadable"}', 'json')
    assert client.get(f'/api/v1/public-artifacts/{unregistered}.json').status_code == 404
    assert client.get(f'/api/v1/public-artifacts/{result["receipt_sha256"]}.json').status_code == 404
    path, _ = publication.store.file(result['receipt_sha256'], 'r0')
    path.write_bytes(b'corrupt published bytes')
    assert client.get(result['receipt_url']).status_code == 404
    assert client.get('/api/v1/public-artifacts/invalid.r0').status_code == 404
    assert client.get(f'/api/v1/public-artifacts/{unregistered}.zip').status_code == 404
    client.close()


def test_explicit_s3_upload_keeps_types_and_does_not_publish_unregistered_failure(publication, monkeypatch):
    calls = []
    monkeypatch.setenv('ATLAS_PUBLIC_ARTIFACT_S3_URI', 's3://public-bucket/artifacts')
    monkeypatch.setenv('ATLAS_PUBLIC_ARTIFACT_URL', 'https://cdn.example.test/artifacts')
    monkeypatch.setenv('ATLAS_S3_ENDPOINT_URL', 'https://objects.example.test')
    monkeypatch.setattr('app.public_artifacts.subprocess.run', lambda command, **options: calls.append((command, options)))
    result = publication.store.publish_report('qjr_public')
    assert result['report_url'].startswith('https://cdn.example.test/artifacts/')
    assert len(calls) == 2
    for command, options in calls:
        assert command[:3] == ['aws', '--endpoint-url', 'https://objects.example.test']
        assert '--only-show-errors' in command
        suffix = Path(command[5]).suffix
        expected_type = 'application/octet-stream' if suffix == '.r0' else 'application/json'
        assert command[command.index('--content-type') + 1] == expected_type
        assert options['check'] is True and options['timeout'] == 60
    monkeypatch.setattr('app.public_artifacts.subprocess.run', lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired('aws', 60)))
    with pytest.raises(ValueError, match='原报告和证明保留'):
        publication.store.publish_report('qjr_public')
    assert publication.store.for_report('qjr_public') == result


def test_real_plain_report_exports_without_claiming_zkp(tmp_path, monkeypatch):
    monkeypatch.delenv('ATLAS_PUBLIC_ARTIFACT_S3_URI', raising=False)
    quant = QuantJudgeStore(tmp_path / 'plain.sqlite', attestor=ReceiptAttestor(tmp_path / 'attestor.key'), seed_demo=False)
    created = quant.create_agent(QuantAgentCreate(name='Public fixture', developer_alias='Fixture author', category='timing', asset_classes=['crypto'], description='Synthetic test report; no private source or witness.', strategy_commitment='7' * 64))
    report = quant.publish_report(created['agent']['id'], PerformanceReportCreate(report_type='backtest', period_start=datetime(2025, 1, 1, tzinfo=UTC), period_end=datetime(2025, 1, 2, tzinfo=UTC), equity_points=[{'time': 1735689600, 'equity': 100}, {'time': 1735776000, 'equity': 110}], decision_commitments=['8' * 64], market_data_hash='9' * 64), created['developer_token'])
    artifacts = PublicArtifacts(quant, None, ComputeObjects(tmp_path / 'plain-objects'))
    output = artifacts.publish_report(report['id'])
    assert 'receipt_url' not in output
    path, _ = artifacts.file(output['report_sha256'], 'json')
    exported = json.loads(path.read_text())
    assert exported['report']['zk_proof_id'] is None
    assert 'proof' not in exported
    assert created['developer_token'] not in path.read_text()


def test_first_upload_failure_does_not_register_public_downloads(publication, monkeypatch):
    monkeypatch.setenv('ATLAS_PUBLIC_ARTIFACT_S3_URI', 's3://public-bucket/artifacts')
    monkeypatch.setattr('app.public_artifacts.subprocess.run', lambda *a, **kw: (_ for _ in ()).throw(OSError('unavailable')))
    with pytest.raises(ValueError, match='原报告和证明保留'):
        publication.store.publish_report('qjr_public')
    assert publication.store.for_report('qjr_public') is None
    assert publication.store.for_proof('qzp_public') is None
    with publication.store._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM public_artifact_files').fetchone()[0] == 0
    assert publication.proofs.receipt.read_bytes() == b'opaque-existing-verified-receipt-bytes'
