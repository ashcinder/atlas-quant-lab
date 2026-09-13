// Verification only: no wallet/private key is loaded and no tx is submitted.
// Supervisor's eth_call currently has nonstandard state/height side effects.
import fs from 'node:fs';
import {Interface,sha256,keccak256} from 'ethers';
const d=JSON.parse(fs.readFileSync('../docs/SUPERVISOR_ISOLATED_ZKP_DEPLOYMENT.json','utf8'));
const p=JSON.parse(fs.readFileSync('atlas-acceptance-groth16.json','utf8'));
const r=new Interface(JSON.parse(fs.readFileSync('artifacts/compiled.json','utf8')).contracts['src/AtlasReceiptRegistry.sol'].AtlasReceiptRegistry.abi);
async function rpc(method,params) {
 const x=await (await fetch(d.rpc,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',id:1,method,params}),signal:AbortSignal.timeout(15000)})).json();
 if(x.error) throw Error(JSON.stringify(x.error));return x.result;
}
if(BigInt(await rpc('eth_chainId',[]))!==1051n) throw Error('wrong chain');
for(const c of Object.values(d.contracts)) {
 if(keccak256(await rpc('eth_getCode',[c.address,'latest']))!==c.runtimeCodeHash) throw Error('code mismatch');
}
const hash=d.acceptance.transactionHash;
const receipt=await rpc('eth_getTransactionReceipt',[hash]);
const tx=await rpc('eth_getTransactionByHash',[hash]);
if(receipt?.status!=='0x1'||tx?.input?.toLowerCase()!==r.encodeFunctionData('submit',[p.seal,p.journal]).toLowerCase()) throw Error('receipt/input mismatch');
if(tx.to?.toLowerCase()!==d.contracts.AtlasReceiptRegistry.address.toLowerCase()) throw Error('target mismatch');
const digest=sha256(p.journal);
const value=await rpc('eth_call',[{from:d.deployer,to:d.contracts.AtlasReceiptRegistry.address,data:r.encodeFunctionData('verifiedJournals',[digest]),value:'0x0'},'latest']);
if(!r.decodeFunctionResult('verifiedJournals',value)[0]) throw Error('journal not registered');
console.log(JSON.stringify({verified:true,rpc:d.rpc,transactionHash:hash,journalDigest:digest,noPrivateKeyRequired:true}));
