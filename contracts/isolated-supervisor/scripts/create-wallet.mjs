import { Wallet } from 'ethers';
import { mkdir, writeFile, chmod } from 'node:fs/promises';
import { dirname } from 'node:path';

const output = process.argv[2];
if (!output) throw new Error('wallet output path is required');
await mkdir(dirname(output), { recursive: true, mode: 0o700 });
const payer = Wallet.createRandom();
const recipient = Wallet.createRandom();
const feeSink = Wallet.createRandom();
await writeFile(output, JSON.stringify({
  chainId: 1051,
  testOnly: true,
  payer: { address: payer.address, privateKey: payer.privateKey },
  recipient: { address: recipient.address },
  feeSink: { address: feeSink.address },
}, null, 2), { mode: 0o600, flag: 'wx' });
await chmod(output, 0o600);
