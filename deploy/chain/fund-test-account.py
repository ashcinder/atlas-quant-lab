#!/usr/bin/env python3
"""Operator-signed test BKC distribution; wallet never enters the API container."""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'deploy/release'))
from preflight import read_env

if len(sys.argv)!=5:raise SystemExit('usage: fund-test-account.py FULL_ENV EXPECTED_GENESIS RECIPIENT AMOUNT_BKC')
env_file=Path(sys.argv[1]).resolve();values=read_env(env_file)
if values.get('ATLAS_CHAIN_MODE')!='isolated_lab':raise SystemExit('Only the isolated laboratory chain is supported')
container=subprocess.check_output([sys.executable,str(ROOT/'deploy/release/compose.py'),str(env_file),'ps','--quiet','api'],text=True).strip()
if not container:raise SystemExit('API network is unavailable')
wallet=Path(values['ATLAS_CHAIN_SECRETS_DIR'])/'wallet.json'
script=ROOT/'deploy/chain/fund-test-account.mjs'
raise SystemExit(subprocess.call(['docker','run','--rm','--pull','never','--platform','linux/amd64','--network','container:'+container,'--read-only','--user','0:0','--cap-drop','ALL','--cap-add','DAC_OVERRIDE','--security-opt','no-new-privileges:true','--entrypoint','node','-v',str(wallet)+':/run/test-wallet.json:ro','-v',str(script)+':/app/contracts/fund-test-account.mjs:ro',values['ATLAS_API_IMAGE'],'/app/contracts/fund-test-account.mjs',*sys.argv[2:]]))
