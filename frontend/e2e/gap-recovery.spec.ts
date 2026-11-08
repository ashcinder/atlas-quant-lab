import { test, expect, login, route } from './helpers'
import type { Page } from '@playwright/test'

const endpoint = '**/api/v1/strategy-projects'
const thesis = 'Synthetic strategy hypothesis: compare returns after transaction costs.'

async function startDraft(page: Page, name: string) {
  await route(page, '#research')
  await page.getByRole('button', { name: '新建策略项目', exact: true }).click()
  const draft = page.getByRole('dialog', { name: '创建策略项目', exact: true })
  await draft.getByLabel('项目名称', { exact: true }).fill(name)
  await draft.locator('textarea[name=project-thesis]').fill(thesis)
  await draft.locator('input[name=asset-symbol]').fill('BTC-USD')
  return draft
}

async function matchingProjects(page: Page, name: string) {
  const response = await page.request.get('/api/v1/strategy-projects')
  expect(response.ok()).toBeTruthy()
  return (await response.json() as Array<{ id: string; name: string; thesis: string }>).filter(project => project.name === name)
}

test('FAULT-15 a slow project save keeps its draft and prevents repeat submission', async ({ page, account }) => {
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
  const saved = page.waitForResponse(r => r.url().endsWith('/strategy-projects') && r.request().method() === 'POST')
  try {
    await draft.getByRole('button', { name: '创建策略项目', exact: true }).click()
    await expect.poll(() => arrivals).toBe(1)
    await expect(draft.getByRole('button', { name: '保存中…' })).toBeDisabled()
    await expect(draft.getByLabel('项目名称', { exact: true })).toHaveValue(name)
    await expect(draft.locator('textarea')).toHaveValue(thesis)
    await page.keyboard.press('Escape')
    await expect(draft).toBeVisible()
    expect(await matchingProjects(page, name)).toHaveLength(0)
  } finally {
    release()
  }
  expect((await saved).status()).toBe(201)
  await expect(draft).toBeHidden()
  expect(arrivals).toBe(1)
  await page.reload()
  expect(await matchingProjects(page, name)).toMatchObject([{ name, thesis }])
})

test('FAULT-16 the client timeout preserves an unsent project draft and retry saves it once', async ({ page, account }) => {
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
    await draft.getByRole('button', { name: '创建策略项目', exact: true }).click()
    await reachedRoute
    await expect(draft.getByRole('button', { name: '保存中…' })).toBeDisabled()
    await page.clock.fastForward(121_000)
    await expect(page.locator('.error-banner')).toContainText('请求超时')
    await expect(draft.getByLabel('项目名称', { exact: true })).toHaveValue(name)
    await expect(draft.locator('textarea')).toHaveValue(thesis)
    expect(await matchingProjects(page, name)).toHaveLength(0)
  } finally {
    release()
    await page.unrouteAll({ behavior: 'wait' })
  }
  const saved = page.waitForResponse(r => r.url().endsWith('/strategy-projects') && r.request().method() === 'POST')
  await draft.getByRole('button', { name: '创建策略项目', exact: true }).click()
  expect((await saved).status()).toBe(201)
  await expect(draft).toBeHidden()
  await page.reload()
  expect(await matchingProjects(page, name)).toMatchObject([{ name, thesis }])
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
