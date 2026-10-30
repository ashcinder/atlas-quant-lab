#!/usr/bin/env python3
"""Merge reviewed public chain addresses into an operator's private release file."""
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'release'))
from preflight import read_env

if len(sys.argv)!=4:
    raise SystemExit('usage: merge-env.py LAB_ENV CHAIN_ENV NEW_OUTPUT_ENV')
values=read_env(Path(sys.argv[1]))
values.update(read_env(Path(sys.argv[2])))
values['ATLAS_TRUSTED_PROXY_IPS']=values['ATLAS_WEB_IP']
with os.fdopen(os.open(sys.argv[3],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:
    f.write('\n'.join(k+'='+v for k,v in values.items())+'\n')
print('Created reviewed merged configuration; no shell evaluation performed')
