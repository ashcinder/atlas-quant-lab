"""Explicit publication of immutable public reports and already-verified receipts.

This is called only after an author's existing report-publish operation succeeds.
The registry is a public-download allowlist; arbitrary files in the object root,
private strategy inputs and offline witness bundles are never exposed here.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.compute_objects import ComputeObjects, canonical_bytes
from app.zkp import MAX_RECEIPT_BYTES
from app.zkp_models import ZkPublicStatement

_MAX_JSON_BYTES = 16 * 1024 * 1024
_MEDIA = {'json': 'application/json', 'r0': 'application/octet-stream'}
_REPORT_FIELDS = (
    'id', 'report_type', 'period_start', 'period_end', 'decision_count',
    'decision_merkle_root', 'market_data_hash', 'previous_receipt_hash',
    'receipt_hash', 'attestation_key_id', 'attestation_signature', 'zk_proof_id',
    'evidence_level', 'chain_tx_hash', 'chain_status', 'chain_block_number',
    'created_at', 'receipt_integrity_valid', 'public_curve_integrity_valid',
    'score', 'score_version', 'performance_score', 'performance_score_version',
)
_METRIC_FIELDS = ('total_return', 'annualized_return', 'max_drawdown', 'annualized_volatility',
                  'sharpe', 'win_rate', 'benchmark_return', 'observation_count', 'live_days')
_EXTERNAL_FIELDS = ('proof_type', 'proof_profile', 'proof_id', 'proof_hash', 'public_inputs_hash',
                    'image_id', 'verifier', 'verifier_version', 'receipt_kind')
_PROOF_FIELDS = ('id', 'agent_id', 'proof_profile', 'image_id', 'public_inputs_hash', 'proof_hash',
                 'receipt_size', 'receipt_kind', 'verifier_version', 'nullifier', 'status',
                 'verified_at', 'created_at')


def _pick(record: dict, fields) -> dict:
    # Explicit scalar projection also blocks an unexpected nested object from
    # smuggling private fields through otherwise-public metadata names.
    return {key: record[key] for key in fields if key in record and
            (record[key] is None or isinstance(record[key], (str, int, float, bool)))}


class PublicArtifacts:
    def __init__(self, reports, proofs, objects: ComputeObjects | None = None, path: Path | None = None):
        self.reports, self.proofs = reports, proofs
        self.objects = objects or ComputeObjects()
        self.path = path or reports.path
        self.root = self.objects.root / 'artifacts-public'
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS public_artifact_files (digest TEXT NOT NULL, suffix TEXT NOT NULL, PRIMARY KEY(digest,suffix))')
            db.execute('CREATE TABLE IF NOT EXISTS public_report_exports (report_id TEXT PRIMARY KEY, proof_id TEXT, report_digest TEXT NOT NULL, receipt_digest TEXT)')

    def _connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def _path(self, digest: str, suffix: str) -> Path:
        if suffix not in _MEDIA or not re.fullmatch(r'[a-f0-9]{64}', digest):
            raise ValueError('无效公共制品标识')
        return self.root / f'{digest}.{suffix}'

    def _read(self, digest: str, suffix: str) -> bytes:
        path = self._path(digest, suffix)
        if path.is_symlink() or not path.is_file():
            raise ValueError('公共制品不存在')
        limit = MAX_RECEIPT_BYTES if suffix == 'r0' else _MAX_JSON_BYTES
        with path.open('rb') as handle:
            content = handle.read(limit + 1)
        if len(content) > limit or not hmac.compare_digest(hashlib.sha256(content).hexdigest(), digest):
            raise ValueError('公共制品完整性检查失败')
        return content

    def _upload(self, path: Path, suffix: str):
        destination = os.environ.get('ATLAS_PUBLIC_ARTIFACT_S3_URI', '')
        if not destination:
            return
        if not re.fullmatch(r's3://[a-zA-Z0-9.-]+(?:/[a-zA-Z0-9_./-]*)?', destination):
            raise ValueError('公共制品对象存储地址必须是明确的 s3://bucket/prefix')
        command = ['aws']
        endpoint = os.environ.get('ATLAS_S3_ENDPOINT_URL')
        if endpoint:
            if not endpoint.startswith('https://'):
                raise ValueError('对象存储端点需要HTTPS')
            command.extend(['--endpoint-url', endpoint])
        command.extend(['s3', 'cp', str(path), f'{destination.rstrip("/")}/{path.name}',
                        '--content-type', _MEDIA[suffix], '--cache-control',
                        'public,max-age=31536000,immutable', '--only-show-errors'])
        try:
            subprocess.run(command, check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            raise ValueError('公共制品上传失败；原报告和证明保留') from None

    def _put(self, content: bytes, suffix: str) -> str:
        limit = MAX_RECEIPT_BYTES if suffix == 'r0' else _MAX_JSON_BYTES
        if not content or len(content) > limit:
            raise ValueError('公共制品为空或超过大小限制')
        digest = hashlib.sha256(content).hexdigest()
        destination = self._path(digest, suffix)
        if destination.exists():
            self._read(digest, suffix)
        else:
            fd, temporary = tempfile.mkstemp(dir=self.root, prefix='.publishing-')
            try:
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, destination)
            finally:
                Path(temporary).unlink(missing_ok=True)
        self._upload(destination, suffix)
        return digest

    def _url(self, digest: str, suffix: str) -> str:
        self._path(digest, suffix)
        prefix = os.environ.get('ATLAS_PUBLIC_ARTIFACT_URL', '/api/v1/public-artifacts').rstrip('/')
        if not (prefix.startswith('https://') or (prefix.startswith('/') and not prefix.startswith('//'))):
            raise ValueError('公共制品URL必须为HTTPS或站内路径')
        return f'{prefix}/{digest}.{suffix}'

    def publish_report(self, report_id: str) -> dict:
        report = self.reports.get_report(report_id)  # Only deliberately published qj_reports exist here.
        if report.get('id') != report_id:
            raise ValueError('报告身份不匹配')
        verified = self.reports.verify_report(report_id, refresh_chain=False)
        if (verified.get('report_id') != report_id or not all(verified.get(key) is True for key in
            ('receipt_hash_valid', 'attestation_signature_valid', 'record_integrity_valid')) or
                verified.get('public_curve_integrity_valid') is False):
            raise ValueError('已发布报告完整性校验失败，未导出公共制品')
        safe = _pick(report, _REPORT_FIELDS)
        safe['metrics'] = _pick(report.get('metrics') or {}, _METRIC_FIELDS)
        safe['public_curve'] = [_pick(point, ('time', 'return', 'benchmark_return')) for point in report.get('public_curve', [])]
        safe['external_proof'] = _pick(report.get('external_proof') or {}, _EXTERNAL_FIELDS) or None
        document = {'schema': 'atlas.public-report/v1', 'report': safe}
        proof_id = report.get('zk_proof_id')
        receipt_digest = None
        if proof_id:
            # verify_report performs the existing real receipt re-verification and
            # report binding checks. Never replace it with a stored status or hash.
            if not all(verified.get(key) is True for key in
                       ('external_proof_verified', 'proof_file_integrity_valid', 'proof_cryptographic_valid')):
                raise ValueError('报告未通过真实Proof和报告绑定验证，未导出receipt')
            proof = self.proofs.get(proof_id)
            with self.proofs._connect() as db:
                binding = db.execute('SELECT report_id FROM qj_zk_proofs WHERE id=? AND status=\'verified\'', (proof_id,)).fetchone()
            if binding is None or binding['report_id'] != report_id or proof.get('status') != 'verified':
                raise ValueError('Proof不属于当前已发布报告')
            statement = ZkPublicStatement.model_validate(proof['public_statement']).model_dump(mode='json', by_alias=True)
            receipt_path = self.proofs.receipt_path(proof_id)
            with receipt_path.open('rb') as handle:
                receipt = handle.read(MAX_RECEIPT_BYTES + 1)
            if not hmac.compare_digest(hashlib.sha256(receipt).hexdigest(), str(proof.get('proof_hash', ''))):
                raise ValueError('原始receipt内容哈希不匹配')
            receipt_digest = self._put(receipt, 'r0')
            document['proof'] = {**_pick(proof, _PROOF_FIELDS), 'public_statement': statement,
                                 'receipt_url': self._url(receipt_digest, 'r0')}
        elif report.get('evidence_level') == 'zk_verified':
            raise ValueError('ZKP报告缺少已绑定Proof')
        report_digest = self._put(canonical_bytes(document), 'json')
        # Register only after all integrity checks and configured uploads succeed.
        with self._connect() as db:
            db.execute('INSERT OR IGNORE INTO public_artifact_files VALUES (?,?)', (report_digest, 'json'))
            if receipt_digest:
                db.execute('INSERT OR IGNORE INTO public_artifact_files VALUES (?,?)', (receipt_digest, 'r0'))
            db.execute('INSERT OR REPLACE INTO public_report_exports VALUES (?,?,?,?)', (report_id, proof_id, report_digest, receipt_digest))
        return self.for_report(report_id)

    def for_report(self, report_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute('SELECT report_digest,receipt_digest FROM public_report_exports WHERE report_id=?', (report_id,)).fetchone()
        if row is None:
            return None
        result = {'report_url': self._url(row[0], 'json'), 'report_sha256': row[0]}
        if row[1]:
            result.update(receipt_url=self._url(row[1], 'r0'), receipt_sha256=row[1])
        return result

    def for_proof(self, proof_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute('SELECT report_id FROM public_report_exports WHERE proof_id=?', (proof_id,)).fetchone()
        return self.for_report(row[0]) if row else None

    def file(self, digest: str, suffix: str) -> tuple[Path, str]:
        self._path(digest, suffix)
        with self._connect() as db:
            registered = db.execute('SELECT 1 FROM public_artifact_files WHERE digest=? AND suffix=?', (digest, suffix)).fetchone()
        if not registered:
            raise KeyError(digest)
        self._read(digest, suffix)
        return self._path(digest, suffix), _MEDIA[suffix]


def public_artifact_router(artifacts: PublicArtifacts):
    router = APIRouter(prefix='/api/v1')

    @router.get('/public-artifacts/{digest}.{suffix}')
    def download(digest: str, suffix: str):
        try:
            path, media_type = artifacts.file(digest, suffix)
        except (KeyError, ValueError, FileNotFoundError):
            raise HTTPException(404, '公共制品不存在或完整性检查失败') from None
        return FileResponse(path, media_type=media_type, headers={
            'Cache-Control': 'public, max-age=31536000, immutable',
            'Access-Control-Allow-Origin': '*', 'ETag': f'"{digest}"',
            'Content-Disposition': f'attachment; filename="{digest}.{suffix}"',
        })
    return router
