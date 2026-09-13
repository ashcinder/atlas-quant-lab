import fs from 'node:fs';
import path from 'node:path';
import solc from 'solc';
const sources = {};
for (const root of ['src', 'vendor']) {
  for (const name of fs.readdirSync(root, {recursive:true})) {
    const file = path.join(root, name);
    if (file.endsWith('.sol')) sources[file] = {content:fs.readFileSync(file,'utf8')};
  }
}
const result = JSON.parse(solc.compile(JSON.stringify({language:'Solidity',sources,settings:{
  optimizer:{enabled:true,runs:200}, evmVersion:'paris',
  outputSelection:{'*':{'*':['abi','evm.bytecode.object','evm.deployedBytecode.object']}}
}}), {import:p => {
  if (p.startsWith('openzeppelin/contracts/')) {
    return {contents:fs.readFileSync(p.replace('openzeppelin/contracts/','node_modules/@openzeppelin/contracts/'),'utf8')};
  }
  return {error:'Unknown import: '+p};
}}));
for (const e of result.errors ?? []) if(e.severity==='error') throw Error(e.formattedMessage);
fs.mkdirSync('artifacts',{recursive:true});
fs.writeFileSync('artifacts/compiled.json',JSON.stringify({compiler:solc.version(),contracts:result.contracts},null,2));
console.log('Compiled official verifier and Atlas registry for Paris EVM');
