"""Local crypto/policy/protocol checks. These do NOT emulate successful Nitro attestation."""
import importlib.util
import json
import os
import socket
import struct
import sys
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / 'deploy/nitro'
sys.path.insert(0, str(DIR))
from protocol import canonical, context, header, open_payload, receive, seal, send, validate_payload
from key_policy import policy
from enclave import unwrap_cms

ARN = 'arn:aws:kms:us-east-1:111111111111:key/12345678-abcd-1234-abcd-123456789012'

class KMS:
    """Only envelope roundtrip stub. No attestation or KMS-authorization claim."""
    def encrypt(self, **kw):
        self.request = kw
        return {'CiphertextBlob': b'opaque-wrapped-key'}

def test_ciphertext_and_authenticated_header():
    kms = KMS()
    sealed = seal({'source': 'SECRET_STRATEGY'}, ARN, kms)
    assert 'SECRET_STRATEGY' not in json.dumps(sealed)
    assert kms.request['EncryptionContext'] == context(sealed)
    assert open_payload(sealed, kms.request['Plaintext']) == {'source': 'SECRET_STRATEGY'}
    sealed['header']['package_id'] = 'f' * 64
    with pytest.raises(InvalidTag):
        open_payload(sealed, kms.request['Plaintext'])

def test_wrong_key_and_tamper_rejected():
    kms = KMS()
    sealed = seal({'source': 'secret'}, ARN, kms)
    with pytest.raises(InvalidTag):
        open_payload(sealed, os.urandom(32))
    sealed['ciphertext'] = ('B' if sealed['ciphertext'][0] == 'A' else 'A') + sealed['ciphertext'][1:]
    with pytest.raises(InvalidTag):
        open_payload(sealed, kms.request['Plaintext'])

def test_policy_requires_author_separation_and_non_debug_pins():
    author = 'arn:aws:iam::111111111111:role/Author'
    runner = 'arn:aws:iam::222222222222:role/Runner'
    pins = {f'PCR{i}': str(i+1) * 96 for i in range(3)}
    result = policy(author, runner, pins)
    allowed = [s for s in result['Statement'] if s['Effect'] == 'Allow' and s['Principal']['AWS'] == runner]
    assert len(allowed) == 1 and allowed[0]['Action'] == 'kms:Decrypt'
    assert len(allowed[0]['Condition']['StringEqualsIgnoreCase']) == 3
    assert result['Statement'][2]['Effect'] == 'Deny'
    with pytest.raises(ValueError):
        policy(author, author, pins)
    pins['PCR0'] = '0' * 96
    with pytest.raises(ValueError):
        policy(author, runner, pins)

def test_frame_roundtrip_and_oversize_rejection():
    a, b = socket.socketpair()
    with a, b:
        send(a, {'kind': 'signal'})
        assert receive(b) == {'kind': 'signal'}
        a.sendall(struct.pack('!I', 3 * 1024 * 1024))
        with pytest.raises(ValueError):
            receive(b)

def test_source_binding_and_config():
    import hashlib
    key = Ed25519PrivateKey.generate()
    source, salt = 'def decide(ctx): return "0"', os.urandom(32)
    commitment = hashlib.sha256(salt + source.encode()).hexdigest()
    binding = hashlib.sha256(canonical({'execution_mode': 'private_runner', 'runner_public_key': key.public_key().public_bytes_raw().hex(), 'code_commitment': commitment})).hexdigest()
    payload = {'source': source, 'salt': salt.hex(), 'signing_key': key.private_bytes_raw().hex(),
        'interval': 10, 'config': {'run_id': 'run_' + '1'*18, 'release_id': 'rel_'+'2'*18, 'content_hash': binding}}
    validate_payload(payload)
    payload['source'] += '\n# tampered'
    with pytest.raises(ValueError):
        validate_payload(payload)

def test_cms_recipient_key_roundtrip(tmp_path):
    """Actual RSA-OAEP/SHA256 CMS encryption/decryption; not a KMS API mock claim."""
    import datetime
    import subprocess
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import Encoding
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, 'local-crypto-test')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1)).sign(key, hashes.SHA256())
    path = tmp_path / 'cert.pem'
    path.write_bytes(cert.public_bytes(Encoding.PEM))
    data = os.urandom(32)
    encrypted = subprocess.run(['openssl', 'cms', '-encrypt', '-binary', '-outform', 'DER', '-aes-256-cbc', '-recip', str(path), '-keyopt', 'rsa_padding_mode:oaep', '-keyopt', 'rsa_oaep_md:sha256'], input=data, capture_output=True, check=True).stdout
    assert unwrap_cms(encrypted, key) == data
    with pytest.raises(subprocess.CalledProcessError):
        unwrap_cms(encrypted, rsa.generate_private_key(public_exponent=65537, key_size=2048))

def test_no_hardware_fails_closed(monkeypatch):
    import enclave
    monkeypatch.setattr(enclave.os.path, 'exists', lambda _: False)
    with pytest.raises(SystemExit, match='NSM_REQUIRED'):
        enclave.main()
