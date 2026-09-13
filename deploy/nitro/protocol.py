"""Public envelope and bounded, framed vsock protocol. No plaintext fallback."""
import base64
import hashlib
import json
import os
import re
import struct
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

LIMIT = 2 * 1024 * 1024

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def b64(value):
    return base64.b64encode(value).decode()

def unb64(value):
    return base64.b64decode(value, validate=True)

def header(envelope):
    value = envelope['header']
    if set(value) != {'version', 'key_arn', 'package_id'} or value['version'] != 1:
        raise ValueError('Invalid envelope')
    if not re.fullmatch(r'arn:aws:kms:[a-z0-9-]+:\d{12}:key/[a-f0-9-]+', value['key_arn']):
        raise ValueError('Use a full KMS key ARN, never an alias')
    if not re.fullmatch(r'[a-f0-9]{64}', value['package_id']):
        raise ValueError('Invalid package ID')
    return value

def context(envelope):
    return {'atlas:package': header(envelope)['package_id'], 'atlas:purpose': 'confidential-strategy-v1'}

def seal(payload, key_arn, kms):
    # A random ID does not reveal the source hash, file name or parameters.
    envelope = {'header': {'version': 1, 'key_arn': key_arn, 'package_id': os.urandom(32).hex()}}
    key, nonce = os.urandom(32), os.urandom(12)
    wrapped = kms.encrypt(KeyId=key_arn, Plaintext=key, EncryptionContext=context(envelope))
    envelope.update(wrapped_key=b64(wrapped['CiphertextBlob']), nonce=b64(nonce),
                    ciphertext=b64(AESGCM(key).encrypt(nonce, canonical(payload), canonical(header(envelope)))))
    return envelope

def open_payload(envelope, key):
    return json.loads(AESGCM(key).decrypt(unb64(envelope['nonce']), unb64(envelope['ciphertext']), canonical(header(envelope))))

def receive(stream):
    def exact(count):
        data = bytearray()
        while len(data) < count:
            chunk = stream.recv(count - len(data))
            if not chunk:
                raise EOFError('Closed channel')
            data.extend(chunk)
        return bytes(data)
    size = struct.unpack('!I', exact(4))[0]
    if not 0 < size <= LIMIT:
        raise ValueError('Oversized frame')
    return json.loads(exact(size))

def send(stream, value):
    body = canonical(value)
    if len(body) > LIMIT:
        raise ValueError('Oversized frame')
    stream.sendall(struct.pack('!I', len(body)) + body)

def validate_payload(payload):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    source = payload['source'].encode()
    if not 0 < len(source) <= 256_000:
        raise ValueError('Invalid source size')
    commitment = hashlib.sha256(bytes.fromhex(payload['salt']) + source).hexdigest()
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(payload['signing_key']))
    expected = hashlib.sha256(canonical({'execution_mode': 'private_runner',
        'runner_public_key': key.public_key().public_bytes_raw().hex(), 'code_commitment': commitment})).hexdigest()
    if payload['config']['content_hash'] != expected:
        raise ValueError('Source and registered release differ')
    if not re.fullmatch(r'run_[a-f0-9]{18}', payload['config']['run_id']) or not re.fullmatch(r'rel_[a-f0-9]{18}', payload['config']['release_id']):
        raise ValueError('Invalid binding')
    if not isinstance(payload['interval'], int) or not 10 <= payload['interval'] <= 3600:
        raise ValueError('Invalid interval')
    return key
