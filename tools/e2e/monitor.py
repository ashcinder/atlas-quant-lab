"""Read-only monitor for an isolated performance run and protected services."""
import argparse,json,shlex,subprocess,time
from pathlib import Path
from datetime import datetime,timezone
from control import inventory
p=argparse.ArgumentParser();p.add_argument('run_directory',type=Path);p.add_argument('--seconds',type=int,default=4500);p.add_argument('--output',type=Path);a=p.parse_args();m=json.loads((a.run_directory/'run.json').read_text());assert m['synthetic_only'] and m['project'].startswith('atlas-e2e-')
before=inventory()
out=a.output or a.run_directory/('resources-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.jsonl');until=time.monotonic()+a.seconds

def load_browser_processes(raw):
 rows = [line.split(None, 4) for line in raw.splitlines() if len(line.split(None, 4)) == 5]
 roots = set()
 for pid, _, _, _, command in rows:
  try: argv = shlex.split(command)
  except ValueError: continue
  if (len(argv) >= 3 and Path(argv[0]).name == 'node'
      and argv[1] == 'tools/e2e/load.mjs' and Path(argv[2]).resolve() == a.run_directory.resolve()):
   roots.add(pid)
 descendants = roots.copy()
 while True:
  expanded = descendants | {pid for pid, parent, *_ in rows if parent in descendants}
  if expanded == descendants: break
  descendants = expanded
 return [' '.join(row[:4]) for row in rows if row[0] in descendants and 'ms-playwright/' in row[4]]

with out.open('x') as f:
 while time.monotonic()<until:
  raw=subprocess.run(['docker','stats','--no-stream','--format','{{json .}}',m['project']+'-api-1',m['project']+'-web-1'],capture_output=True,text=True)
  clients=subprocess.run(['ps','-axo','pid,ppid,rss,%cpu,command'],capture_output=True,text=True).stdout
  client_rows=load_browser_processes(clients)
  memory=subprocess.run(['vm_stat'],capture_output=True,text=True).stdout
  states=subprocess.run(['docker','inspect',m['project']+'-api-1',m['project']+'-web-1'],capture_output=True,text=True)
  rows=json.loads(states.stdout) if states.returncode==0 else []
  f.write(json.dumps({'at':time.time(),'docker':[json.loads(x) for x in raw.stdout.splitlines() if x.startswith('{')],'vm_stat':memory,'browser_processes':client_rows,'protected_unchanged':inventory()==before,'state':[{'name':x['Name'],'oom':x['State']['OOMKilled'],'restarts':x['RestartCount'],'health':x['State'].get('Health',{}).get('Status')} for x in rows]})+'\n');f.flush();time.sleep(10)
print(out)
