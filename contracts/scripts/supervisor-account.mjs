import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {Wallet, sha256, toUtf8Bytes, randomBytes, hexlify} from 'ethers';
const file = path.join(os.homedir(),'.local/share/atlas-supervisor-deployer/wallet.json');
fs.mkdirSync(path.dirname(file),{recursive:true,mode:0o700});
let wallet;
if(fs.existsSync(file)) wallet=new Wallet(JSON.parse(fs.readFileSync(file,'utf8')).privateKey);
else {
  wallet=Wallet.createRandom();
  fs.writeFileSync(file,JSON.stringify({privateKey:wallet.privateKey,address:wallet.address}),{mode:0o600,flag:'wx'});
}
const random = hexlify(randomBytes(32));
const signature = wallet.signingKey.sign(sha256(toUtf8Bytes(random)));
const url=process.env.ATLAS_SUPERVISOR_HTTP || 'http://127.0.0.1:56741';
if(!['http://127.0.0.1:56741','http://127.0.0.1:56742'].includes(url)) throw Error('Only reviewed local Supervisor endpoints allowed');
const response = await fetch(url+'/claim',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({PublicKey:wallet.signingKey.publicKey.slice(2),RandomStr:random,Sign1:signature.r.slice(2),Sign2:signature.s.slice(2)}),signal:AbortSignal.timeout(15000)});
console.log(JSON.stringify({address:wallet.address,claim:await response.json()}));
