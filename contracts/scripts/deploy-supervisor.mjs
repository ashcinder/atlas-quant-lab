import fs from 'node:fs';
import {ContractFactory,keccak256} from 'ethers';
import {rpc,transact,rpcUrl,wallet} from './rpc.mjs';
const output=rpcUrl.endsWith(':42516')?'../docs/SUPERVISOR_ISOLATED_ZKP_DEPLOYMENT.json':'../docs/SUPERVISOR_ZKP_DEPLOYMENT.json';
const compiled=JSON.parse(fs.readFileSync('artifacts/compiled.json')).contracts;
const deployment=fs.existsSync(output)?JSON.parse(fs.readFileSync(output)):{chainId:1051,rpc:rpcUrl,deployer:wallet.address,contracts:{},strategyProofVerified:false};
if(deployment.rpc!==rpcUrl) throw Error('deployment network mismatch');
async function deploy(name,file,args) {
  if(deployment.contracts[name]) return deployment.contracts[name].address;
  const artifact=compiled[file][name];
  const tx=await new ContractFactory(artifact.abi,'0x'+artifact.evm.bytecode.object).getDeployTransaction(...args);
  const {hash,receipt}=await transact(tx.data);
  if(receipt.status!=='0x1'||!receipt.contractAddress) throw Error('deployment failed '+JSON.stringify(receipt));
  const address=receipt.contractAddress;
  const code=await rpc('eth_getCode',[address,'latest']);
  if(!code || code==='0x') throw Error('deployed code missing');
  deployment.contracts[name]={address,transactionHash:hash,blockNumber:receipt.blockNumber,runtimeCodeHash:keccak256(code)};
  fs.writeFileSync(output,JSON.stringify(deployment,null,2)+'\n');
  console.log(name,address,hash);
  return address;
}
const verifier=await deploy('RiscZeroGroth16Verifier','vendor/risc0/groth16/RiscZeroGroth16Verifier.sol',[
  '0xa54dc85ac99f851c92d7c96d7318af41dbe7c0194edfcc37eb4d422a998c1f56',
  '0x04446e66d300eb7fb45c9726bb53c793dda407a62e9601618bb43c5c14657ac0']);
await deploy('AtlasReceiptRegistry','src/AtlasReceiptRegistry.sol',[verifier,'0x02b08452a95d405b82b52dd475fc448639da4465123324711b369d7e18c27cd4']);
