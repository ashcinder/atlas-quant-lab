from pathlib import Path
import runpy

import pytest

anchor_intent = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts/anchor-zk-report.py'))['anchor_intent']


@pytest.mark.parametrize('failed', ['external_proof_verified', 'proof_cryptographic_valid',
                                  'receipt_hash_valid', 'record_integrity_valid'])
def test_cannot_prepare_anchor_for_unverified_or_tampered_report(failed):
    class UnverifiedReport:
        def verify_report(self, *args, **kwargs):
            return {key: key != failed for key in ['external_proof_verified',
                    'proof_cryptographic_valid', 'receipt_hash_valid', 'record_integrity_valid']}

        def _connect(self):
            pytest.fail('必须在读取锚定内容前拒绝验证失败的报告')

    with pytest.raises(ValueError):
        anchor_intent(UnverifiedReport(), 'unverified')
