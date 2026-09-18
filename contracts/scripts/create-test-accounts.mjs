// Local-only test secrets. Never import these accounts on a production network.
import { Wallet } from 'ethers';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { homedir } from 'node:os';
const directory = join(homedir(), '.local/share/trine-test-accounts');
await mkdir(directory, { recursive: true, mode: 0o700 });
const run = new Date().toISOString().replace(/[:.]/g, '-');
const accounts = ['developer', 'proof-service'].map(role => {
  const wallet = Wallet.createRandom();
  return { role, address: wallet.address, privateKey: wallet.privateKey };
});
const file = join(directory, `${run}.json`);
await writeFile(file, JSON.stringify({ chainId: 1051, testOnly: true, accounts }, null, 2), { mode: 0o600, flag: 'wx' });
console.log(JSON.stringify({ file, accounts: accounts.map(({role,address}) => ({role,address})) }));
