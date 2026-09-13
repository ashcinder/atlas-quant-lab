"""Measured enclave controller: decrypt once, expose only bound signed targets.

Parent is untrusted. Its KMS response is CMS encrypted to an enclave-only key.
No TCP service, plaintext package endpoint, debug fallback or exception logging.
"""
import os
import re
import socket
import subprocess
import tempfile
import time
from uuid import uuid4
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption
from protocol import b64, unb64, canonical, context, header, open_payload, receive, send, validate_payload

def unwrap_cms(ciphertext, key):
    # All enclave filesystem storage is in enclave memory. Restrict this key to root.
    with tempfile.TemporaryDirectory() as directory:
        path = directory + '/recipient.pem'
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
        result = subprocess.run(['openssl', 'cms', '-decrypt', '-inform', 'DER', '-inkey', path],
            input=ciphertext, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=True)
        if len(result.stdout) != 32:
            raise ValueError('Invalid data key')
        return result.stdout

def decide(source, step, book):
    # A temp file caps output size through RLIMIT_FSIZE; no unbounded PIPE buffer.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(['python', '-I', '/app/worker.py'],
            input=canonical({'source': source, 'context': {'step': step, 'book': book}}) + b'\n',
            stdout=output, stderr=subprocess.DEVNULL, timeout=5, close_fds=True)
        output.seek(0)
        target = output.read(128).decode()
    if result.returncode or not re.fullmatch(r'(?:0(?:\.[0-9]{1,8})?|1(?:\.0{1,8})?)', target):
        raise ValueError('Invalid decision')
    return target

def session(channel):
    envelope = receive(channel)
    h = header(envelope)
    recipient = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    doc = subprocess.run(['/usr/local/bin/atlas-nsm'], input=recipient.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo),
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=True).stdout
    send(channel, {'kind': 'kms', 'key_arn': h['key_arn'], 'wrapped_key': envelope['wrapped_key'],
        'context': context(envelope), 'attestation': b64(doc)})
    payload = open_payload(envelope, unwrap_cms(unb64(receive(channel)['ciphertext_for_recipient']), recipient))
    signing_key = validate_payload(payload)
    del recipient
    step = 0
    while True:
        send(channel, {'kind': 'market'})
        market = receive(channel)
        book = market['book']
        if set(book) != {'symbol', 'bidPrice', 'bidQty', 'askPrice', 'askQty'} or book['symbol'] != 'BTCUSDT':
            raise ValueError('Invalid book')
        # Quotes and clock are parent-supplied; never claimed as attested market truth.
        target = decide(payload['source'], step, book)
        config = payload['config']
        signal = {'domain': 'atlas.private-decision/v1', 'run_id': config['run_id'],
            'release_id': config['release_id'], 'content_hash': config['content_hash'],
            'nonce': uuid4().hex, 'issued_at': market['timestamp'], 'target': target}
        signal['signature'] = signing_key.sign(canonical(signal)).hex()
        send(channel, {'kind': 'signal', 'payload': signal})
        if receive(channel) != {'accepted': True}:
            return  # never retry an uncertain trade automatically
        step += 1
        time.sleep(payload['interval'])

def main():
    if not os.path.exists('/dev/nsm'):
        raise SystemExit('NSM_REQUIRED')
    server = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    server.bind((socket.VMADDR_CID_ANY, 5000))
    server.listen(1)
    # Single package per process lifetime. Restart creates a fresh recipient key.
    channel, _ = server.accept()
    channel.settimeout(60)
    try:
        session(channel)
    except Exception:
        try:
            send(channel, {'kind': 'failed'})
        except Exception:
            pass
    finally:
        channel.close()
        server.close()

if __name__ == '__main__':
    main()
