from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = spec_from_file_location('release_preflight', ROOT / 'deploy/release/preflight.py')
preflight = module_from_spec(spec)
spec.loader.exec_module(preflight)


def config(tmp_path):
    values = preflight.read_env(ROOT / '.env.lab.example')
    cert = tmp_path / 'certificate.pem'
    cert.write_text('test path only; no TLS parsing in unit validation')
    values.update(ATLAS_DOMAIN='lab.test', ATLAS_ALLOWED_ORIGINS='https://lab.test:9443',
                  ATLAS_HTTPS_PORT='9443', ATLAS_TLS_CERT_FILE=str(cert), ATLAS_TLS_KEY_FILE=str(cert))
    return values


def test_https_port_and_reviewed_config_validate(tmp_path):
    preflight.validate_config(config(tmp_path))


@pytest.mark.parametrize('key,value', [
    ('ATLAS_ALLOWED_ORIGINS', 'https://lab.test'), ('ATLAS_ALLOW_REGISTRATION', 'true'),
    ('ATLAS_COOKIE_SECURE', 'false'), ('VITE_TRINE_DEMO_MODE', 'true'),
    ('VITE_TRINE_TEST_PRIVATE_KEY', 'not-a-real-key'), ('ATLAS_TRUSTED_PROXY_IPS', '*'),
    ('ATLAS_API_IP', '172.30.120.0'), ('TRINE_PROOF_PRICE_BKC', '1'),
    ('ATLAS_DOMAIN', 'lab.test;bad'),
])
def test_unsafe_release_config_is_rejected(tmp_path, key, value):
    values = config(tmp_path)
    values[key] = value
    with pytest.raises(ValueError):
        preflight.validate_config(values)


def test_duplicate_env_keys_fail_instead_of_silent_override(tmp_path):
    p = tmp_path / 'test.env'
    p.write_text('ATLAS_ALLOWED_ORIGINS=https://lab.test\nATLAS_ALLOWED_ORIGINS=http://localhost\n')
    with pytest.raises(ValueError, match='duplicate'):
        preflight.read_env(p)


def chain_config(tmp_path):
    values = config(tmp_path)
    directory = tmp_path/'secrets'
    directory.mkdir(mode=0o700)
    for name in ('mysql-password', 'mysql-root-password'):
        path = directory/name
        path.write_text('test-placeholder-'*4)
        path.chmod(0o600)
    values.update(ATLAS_CHAIN_MODE='isolated_lab', ATLAS_CHAIN_SECRETS_DIR=str(directory),
                  ATLAS_SUPERVISOR_IP='172.30.120.5', QUANTJUDGE_SUPERVISOR_RPC_URL='http://supervisor:42515',
                  ATLAS_SUPERVISOR_PAYER_ADDRESS='0x'+'1'*40,
                  ATLAS_SUPERVISOR_RECIPIENT_ADDRESS='0x'+'2'*40,
                  ATLAS_SUPERVISOR_FEE_ADDRESS='0x'+'3'*40,
                  TRINE_PROOF_RECIPIENT='0x'+'2'*40, TRINE_PROOF_PRICE_BKC='1')
    import json
    wallet=directory/'wallet.json'
    wallet.write_text(json.dumps({'chainId':1051,'testOnly':True,'payer':{'address':'0x'+'1'*40,'privateKey':'0x'+'1'*64},'recipient':{'address':'0x'+'2'*40},'feeSink':{'address':'0x'+'3'*40}}));wallet.chmod(0o600)
    return values


def test_explicit_isolated_chain_profile_and_compose_overlay(tmp_path):
    values = chain_config(tmp_path)
    preflight.validate_config(values)
    assert preflight.compose_files(values)[-1].endswith('compose.chain.yaml')
    assert len(preflight.compose_files(config(tmp_path))) == 2


@pytest.mark.parametrize('key,value', [
    ('ATLAS_CHAIN_MODE','production'), ('QUANTJUDGE_SUPERVISOR_RPC_URL','http://127.0.0.1:42515'),
    ('ATLAS_SUPERVISOR_IP','172.30.120.3'), ('TRINE_PROOF_PRICE_BKC','0'),
    ('TRINE_PROOF_RECIPIENT','0x'+'0'*40),
    ('TRINE_PROOF_RECIPIENT','0x'+'4'*40), ('ATLAS_SUPERVISOR_FEE_ADDRESS','0x'+'1'*40),
])
def test_chain_profile_refuses_ambiguous_network_and_contract(tmp_path,key,value):
    values = chain_config(tmp_path)
    values[key] = value
    with pytest.raises(ValueError):
        preflight.validate_config(values)


def test_chain_database_secret_permissions_are_required(tmp_path):
    values = chain_config(tmp_path)
    (Path(values['ATLAS_CHAIN_SECRETS_DIR'])/'mysql-password').chmod(0o644)
    with pytest.raises(ValueError,match='private'):
        preflight.validate_config(values)


def test_missing_payer_wallet_refuses_deployment(tmp_path):
    values=chain_config(tmp_path)
    (Path(values['ATLAS_CHAIN_SECRETS_DIR'])/'wallet.json').unlink()
    with pytest.raises(ValueError,match='wallet'):
        preflight.validate_config(values)
