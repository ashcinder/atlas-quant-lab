import { test, expect, login, route } from './helpers'
import type { Page } from '@playwright/test'

const endpoint = '**/api/v1/lab-strategies'
const source = 'def target_bps(index, close, sma):\n    return 3000\n'

async function startDraft(page: Page, name: string) {
  await route(page, '#research')
  await page.getByRole('button', { name: '新建策略', exact: true }).click()
  const draft = page.getByRole('region', { name: '代码策略工作区', exact: true })
  await draft.getByLabel('代码策略名称', { exact: true }).fill(name)
  await draft.getByLabel('Python 策略代码').fill(source)
  return draft
}

async function matchingStrategies(page: Page, name: string) {
  const session = await (await page.request.get('/api/session')).json()
  const headers = { 'X-Atlas-Lab-Owner': session.userId }
  const response = await page.request.get('/api/v1/lab-strategies', { headers })
  expect(response.ok()).toBeTruthy()
  const items = (await response.json() as Array<{ id: string; name: string }>).filter(strategy => strategy.name === name)
  return Promise.all(items.map(async item => {
    const detail = await page.request.get('/api/v1/lab-strategies/' + item.id, { headers })
    expect(detail.ok()).toBeTruthy()
    return detail.json()
  }))
}

test('FAULT-15 a slow strategy save keeps its draft and prevents repeat submission', async ({ page, account }) => {
  await login(page, account)
  const name = 'Slow save ' + Date.now()
  const draft = await startDraft(page, name)
  let release!: () => void
  const hold = new Promise<void>(resolve => { release = resolve })
  let arrivals = 0
  await page.route(endpoint, async request => {
    if (request.request().method() !== 'POST') return request.continue()
    arrivals++
    await hold
    await request.continue()
  })
  const saved = page.waitForResponse(r => r.url().endsWith('/lab-strategies') && r.request().method() === 'POST')
  try {
    await draft.getByRole('button', { name: '保存策略', exact: true }).click()
    await expect.poll(() => arrivals).toBe(1)
    await expect(draft.getByRole('button', { name: '保存策略' })).toBeDisabled()
    await expect(draft.getByLabel('代码策略名称', { exact: true })).toHaveValue(name)
    await expect(draft.getByLabel('Python 策略代码')).toHaveValue(source)
    await page.keyboard.press('Escape')
    await expect(draft).toBeVisible()
    expect(await matchingStrategies(page, name)).toHaveLength(0)
  } finally {
    release()
  }
  expect((await saved).status()).toBe(201)
  await expect(draft.getByText('已保存', { exact: true })).toBeVisible()
  expect(arrivals).toBe(1)
  await page.reload()
  expect(await matchingStrategies(page, name)).toMatchObject([{ name, source }])
})

test('FAULT-16 the client timeout preserves an unsent strategy draft and retry saves it once', async ({ page, account }) => {
  await page.clock.install()
  await login(page, account)
  const name = 'Timeout save ' + Date.now()
  const draft = await startDraft(page, name)
  let arrive!: () => void
  const reachedRoute = new Promise<void>(resolve => { arrive = resolve })
  let release!: () => void
  const hold = new Promise<void>(resolve => { release = resolve })
  await page.route(endpoint, async request => {
    if (request.request().method() !== 'POST') return request.continue()
    arrive()
    await hold
    // The original POST never reaches the server.
    await request.abort().catch(() => undefined)
  })
  try {
    await draft.getByRole('button', { name: '保存策略', exact: true }).click()
    await reachedRoute
    await expect(draft.getByRole('button', { name: '保存策略' })).toBeDisabled()
    await page.clock.fastForward(121_000)
    await expect(page.locator('.lab-workbench .lab-error')).toContainText('请求超时')
    await expect(draft.getByLabel('代码策略名称', { exact: true })).toHaveValue(name)
    await expect(draft.getByLabel('Python 策略代码')).toHaveValue(source)
    expect(await matchingStrategies(page, name)).toHaveLength(0)
  } finally {
    release()
    await page.unrouteAll({ behavior: 'wait' })
  }
  const saved = page.waitForResponse(r => r.url().endsWith('/lab-strategies') && r.request().method() === 'POST')
  await draft.getByRole('button', { name: '保存策略', exact: true }).click()
  expect((await saved).status()).toBe(201)
  await expect(draft.getByText('已保存', { exact: true })).toBeVisible()
  await page.reload()
  expect(await matchingStrategies(page, name)).toMatchObject([{ name, source }])
})

test('FAULT-17 proof verification outage stays unverified and a retry validates the existing receipt', async ({ page, account }) => {
  const { fixture } = await import('./helpers')
  await login(page, account)
  const id = fixture().proof_id
  await route(page, '#/proof/' + id)
  const verify = page.getByRole('button', { name: '验证 Proof', exact: true })
  await expect(verify).toBeVisible()
  const path = '**/api/v1/quantjudge/zk-proofs/' + id + '/verify'
  await page.route(path, request => request.fulfill({ status: 503, json: { detail: '真实证明验证器不可用' } }))
  await verify.click()
  await expect(page.getByRole('alert')).toContainText('真实证明验证器不可用')
  await expect(page.getByRole('heading', { name: '本次密码学验证通过' })).toHaveCount(0)
  await page.unroute(path)
  const response = page.waitForResponse(r => r.url().endsWith('/zk-proofs/' + id + '/verify') && r.request().method() === 'POST')
  await verify.click()
  expect(await (await response).json()).toMatchObject({ valid: true, proof_id: id })
  await expect(page.getByRole('heading', { name: '本次密码学验证通过' })).toBeVisible()
})
