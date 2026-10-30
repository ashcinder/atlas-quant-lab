import { Wallet, parseEther } from 'ethers';
import { readFileSync } from 'node:fs';

const [expectedGenesis, recipient, amount] = process.argv.slice(2);
if (!/^0x[0-9a-f]{64}$/i.test(expectedGenesis) || !/^0x[0-9a-f]{40}$/i.test(recipient) || BigInt(recipient)===0n) throw Error('Invalid public chain identity or recipient');
const value=parseEther(amount);
if(value<=0n) throw Error('Test amount must be positive');
const config=JSON.parse(readFileSync('/run/test-wallet.json'));
if(config.chainId!==1051 || config.testOnly!==true) throw Error('Not an isolated test wallet');
const wallet=new Wallet(config.payer.privateKey);
async function rpc(method,params=[]) {
  await new Promise(resolve=>setTimeout(resolve,150));
  const response=await fetch('http://supervisor:42515',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',id:1,method,params}),signal:AbortSignal.timeout(20000)});
  const body=await response.json();
  if(!response.ok || body.error) throw Error('Isolated chain RPC failed');
  return body.result;
}
if(BigInt(await rpc('eth_chainId'))!==1051n) throw Error('Wrong chain ID');
const genesis=await rpc('eth_getBlockByNumber',['0x0',false]);
if(genesis?.hash?.toLowerCase()!==expectedGenesis.toLowerCase()) throw Error('Wrong genesis; refusing to sign');
const tx={type:0,chainId:1051,nonce:Number(BigInt(await rpc('eth_getTransactionCount',[wallet.address,'pending']))),gasPrice:BigInt(await rpc('eth_gasPrice')),gasLimit:21000n,to:recipient,value,data:'0x'};
const raw=await wallet.signTransaction(tx);
const hash=await rpc('eth_sendRawTransaction',[raw]);
const receipt=await rpc('eth_getTransactionReceipt',[hash]);
if(receipt?.status!=='0x1') {
  console.log(JSON.stringify({testOnly:true,transactionHash:hash,status:'unconfirmed'}));
  throw Error('Funding outcome unconfirmed; retain the original transaction identity and check before retrying');
}
console.log(JSON.stringify({testOnly:true,chainId:1051,genesis:genesis.hash,recipient,amountBkc:amount,transactionHash:hash,blockNumber:receipt.blockNumber}));
