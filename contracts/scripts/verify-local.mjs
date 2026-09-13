import fs from 'node:fs';
import {JsonRpcProvider,ContractFactory,sha256,keccak256} from 'ethers';
const provider=new JsonRpcProvider('http://127.0.0.1:8547',31337);
const signer=await provider.getSigner();
const compiled=JSON.parse(fs.readFileSync('artifacts/compiled.json')).contracts;
const fixture=fs.readFileSync('vendor/risc0/TestReceiptV3_0.sol','utf8');
const value=name=>'0x'+fixture.match(new RegExp(name+'\\s*=\\s*hex"([a-f0-9]+)"'))[1];
const payload=process.argv[2]?JSON.parse(fs.readFileSync(process.argv[2],'utf8')):
  {imageId:value('IMAGE_ID'),journal:value('JOURNAL'),seal:value('SEAL')};
async function deploy(file,name,args) {
 const a=compiled[file][name];
 const c=await new ContractFactory(a.abi,'0x'+a.evm.bytecode.object,signer).deploy(...args);
 await c.waitForDeployment();
 return c;
}
const verifier=await deploy('vendor/risc0/groth16/RiscZeroGroth16Verifier.sol','RiscZeroGroth16Verifier',[
 '0xa54dc85ac99f851c92d7c96d7318af41dbe7c0194edfcc37eb4d422a998c1f56',
 '0x04446e66d300eb7fb45c9726bb53c793dda407a62e9601618bb43c5c14657ac0']);
const registry=await deploy('src/AtlasReceiptRegistry.sol','AtlasReceiptRegistry',[await verifier.getAddress(),payload.imageId]);
await verifier.verify(payload.seal,payload.imageId,sha256(payload.journal));
const receipt=await (await registry.submit(payload.seal,payload.journal)).wait();
if(receipt.status!==1 || !await registry.verifiedJournals(sha256(payload.journal))) throw Error('not verified');
const rejected=[];
async function reject(name,fn) {
 try {await fn();} catch(e) {
   if(e.code!=='CALL_EXCEPTION') throw e;
   rejected.push(name);return;
 }
 throw Error('invalid proof accepted: '+name);
}
const seal=Buffer.from(payload.seal.slice(2),'hex');seal[20]^=1;
await reject('corrupted_seal',()=>verifier.verify('0x'+seal.toString('hex'),payload.imageId,sha256(payload.journal)));
await reject('wrong_journal',()=>verifier.verify(payload.seal,payload.imageId,sha256('0x00')));
await reject('wrong_image',()=>verifier.verify(payload.seal,'0x'+'ab'.repeat(32),sha256(payload.journal)));
await reject('duplicate_journal',()=>registry.submit.staticCall(payload.seal,payload.journal));
const output={network:'isolated_local_evm',chainId:31337,supervisor:false,
 proofSource:process.argv[2]?'atlas_private_program_receipt':'upstream_official_test_vector',
 imageId:payload.imageId,journalDigest:sha256(payload.journal),
 verifier:await verifier.getAddress(),registry:await registry.getAddress(),
 transactionHash:receipt.hash,blockNumber:receipt.blockNumber,gasUsed:receipt.gasUsed.toString(),
 registryRuntimeCodeHash:keccak256(await provider.getCode(await registry.getAddress())),
 cryptographicVerificationOnEVM:true,rejected};
fs.writeFileSync(process.argv[2]?'../docs/ATLAS_EVM_ZKP_ACCEPTANCE.json':'../docs/VERIFIER_EVM_COMPATIBILITY.json',JSON.stringify(output,null,2)+'\n');
console.log(JSON.stringify(output));
