"""Untrusted parent relay: only ciphertext and intentionally public signals."""
import argparse
import json
import socket
import time
from pathlib import Path
from urllib.parse import urlparse
import boto3
import httpx
from protocol import b64, unb64, context, header, receive, send

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cid', type=int, required=True)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--platform', required=True)
    args = parser.parse_args()
    if urlparse(args.platform).scheme != 'https' or urlparse(args.platform).username:
        raise ValueError('Platform HTTPS required')
    envelope = json.loads(args.package.read_text())
    h = header(envelope)
    kms = boto3.client('kms', region_name=h['key_arn'].split(':')[3])
    channel = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    channel.settimeout(3700)
    # Enclave boot is asynchronous. Only retry connection, never a submitted signal.
    for attempt in range(30):
        try:
            channel.connect((args.cid, 5000))
            break
        except OSError:
            if attempt == 29:
                raise
            time.sleep(1)
    send(channel, envelope)
    with channel, httpx.Client(timeout=20, trust_env=False) as client:
        while True:
            message = receive(channel)
            kind = message.get('kind')
            if kind == 'kms':
                if message['key_arn'] != h['key_arn'] or message['context'] != context(envelope) or message['wrapped_key'] != envelope['wrapped_key']:
                    raise ValueError('Unexpected key request')
                result = kms.decrypt(KeyId=h['key_arn'], CiphertextBlob=unb64(envelope['wrapped_key']),
                    EncryptionContext=context(envelope), Recipient={'KeyEncryptionAlgorithm': 'RSAES_OAEP_SHA_256',
                    'AttestationDocument': unb64(message['attestation'])})
                if result.get('Plaintext') or not result.get('CiphertextForRecipient'):
                    raise ValueError('Confidential response required')
                send(channel, {'ciphertext_for_recipient': b64(result['CiphertextForRecipient'])})
            elif kind == 'market':
                response = client.get('https://api.binance.com/api/v3/ticker/bookTicker', params={'symbol': 'BTCUSDT'})
                response.raise_for_status()
                send(channel, {'book': response.json(), 'timestamp': time.time()})
            elif kind == 'signal':
                response = client.post(args.platform.rstrip('/') + '/api/v1/private-runner/signals', json=message['payload'])
                accepted = response.is_success and response.json().get('accepted') is True
                send(channel, {'accepted': accepted})
                if not accepted:
                    raise ValueError('Signal refused; operator review required')
            else:
                raise ValueError('Enclave stopped')

if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('RELAY_STOPPED: inspect service state; no order was automatically retried.') from None
