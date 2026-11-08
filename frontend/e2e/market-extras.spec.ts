import { execFile } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { promisify } from 'node:util'
import { test, expect, login, fixturePath } from './helpers'

test('MARKET-04 chart zoom, drag, replay trades, resume and exhausted history', async ({ page, account }) => {
  await login(page, account)
  const chart = page.locator('.chart-workspace')
  const history = chart.getByLabel('已加载K线范围')
  await expect(history).toContainText(/\d{3,} 根/)
  const canvas = chart.locator('.chart-canvas canvas').first()
  await expect(canvas).toBeVisible()
  const area = (await canvas.boundingBox())!
  const timeAxis = chart.getByLabel('当前可见K线时间范围')
  const beforeZoom = await timeAxis.innerText()
  await page.mouse.move(area.x + area.width / 2, area.y + area.height / 2)
  await page.mouse.wheel(0, -480)
  await expect.poll(() => timeAxis.innerText()).not.toBe(beforeZoom)
  const beforeDrag = await timeAxis.innerText()
  await page.mouse.down()
  await page.mouse.move(area.x + area.width * .8, area.y + area.height / 2, { steps: 8 })
  await page.mouse.up()
  await expect.poll(() => timeAxis.innerText()).not.toBe(beforeDrag)

  const beforeReplay = await page.request.get('/api/ledger').then(response => response.json())
  await chart.getByRole('button', { name: '回放', exact: true }).click()
  const index = chart.locator('.replay-status b')
  const start = Number(await index.innerText())
  await chart.getByTitle('下一根K线', { exact: true }).click()
  await expect(index).toHaveText(String(start + 1))
  await chart.getByRole('button', { name: '买入25%' }).click()
  const position = chart.locator('.replay-account em')
  await expect(position).not.toHaveText(/^仓位 0(?:\.0+)?$/)
  await chart.getByRole('button', { name: '全部卖出' }).click()
  await expect(position).toHaveText(/^仓位 0(?:\.0+)?$/)
  const equity = await chart.locator('.replay-account strong').innerText()
  await chart.getByTitle('返回实时图表').click()
  await expect(index).toBeHidden()
  await page.reload()
  await expect(history).toContainText(/\d{3,} 根/)
  await chart.getByRole('button', { name: '回放', exact: true }).click()
  await expect(index).toHaveText(String(start + 1))
  await expect(chart.locator('.replay-account strong')).toHaveText(equity)
  const afterReplay = await page.request.get('/api/ledger').then(response => response.json())
  expect(afterReplay.revision).toBe(beforeReplay.revision)
  await chart.getByTitle('返回实时图表').click()

  const count = await history.innerText()
  const loading = page.waitForRequest(request => {
    const url = new URL(request.url())
    return url.pathname.endsWith('/market/manifest') && url.searchParams.has('end')
  })
  await chart.getByRole('button', { name: '加载更早行情', exact: true }).click()
  await loading
  await expect(chart.locator('.chart-history')).toContainText(/更早行情暂不可用|未提供更早行情/)
  await expect(history).toHaveText(count)
})

test('ALERT-02 browser-triggered observation cools down and remains read after reload', async ({ page, account }) => {
  const loading = new Set<import('@playwright/test').Request>()
  page.on('request', request => { if (/\/api\/v1\/(alerts|notifications)(?:\?|$)/.test(request.url())) loading.add(request) })
  page.on('requestfinished', request => loading.delete(request))
  page.on('requestfailed', request => loading.delete(request))
  await login(page, account)
  await page.getByRole('button', { name: '提醒中心', exact: true }).click()
  const drawer = page.getByRole('dialog', { name: '提醒中心' })
  await drawer.getByRole('button', { name: '新建提醒', exact: true }).click()
  const name = 'Synthetic trigger ' + Date.now()
  await drawer.getByLabel('提醒名称', { exact: true }).fill(name)
  await drawer.getByLabel('阈值', { exact: true }).fill('1')
  const saved = page.waitForResponse(response => response.url().endsWith('/api/v1/alerts') && response.request().method() === 'POST')
  await drawer.getByRole('button', { name: '保存提醒', exact: true }).click()
  const rule = await (await saved).json()
  const path = '/api/v1/compute/alerts/' + rule.id + '/observations'
  const observed = page.waitForResponse(response => response.url().endsWith(path))
  await drawer.getByRole('button', { name: '立即检查', exact: true }).click()
  const first = (await (await observed).json()).notification
  expect(first.id).toBeTruthy()
  const notification = drawer.locator('.notification-list > div').filter({ hasText: name })
  await expect(notification).toHaveClass('is-unread')
  const repeat = await page.request.post(path, { data: { value: 2, triggered: true } })
  expect(repeat.ok()).toBeTruthy()
  expect((await repeat.json()).notification).toBeNull()
  await expect(notification).toHaveCount(1)
  await drawer.getByRole('button', { name: '全部已读', exact: true }).click()
  await expect(notification).not.toHaveClass('is-unread')
  await expect.poll(() => loading.size).toBe(0)
  await page.reload()
  await page.getByRole('button', { name: '提醒中心', exact: true }).click()
  await expect(notification).toBeVisible()
  await expect(notification).not.toHaveClass('is-unread')
})


test('MARKET-06 additional published history merges without duplicating overlapping candles', async ({ page, account }) => {
  const manifest = JSON.parse(await readFile(join(dirname(fixturePath), 'run.json'), 'utf8'))
  expect(manifest.synthetic_only).toBe(true)
  expect(manifest.project).toMatch(/^atlas-e2e-[a-z0-9-]+$/)
  expect(manifest.project).not.toContain('hour')
  const runDocker = promisify(execFile)
  const api = manifest.project + '-api-1'
  const container = JSON.parse((await runDocker('docker', ['inspect', api])).stdout)[0]
  expect(container.Config.Labels['com.docker.compose.project']).toBe(manifest.project)
  expect(container.Mounts).toEqual(expect.arrayContaining([
    expect.objectContaining({ Name: manifest.volume, Destination: '/work' }),
  ]))
  const publish = async (count: number) => {
    const result = await runDocker('docker', ['exec', api, 'python', '/e2e/history-market.py', String(count)])
    return JSON.parse(result.stdout)
  }
  try {
  const current = await publish(1000)
  await login(page, account)
  expect(new URL(page.url()).origin).toBe(manifest.origin)
  const range = page.getByLabel('已加载K线范围', { exact: true })
  await expect(range).toContainText('1000 根')
  const expanded = await publish(2000)
  expect(expanded.end).toBe(current.end)
  expect(current.start - expanded.start).toBe(1000 * 86400)
  await page.getByRole('button', { name: '加载更早行情', exact: true }).click()
  await expect(range).toContainText('2000 根')
  await page.getByRole('button', { name: '回放', exact: true }).click()
  await expect(page.locator('.replay-status em')).toHaveText('/ 2000')
  await page.getByTitle('返回实时图表').click()
  } finally {
    const restored = await runDocker('docker', ['exec', api, 'python', '/e2e/history-market.py', 'restore'])
    expect(JSON.parse(restored.stdout).restored).toBe(true)
  }
})
