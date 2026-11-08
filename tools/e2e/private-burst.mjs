/** Real private queue in a synthetic project. Results never enter normal SLOs. */
import { readFile, writeFile } from 'node:fs/promises'
import { request } from '../../frontend/node_modules/playwright/index.mjs'
import { Wallet } from '../../frontend/node_modules/ethers/lib.esm/index.js'

const path = process.argv[2]
const run = JSON.parse(await readFile(path + '/run.json'))
const fixture = JSON.parse(await readFile(path + '/fixture.json'))
if (!run.synthetic_only || !fixture.synthetic_only || !/^http:\/\/127\.0\.0\.1:\d+$/.test(run.origin)
    || run.port === 18095 || run.project.includes('hour')) throw Error('Dedicated synthetic functional project required')
const clients = []
const records = []
const release = fixture.releases.private
const payload = { release_id: release, dataset_id: fixture.datasets['BTC-USD:1d'].dataset_id,
  settings: { initial_capital: 10000 } }

async function account(name) {
  const client = await request.newContext({ baseURL: run.origin, extraHTTPHeaders: { Origin: run.origin } })
  clients.push(client)
  const auth = await client.post('/api/login', { data: {
    email: name + '@e2e.example.test', password: process.env.ATLAS_E2E_PASSWORD ?? 'Only-E2E-Fixture-2026!',
  } })
  if (!auth.ok()) throw Error('Synthetic login failed ' + auth.status())
  return client
}

async function checked(reply) {
  if (!reply.ok()) throw Error('Unexpected synthetic request status ' + reply.status())
  return reply.json()
}

async function trial(owner, client, phase) {
  const started = performance.now()
  const response = await client.post('/api/v1/compute/private-backtests', { data: payload, timeout: 75_000 })
  const result = await response.json()
  const row = { owner, phase, status: response.status(), ms: Math.round(performance.now() - started) }
  if (response.status() === 200) {
    if (!result.run_id || result.compute?.execution_location !== 'server_private') throw Error('Invalid private result')
    row.run_id = result.run_id
  } else if (response.status() === 429) {
    row.retry_after = response.headers()['retry-after']
    if (row.retry_after !== '3' || !result.detail?.includes('每账号限一项')) throw Error('Unexpected 429 reason')
  } else {
    throw Error('Unexpected burst HTTP status ' + response.status())
  }
  records.push(row)
  return row
}

try {
  const author = await account('author')
  const peers = await Promise.all(['subscriber', 'user44', 'user45', 'user46', 'user47', 'user49'].map(account))
  // Give the sixth peer a real application entitlement through the simulated RPC.
  await checked(await author.post('/api/v1/strategy-releases/' + release + '/publish'))
  let offer = await checked(await author.get('/api/v1/strategy-releases/' + release + '/bkc-offer'))
  if (!offer) {
    offer = await checked(await author.put('/api/v1/strategy-releases/' + release + '/bkc-offer', {
      data: { recipient: '0x' + '37'.repeat(20), amount_bkc: '0.01' },
    }))
  }
  const last = peers[5]
  const current = await checked(await last.get('/api/v1/strategy-subscriptions'))
  if (!current.some(item => item.release_id === release && item.status === 'active')) {
    const wallet = new Wallet('0x' + '19'.repeat(32))
    const order = await checked(await last.post('/api/v1/strategy-releases/' + release + '/bkc-order', {
      data: { address: wallet.address },
    }))
    const orderPath = '/api/v1/bkc-orders/' + order.id
    const { transaction } = await checked(await last.get(orderPath + '/signing'))
    const raw = await wallet.signTransaction({ ...transaction, nonce: Number(transaction.nonce),
      chainId: BigInt(transaction.chainId), type: 0 })
    const sent = await checked(await last.post(orderPath + '/broadcast', { data: { raw_transaction: raw } }))
    const confirmed = await checked(await last.post(orderPath + '/confirm', {
      data: { transaction_hash: sent.transaction_hash },
    }))
    if (confirmed.status !== 'confirmed') throw Error('Synthetic entitlement was not activated')
  }
  const duplicates = await Promise.all([trial(0, peers[0], 'same-account'), trial(0, peers[0], 'same-account')])
  if (duplicates.filter(row => row.status === 200).length !== 1) throw Error('Same-owner duplicate was not rejected')
  const full = await Promise.all(peers.map((client, index) => trial(index, client, 'six-accounts')))
  const limited = full.filter(row => row.status === 429)
  if (limited.length !== 1) throw Error('Expected one overflow beyond the five admitted private jobs')
  const retry = await trial(limited[0].owner, peers[limited[0].owner], 'overflow-retry')
  if (retry.status !== 200) throw Error('Overflowed owner could not recover')
  const accepted = records.filter(row => row.status === 200)
  if (new Set(accepted.map(row => row.run_id)).size !== accepted.length) throw Error('Burst duplicated persisted results')
  await writeFile(path + '/private-burst.json', JSON.stringify({ passed: true, images: run.images, records }, null, 2))
  console.log('Private queue burst: five admitted, one overflow, retry succeeded')
} catch (error) {
  await writeFile(path + '/private-burst.json', JSON.stringify({ passed: false, images: run.images,
    error: String(error), records }, null, 2))
  throw error
} finally {
  await Promise.all(clients.map(client => client.dispose()))
}
