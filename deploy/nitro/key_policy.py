"""AUTHOR runs this in an independent AWS account. Platform never receives admin."""
import argparse
import json
import re
from pathlib import Path

def policy(author, runner, measurements):
    if not re.fullmatch(r'arn:aws:iam::\d{12}:role/[\w+=,.@/-]+', author) or not re.fullmatch(r'arn:aws:iam::\d{12}:role/[\w+=,.@/-]+', runner):
        raise ValueError('Use IAM role ARNs')
    if author.split(':')[4] == runner.split(':')[4]:
        raise ValueError('Author key owner and platform must be separate AWS accounts')
    pins = {}
    for index in (0, 1, 2):
        value = measurements[f'PCR{index}'].lower()
        if not re.fullmatch('[0-9a-f]{96}', value) or value == '0' * 96:
            raise ValueError('Real, non-debug PCR0/1/2 required')
        pins[f'kms:RecipientAttestation:PCR{index}'] = value
    return {'Version': '2012-10-17', 'Statement': [
        {'Sid': 'IndependentAuthorAdministration', 'Effect': 'Allow', 'Principal': {'AWS': author},
         'Action': 'kms:*', 'Resource': '*'},
        {'Sid': 'OnlyApprovedEnclaveCanDecrypt', 'Effect': 'Allow', 'Principal': {'AWS': runner},
         'Action': 'kms:Decrypt', 'Resource': '*', 'Condition': {'StringEqualsIgnoreCase': pins,
         'StringEquals': {'kms:EncryptionContext:atlas:purpose': 'confidential-strategy-v1'}}},
        # Explicitly deny this platform principal outside the attested path, even if grants change.
        {'Sid': 'DenyUnattestedPlatformDecrypt', 'Effect': 'Deny', 'Principal': {'AWS': runner},
         'Action': ['kms:Decrypt', 'kms:ReEncryptFrom'], 'Resource': '*',
         'Condition': {'Null': {'kms:RecipientAttestation:PCR0': 'true'}}},
    ] + [
        {'Sid': f'DenyUnapprovedPCR{index}', 'Effect': 'Deny', 'Principal': {'AWS': runner},
         'Action': ['kms:Decrypt', 'kms:ReEncryptFrom'], 'Resource': '*',
         'Condition': {'StringNotEqualsIgnoreCase': {f'kms:RecipientAttestation:PCR{index}': pins[f'kms:RecipientAttestation:PCR{index}']}}}
        for index in (0, 1, 2)
    ]}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--author-role', required=True)
    parser.add_argument('--platform-role', required=True)
    parser.add_argument('--measurements', type=Path, required=True)
    args = parser.parse_args()
    measured = json.loads(args.measurements.read_text())
    print(json.dumps(policy(args.author_role, args.platform_role, measured.get('Measurements', measured)), indent=2))
