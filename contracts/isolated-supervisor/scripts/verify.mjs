import { Wallet, keccak256 } from 'ethers';
import { readFile, writeFile } from 'node:fs/promises';

const [phase, walletFile, phaseOneFile, resultFile] = process.argv.slice(2);
const rpcUrl = process.env.ATLAS_SUPERVISOR_RPC_URL;
if (!['phase1', 'phase2'].includes(phase)) throw new Error('phase must be phase1 or phase2');
if (!rpcUrl || new URL(rpcUrl).hostname !== '127.0.0.1') throw new Error('RPC must use 127.0.0.1');
const walletData = JSON.parse(await readFile(walletFile, 'utf8'));
const payer = new Wallet(walletData.payer.privateKey);
const recipient = walletData.recipient.address;

async function rpc(method, params = []) {
  await new Promise(resolve => setTimeout(resolve, 60));
  const response = await fetch(rpcUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
    signal: AbortSignal.timeout(15000),
  });
  const payload = await response.json();
  if (payload.error) throw new Error(`${method}: ${JSON.stringify(payload.error)}`);
  return payload.result;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function hex(value) {
  return BigInt(value);
}

const chainId = hex(await rpc('eth_chainId'));
assert(chainId === 1051n, `unexpected chain id ${chainId}`);
const genesis = await rpc('eth_getBlockByNumber', ['0x0', false]);
assert(genesis && /^0x[0-9a-f]{64}$/i.test(genesis.hash), 'missing genesis hash');
assert(hex(genesis.timestamp) > 0n, `invalid genesis timestamp ${genesis.timestamp}`);

if (phase === 'phase1') {
  const initialPayer = hex(await rpc('eth_getBalance', [payer.address, 'latest']));
  const initialRecipient = hex(await rpc('eth_getBalance', [recipient, 'latest']));
  const nonce = Number(hex(await rpc('eth_getTransactionCount', [payer.address, 'latest'])));
  const value = 1_000_000_000_000_000n;
  const raw = await payer.signTransaction({
    type: 0,
    chainId: 1051,
    nonce,
    gasPrice: 1_000_000_000n,
    gasLimit: 100_000n,
    to: recipient,
    value,
    data: '0x'+'61'.repeat(1024),
  });
  const rejected = async (overrides) => {
    const invalid = await payer.signTransaction({type:0,chainId:1051,nonce,gasPrice:1_000_000_000n,gasLimit:21_000n,to:recipient,value,data:'0x',...overrides});
    let failed = false;
    try { await rpc('eth_sendRawTransaction',[invalid]); } catch { failed = true; }
    assert(failed,'invalid signed transaction was accepted');
  };
  await rejected({nonce:nonce+3});
  await rejected({chainId:1052});
  await rejected({gasPrice:2_000_000_000n});
  await rejected({value:initialPayer*2n});
  assert(hex(await rpc('eth_getBalance',[recipient,'latest']))===initialRecipient,'rejected transfer changed balance');
  const heightBeforeCall=await rpc('eth_blockNumber');
  const callResult=await rpc('eth_call',[{from:payer.address,to:recipient,value:'0x1',data:'0x'},'latest']);
  assert(callResult==='0x','read-only call did not execute');
  assert(await rpc('eth_blockNumber')===heightBeforeCall,'eth_call added a block');
  assert(hex(await rpc('eth_getBalance',[recipient,'latest']))===initialRecipient,'eth_call changed recipient');
  assert(hex(await rpc('eth_getBalance',[payer.address,'latest']))===initialPayer,'eth_call changed payer');
  const originResponse=await fetch(rpcUrl,{method:'POST',headers:{'Content-Type':'application/json',Origin:'https://untrusted.example'},body:JSON.stringify({jsonrpc:'2.0',id:1,method:'eth_chainId',params:[]})});
  assert(originResponse.status===403,'browser Origin was not rejected');
  const expectedHash = keccak256(raw);
  const transactionHash = await rpc('eth_sendRawTransaction', [raw]);
  assert(transactionHash.toLowerCase() === expectedHash.toLowerCase(), 'RPC returned a non-canonical transaction hash');
  const receipt = await rpc('eth_getTransactionReceipt', [transactionHash]);
  assert(receipt?.status === '0x1', `transaction failed: ${JSON.stringify(receipt)}`);
  const transaction = await rpc('eth_getTransactionByHash', [transactionHash]);
  assert(transaction?.hash?.toLowerCase() === transactionHash.toLowerCase(), 'transaction lookup hash mismatch');
  assert(transaction?.from?.toLowerCase() === payer.address.toLowerCase(), 'transaction sender mismatch');
  assert(transaction?.to?.toLowerCase() === recipient.toLowerCase(), 'transaction recipient mismatch');
  assert(hex(transaction.value) === value, 'transaction value mismatch');
  const latest = await rpc('eth_getBlockByNumber', ['latest', false]);
  assert(hex(latest.number) === 1n, `expected block 1, got ${latest.number}`);
  const finalRecipient = hex(await rpc('eth_getBalance', [recipient, 'latest']));
  const finalPayer = hex(await rpc('eth_getBalance', [payer.address, 'latest']));
  assert(finalRecipient === initialRecipient + value, 'recipient balance did not increase by the transfer value');
  assert(finalPayer < initialPayer - value, 'payer balance did not include transfer and gas costs');
  assert(hex(await rpc('eth_getTransactionCount',[payer.address,'pending']))===BigInt(nonce+1),'nonce did not advance once');
  await rejected({nonce,value:value+1n});
  const duplicateHash = await rpc('eth_sendRawTransaction', [raw]);
  assert(duplicateHash.toLowerCase() === transactionHash.toLowerCase(), 'duplicate submission hash changed');
  const afterDuplicate = await rpc('eth_blockNumber');
  assert(hex(afterDuplicate) === 1n, 'duplicate submission produced another block');
  const report = {
    phase: 'before_restart',
    checkedSecurity: {wrongNonceRejected:true,wrongChainRejected:true,wrongGasRejected:true,insufficientBalanceRejected:true,ethCallReadOnly:true,browserOriginRejected:true,staleNonceRejected:true},
    chainId: Number(chainId),
    genesis: { hash: genesis.hash, timestamp: genesis.timestamp },
    transactionHash,
    receipt: { status: receipt.status, blockHash: receipt.blockHash, blockNumber: receipt.blockNumber },
    latest: { hash: latest.hash, number: latest.number, timestamp: latest.timestamp },
    addresses: { payer: payer.address, recipient, feeSink: walletData.feeSink.address },
    balances: { payer: finalPayer.toString(), recipient: finalRecipient.toString() },
    duplicateSubmission: { hash: duplicateHash, blockNumber: afterDuplicate },
  };
  await writeFile(phaseOneFile, JSON.stringify(report, null, 2) + '\n');
} else {
  const before = JSON.parse(await readFile(phaseOneFile, 'utf8'));
  assert(hex(await rpc('eth_getTransactionCount',[payer.address,'pending']))===1n,'nonce not persisted');
  const latest = await rpc('eth_getBlockByNumber', ['latest', false]);
  const receipt = await rpc('eth_getTransactionReceipt', [before.transactionHash]);
  const transaction = await rpc('eth_getTransactionByHash', [before.transactionHash]);
  const payerBalance = hex(await rpc('eth_getBalance', [payer.address, 'latest']));
  const recipientBalance = hex(await rpc('eth_getBalance', [recipient, 'latest']));
  assert(genesis.hash === before.genesis.hash, 'genesis hash changed after restart');
  assert(genesis.timestamp === before.genesis.timestamp, 'genesis timestamp changed after restart');
  assert(latest.hash === before.latest.hash, 'latest block hash changed after restart');
  assert(latest.number === before.latest.number, 'latest block height changed after restart');
  assert(receipt?.status === '0x1', 'receipt missing after restart');
  assert(receipt.blockHash === before.receipt.blockHash, 'receipt block hash changed after restart');
  assert(transaction?.hash?.toLowerCase() === before.transactionHash.toLowerCase(), 'transaction missing after restart');
  assert(payerBalance.toString() === before.balances.payer, 'payer balance changed after restart');
  assert(recipientBalance.toString() === before.balances.recipient, 'recipient balance changed after restart');
  const report = {
    schemaVersion: 1,
    generatedAt: new Date().toISOString(),
    network: { isolated: true, loopbackOnly: true, chainId: Number(chainId) },
    beforeRestart: before,
    afterRestart: {
      genesis: { hash: genesis.hash, timestamp: genesis.timestamp },
      latest: { hash: latest.hash, number: latest.number, timestamp: latest.timestamp },
      transactionHash: before.transactionHash,
      receipt: { status: receipt.status, blockHash: receipt.blockHash, blockNumber: receipt.blockNumber },
      balances: { payer: payerBalance.toString(), recipient: recipientBalance.toString() },
    },
    assertions: {
      ...before.checkedSecurity,
      noncePersistedAcrossRestart: true,
      cleanDatabaseBootstrapped: true,
      genesisTimestampPositive: true,
      canonicalSignedTransactionHash: true,
      duplicateSubmissionIdempotent: true,
      recipientBalanceUpdated: true,
      longOrderPayloadAccepted: true,
      statePersistedAcrossRestart: true,
    },
  };
  await writeFile(resultFile, JSON.stringify(report, null, 2) + '\n');
}
