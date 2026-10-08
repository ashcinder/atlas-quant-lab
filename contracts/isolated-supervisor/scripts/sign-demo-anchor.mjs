// Sign once using the isolated funded wallet; no broadcast or private output on stdout.
import { Wallet } from 'ethers';
import { readFile, writeFile } from 'node:fs/promises';
const [root, intentPath] = process.argv.slice(2);
if (!root || !root.split('/').at(-1).startsWith('atlas-competition-')) throw new Error('Dedicated demo root required');
const settings = JSON.parse(await readFile(`${root}/demo.json`, 'utf8'));
const intent = JSON.parse(await readFile(intentPath, 'utf8')).intent;
const wallet = JSON.parse(await readFile(`${root}/secrets/wallet.json`, 'utf8'));
async function rpc(method, params = []) {
 const response = await fetch(`http://127.0.0.1:${settings.rpc_port}`, { method:'POST', headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',id:1,method,params}),signal:AbortSignal.timeout(10000) });
 const value=await response.json();if(value.error) throw new Error(`${method} failed`);return value.result;
}
const chain=BigInt(await rpc('eth_chainId'));
const genesis=await rpc('eth_getBlockByNumber',['0x0',false]);
if (chain!==1051n || genesis.hash!==settings.genesis || intent.chainId!==1051 || intent.value!=='0x0' || !intent.data.startsWith('0x41544c41535a4b32')) throw new Error('Intent/network mismatch');
const from=wallet.payer.address,to=wallet.recipient.address;
const gasPrice=BigInt(await rpc('eth_gasPrice'));
const estimate=BigInt(await rpc('eth_estimateGas',[{from,to,value:'0x0',data:intent.data}]));
const bytes=Buffer.from(intent.data.slice(2),'hex');const intrinsic=21000n+[...bytes].reduce((v,b)=>v+(b?68n:4n),0n);
const gasLimit=((estimate>intrinsic?estimate:intrinsic)*120n+99n)/100n;
const nonce=Number(BigInt(await rpc('eth_getTransactionCount',[from,'pending'])));
const raw=await new Wallet(wallet.payer.privateKey).signTransaction({type:0,chainId:1051,nonce,gasPrice,gasLimit,to,value:0n,data:intent.data});
await writeFile(`${root}/secrets/anchor.raw`,raw,{mode:0o600,flag:'wx'});
console.log('Signed isolated zero-value anchor retained privately; not broadcast yet.');
