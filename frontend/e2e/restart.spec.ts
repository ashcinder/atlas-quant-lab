import { execFile } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { promisify } from 'node:util'
import { test, expect, login, route, fixturePath } from './helpers'

const docker = promisify(execFile)

async function restartIsolatedApi(origin: string) {
  const manifest = JSON.parse(await readFile(join(dirname(fixturePath), 'run.json'), 'utf8'))
  expect(manifest.synthetic_only).toBe(true)
  expect(manifest.project).toMatch(/^atlas-e2e-[a-z0-9-]+$/)
  expect(manifest.origin).toBe(origin)
  expect(manifest.port).not.toBe(18095)
  const name = manifest.project + '-api-1'
  const snapshot = async () => JSON.parse((await docker('docker', ['inspect', name])).stdout)[0]
  const before = await snapshot()
  expect(before.Config.Labels['com.docker.compose.project']).toBe(manifest.project)
  expect(before.Mounts.some((item: { Name?: string; Destination: string }) => (
    item.Name === manifest.volume && item.Destination === '/work'
  ))).toBe(true)
  await docker('docker', ['restart', name], { timeout: 30_000 })
  await expect.poll(async () => (await snapshot()).State.Health.Status, { timeout: 30_000 }).toBe('healthy')
  expect((await snapshot()).State.StartedAt).not.toBe(before.State.StartedAt)
  return name
}

test('TRADE-02 lost acknowledgement partial fill survives API restart and reconciles once', async ({ page, account, browser }) => {
  test.setTimeout(90_000)
  await login(page, account)
  await route(page, '#/trading')
  await page.getByRole('button', { name: '接入模拟账户', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('模拟 API Key', { exact: true }).fill('synthetic-partial-' + account)
  await dialog.getByLabel('模拟 API Secret', { exact: true }).fill('synthetic-secret-for-isolated-tests')
  await dialog.getByRole('checkbox').check()
  await dialog.getByRole('button', { name: '验证连接并保存', exact: true }).click()
  await expect(dialog).toContainText('模拟账户已验证并保存')
  await page.getByRole('button', { name: '关闭操作面板' }).click()
  await page.getByRole('button', { name: '人工下单', exact: true }).click()
  await page.getByLabel('交易对', { exact: true }).fill('BTC-USDT')
  await page.getByLabel('数量（基础币）').fill('0.001')
  await page.getByLabel('限价（USDT）').fill('10000')
  const previewed = page.waitForResponse(response => response.url().endsWith('/orders/preview'))
  await page.getByRole('button', { name: '预览订单', exact: true }).click()
  const order = await (await previewed).json()
  const path = '/api/v1/trading/orders/' + order.id
  const acknowledgement = page.waitForResponse(response => response.url().endsWith('/orders/' + order.id + '/confirm'))
  await page.getByLabel('确认文字', { exact: true }).fill('确认模拟下单')
  await page.getByRole('button', { name: '确认提交订单' }).click()
  expect((await (await acknowledgement).json()).state).toBe('unknown')

  // Close this browser page before the service stop so intentional downtime is
  // isolated from browser exception accounting. Its context retains the session.
  const origin = new URL(page.url()).origin
  const context = page.context()
  await page.close()
  const api = await restartIsolatedApi(origin)
  const recovered = await context.newPage()
  await recovered.goto('/#/trading')
  await expect(recovered.getByRole('button', { name: '新建运行', exact: true }).first()).toBeVisible()
  const refreshed = await recovered.request.post(path + '/refresh', { data: {} })
  expect(refreshed.ok(), await refreshed.text()).toBeTruthy()
  const found = await refreshed.json()
  expect(found.result.exchange_status).toBe('PARTIALLY_FILLED')
  expect(Number(found.result.filled_quantity)).toBe(.0004)
  const cancelled = await recovered.request.post(path + '/cancel', { data: { confirmation: '确认撤单' } })
  expect(cancelled.ok(), await cancelled.text()).toBeTruthy()
  for (let i = 0; i < 2; i++) {
    expect((await recovered.request.post(path + '/confirm', { data: { confirmation: '确认模拟下单' } })).ok()).toBeTruthy()
    const state = await (await recovered.request.post(path + '/refresh', { data: {} })).json()
    expect(state.result.exchange_status).toBe('CANCELED')
    expect(Number(state.result.filled_quantity)).toBe(.0004)
  }

  const ledger = await (await recovered.request.get('/api/v1/ledger/trades')).json()
  const fills = ledger.fills.filter((fill: { order_id: string }) => fill.order_id === order.id)
  expect(fills).toHaveLength(1)
  expect(Number(fills[0].quantity)).toBe(.0004)
  expect(Number(fills[0].fee)).toBe(.004)
  expect(fills[0].realized_pnl).toBeNull()
  const counter = await docker('docker', ['exec', api, 'python', '-c',
    'import sqlite3,sys; db=sqlite3.connect("/work/synthetic-binance.sqlite"); print(db.execute("SELECT submit_calls FROM orders WHERE client_id=?", (sys.argv[1],)).fetchone()[0])',
    order.id])
  expect(counter.stdout.trim()).toBe('1')

  const outsider = await browser.newContext()
  try {
    const denied = await outsider.newPage()
    await login(denied, 'outsider')
    const otherLedger = await (await denied.request.get('/api/v1/ledger/trades')).json()
    expect(otherLedger.fills.some((fill: { order_id: string }) => fill.order_id === order.id)).toBe(false)
  } finally {
    await outsider.close()
  }
})
