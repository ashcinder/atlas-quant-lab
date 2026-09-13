import fs from 'node:fs';
import {Interface,sha256,keccak256} from 'ethers';
import {rpc,transact,rpcUrl,wallet} from './rpc.mjs';
if(!process.argv[2]) throw Error('Provide locally verified Groth16 export');
const payload=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const file=rpcUrl.endsWith(':42516')?'../docs/SUPERVISOR_ISOLATED_ZKP_DEPLOYMENT.json':'../docs/SUPERVISOR_ZKP_DEPLOYMENT.json';
const deployment=JSON.parse(fs.readFileSync(file,'utf8'));
if(deployment.rpc!==rpcUrl) throw Error('network mismatch');
const compiled=JSON.parse(fs.readFileSync('artifacts/compiled.json')).contracts;
const v=new Interface(compiled['vendor/risc0/groth16/RiscZeroGroth16Verifier.sol'].RiscZeroGroth16Verifier.abi);
const r=new Interface(compiled['src/AtlasReceiptRegistry.sol'].AtlasReceiptRegistry.abi);
const verifier=deployment.contracts.RiscZeroGroth16Verifier.address;
const registry=deployment.contracts.AtlasReceiptRegistry.address;
for(const entry of Object.values(deployment.contracts)) {
 if(keccak256(await rpc('eth_getCode',[entry.address,'latest']))!==entry.runtimeCodeHash) throw Error('runtime changed');
}
const call=async (to,data)=>rpc('eth_call',[{from:wallet.address,to,data,value:'0x0'},'latest']);
const image=r.decodeFunctionResult('imageId',await call(registry,r.encodeFunctionData('imageId')))[0];
if(image!==payload.imageId) throw Error('fixed image mismatch');
const submitted=await transact(r.encodeFunctionData('submit',[payload.seal,payload.journal]),registry);
if(submitted.receipt.status!=='0x1') throw Error('actual strategy proof rejected '+submitted.hash);
const digest=sha256(payload.journal);
const stored=r.decodeFunctionResult('verifiedJournals',await call(registry,r.encodeFunctionData('verifiedJournals',[digest])))[0];
if(!stored) throw Error('verified journal not stored');
const checks=[];
async function reject(name,data,to) {
 let tx;
 try {tx=await transact(data,to);} catch(error) {
   // Supervisor executes synchronously and reports a revert as JSON-RPC error;
   // it does not retain a failed receipt. Network/parse errors never count.
   if(error.message.includes('"code":-32000') && error.message.includes('execution reverted')) {
     checks.push({name,rpcCode:-32000,result:'execution reverted',transactionHash:null});return;
   }
   throw error;
 }
 if(tx.receipt.status!=='0x0') throw Error('invalid case did not revert '+name+' '+tx.hash);
 checks.push({name,transactionHash:tx.hash,status:tx.receipt.status});
}
const bad=Buffer.from(payload.seal.slice(2),'hex');bad[20]^=1;
await reject('corrupted_seal',v.encodeFunctionData('verify',['0x'+bad.toString('hex'),image,digest]),verifier);
await reject('wrong_journal',v.encodeFunctionData('verify',[payload.seal,image,sha256('0x00')]),verifier);
await reject('wrong_image',v.encodeFunctionData('verify',[payload.seal,'0x'+'ab'.repeat(32),digest]),verifier);
await reject('duplicate_journal',r.encodeFunctionData('submit',[payload.seal,payload.journal]),registry);
const output={network:rpcUrl.endsWith(':42516')?'isolated_supervisor':'original_supervisor',chainId:1051,rpc:rpcUrl,
 imageId:image,journalDigest:digest,verifier,registry,transactionHash:submitted.hash,
 blockNumber:submitted.receipt.blockNumber,gasUsed:submitted.receipt.gasUsed,
 cryptographicVerificationOnSupervisor:true,proofSource:'atlas_private_program_receipt',
 reportId:'qjr_a3d3bf9b1500434cb4',scope:'bounded_program_backtest',
 liveProfitProved:false,AIExecutionProved:false,checks};
fs.writeFileSync('../docs/SUPERVISOR_ZKP_ACCEPTANCE.json',JSON.stringify(output,null,2)+'\n');
deployment.strategyProofVerified=true;deployment.acceptance=output;
fs.writeFileSync(file,JSON.stringify(deployment,null,2)+'\n');
console.log(JSON.stringify(output));
