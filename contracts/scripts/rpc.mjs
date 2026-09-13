import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {Wallet} from 'ethers';
export const rpcUrl=process.env.ATLAS_SUPERVISOR_RPC || 'http://127.0.0.1:42515';
if(!['http://127.0.0.1:42515','http://127.0.0.1:42516'].includes(rpcUrl)) throw Error('Only reviewed local Supervisor endpoints allowed');
export const wallet=new Wallet(JSON.parse(fs.readFileSync(path.join(os.homedir(),'.local/share/atlas-supervisor-deployer/wallet.json'),'utf8')).privateKey);
export async function rpc(method,params) {
  const response=await fetch(rpcUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',id:1,method,params}),signal:AbortSignal.timeout(45000)});
  const text=await response.text();
  if(!text) throw Error('Empty RPC response: '+method+' HTTP '+response.status);
  const body=JSON.parse(text);
  if(body.error) throw Error(JSON.stringify(body.error));
  return body.result;
}
export async function transact(data,to) {
  if(BigInt(await rpc('eth_chainId',[]))!==1051n) throw Error('wrong chain');
  const nonce=Number(BigInt(await rpc('eth_getTransactionCount',[wallet.address,'latest'])));
  const gasPrice=BigInt(await rpc('eth_gasPrice',[]));
  if(gasPrice>10000000000n) throw Error('unexpected gas price');
  const raw=await wallet.signTransaction({type:0,chainId:1051,nonce,gasPrice,gasLimit:6000000,value:0,data,...(to?{to}:{})});
  const hash=await rpc('eth_sendRawTransaction',[raw]);
  if(typeof hash!=='string'||!/^0x[0-9a-fA-F]{64}$/.test(hash)) throw Error('RPC did not return a transaction hash');
  const receipt=await rpc('eth_getTransactionReceipt',[hash]);
  if(!receipt || typeof receipt!=='object') throw Error('no mined receipt: '+hash);
  return {hash,receipt};
}
