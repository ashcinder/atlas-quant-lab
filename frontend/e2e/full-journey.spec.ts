import { execFile } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { promisify } from 'node:util'
import type { Page } from '@playwright/test'
import { Wallet } from 'ethers'
import { test, expect, fixturePath, login, route, savedRun } from './helpers'
import { importSyntheticWallet, showRuntimeMarket } from './role-flow'

const docker = promisify(execFile)

async function publishMarket(page: Page, end: number, next: boolean, restore = false) {
  const manifest = JSON.parse(await readFile(join(dirname(fixturePath), 'run.json'), 'utf8'))
  expect(manifest.synthetic_only).toBe(true)
  expect(manifest.project).toMatch(/^atlas-e2e-[a-z0-9-]+$/)
  expect(manifest.project).not.toContain('hour')
  expect(manifest.origin).toBe(new URL(page.url()).origin)
  expect(manifest.port).not.toBe(18095)
  const name = manifest.project + '-api-1'
  const state = JSON.parse((await docker('docker', ['inspect', name])).stdout)[0]
  expect(state.Config.Labels['com.docker.compose.project']).toBe(manifest.project)
  expect(state.Mounts).toEqual(expect.arrayContaining([
    expect.objectContaining({ Name: manifest.volume, Destination: '/work' }),
  ]))
  const { stdout } = await docker('docker', ['exec', name, 'python', '/e2e/role-market.py',
    ...(restore ? ['restore'] : [String(end), next ? '1' : '0'])])
  return JSON.parse(stdout)
}

test.afterEach(async ({ page }) => { await publishMarket(page, 0, false, true) })

async function confirmWalletOrder(page: Page, parent: ReturnType<Page['locator']>) {
  await parent.getByRole('button', { name: '支付 / 核验 BKC' }).click()
  const dialog = page.getByRole('dialog', { name: '确认 BKC 支付' })
  const confirmed = page.waitForResponse(response =>
    /\/bkc-orders\/[^/]+\/confirm$/.test(response.url()) && response.request().method() === 'POST')
  await dialog.getByRole('button', { name: '确认支付' }).click()
  const response = await confirmed
  expect(response.ok(), await response.text()).toBeTruthy()
  const order = await response.json()
  expect(order.status).toBe('confirmed')
  expect(order.transaction_hash).toMatch(/^0x[0-9a-f]{64}$/)
  await expect(dialog).toBeHidden()
  return order
}

// Historical r23 browser path. The code workbench has no legacy project/visual editor entry.
test.skip('JOURNEY-full author freezes evidence and subscriber settles the next candle once', async ({ page, browser }, info) => {
  test.setTimeout(180_000)
  const unique = Date.now()
  const name = 'QA Trend ' + unique
  const ruleId = 'qa_trend_' + unique
  const authorKey = '0x' + '17'.repeat(32)
  const recipient = new Wallet(authorKey).address
  const end = (Math.floor(Date.now() / 86_400_000) - 3) * 86_400

  await login(page, 'author')
  const original = await publishMarket(page, end, false)
  expect(original.count).toBe(1000)
  await importSyntheticWallet(page, authorKey)
  await route(page, '#research')
  await page.getByRole('button', { name: '新建策略项目', exact: true }).click()
  const create = page.getByRole('dialog')
  await create.locator('[name=project-name]').fill(name)
  await create.locator('[name=project-thesis]').fill('Trade a deterministic synthetic trend with transaction costs and a holdout.')
  await create.locator('[name=asset-symbol]').fill('BTC-USD')
  const creating = page.waitForResponse(response => response.url().endsWith('/strategy-projects') && response.request().method() === 'POST')
  await create.getByRole('button', { name: '创建策略项目', exact: true }).click()
  const projectResponse = await creating
  expect(projectResponse.status(), await projectResponse.text()).toBe(201)
  const project = await projectResponse.json()
  const readProject = async () => (await page.request.get('/api/v1/strategy-projects/' + project.id)).json()
  await expect(page.getByLabel('选择策略项目')).toHaveValue(project.id)

  await page.getByRole('button', { name: '买卖条件', exact: true }).click()
  const builder = page.locator('.builder-canvas')
  await builder.getByLabel('策略名称', { exact: true }).fill(name)
  await page.getByLabel('策略 ID', { exact: true }).fill(ruleId)
  for (const period of await page.getByLabel('指标周期', { exact: true }).all()) await period.fill('3')
  await page.getByRole('button', { name: '保存模板', exact: true }).click()
  await expect.poll(async () => (await readProject()).custom_strategy_id).toBe(ruleId)
  const backtest = await savedRun(page, () => page.getByRole('button', { name: '运行自定义回测', exact: true }).click())
  expect(backtest.strategy.id).toBe(ruleId)
  expect(backtest.metrics.total_return).toBeGreaterThan(0)
  const result = page.getByRole('region', { name: '回测结果' })
  await result.getByRole('button', { name: '公开回测收益并上链' }).click()
  const report = await confirmWalletOrder(page, result.locator('.bkc-order-panel'))
  expect(report.payload.claim).toBe('report-anchored-only')
  expect(report.payload.run_id).toBe(backtest.run_id)
  expect(report.payload.metrics.total_return).toBe(backtest.metrics.total_return)
  expect(report.payload.report_hash).toMatch(/^[a-f0-9]{64}$/)

  const agentResponse = await page.request.post('/api/v1/quantjudge/agents', {
    data: { name, developer_alias: 'Synthetic QA author', category: 'timing', asset_classes: ['crypto'],
      description: 'Isolated QA workflow for a deterministic trend rule.', strategy_commitment: '9'.repeat(64) },
  })
  expect(agentResponse.status()).toBe(201)
  const agent = await agentResponse.json()
  await route(page, '#research')
  await page.getByRole('button', { name: '交易流程', exact: true }).click()
  await page.getByText('高级工作流档案', { exact: true }).click()
  await expect(page.getByText('结构有效', { exact: true }).first()).toBeVisible()
  await page.locator('details.guided-save-settings summary').click()
  await page.getByLabel('选择用于归属工作流的策略身份').selectOption(agent.agent.id)
  await page.getByLabel('开发者凭证', { exact: true }).fill(agent.developer_token)
  await page.getByRole('button', { name: /^(保存修订|保存版本)$/ }).click()
  await expect.poll(async () => (await readProject()).hard_risk_gates).toBeGreaterThan(0)
  await page.getByLabel('开发者凭证', { exact: true }).fill('')

  await page.getByRole('button', { name: '参数测试', exact: true }).click()
  await page.locator('.strategy-checks input:checked').evaluateAll(inputs =>
    inputs.forEach(input => (input as HTMLInputElement).click()))
  await page.locator('.strategy-checks').getByRole('checkbox', { name: new RegExp(name) }).check()
  await page.getByLabel('训练', { exact: true }).fill('200')
  await page.getByLabel('测试', { exact: true }).fill('120')
  await page.getByLabel('步长', { exact: true }).fill('120')
  await page.getByRole('button', { name: '运行稳健性研究', exact: true }).click()
  await expect(page.locator('.research-table')).toContainText(name, { timeout: 30_000 })
  await expect.poll(async () => {
    const state = await readProject()
    return { status: state.research_status, remaining: state.next_gate?.id ?? null }
  }, { timeout: 20_000 }).toEqual({ status: 'completed', remaining: 'version' })

  await page.locator('.project-gate-button').click()
  await page.getByRole('button', { name: '冻结不可变版本', exact: true }).click()
  await page.getByRole('button', { name: '确认冻结 v1.0.0', exact: true }).click()
  await expect.poll(async () => (await readProject()).commitment).toMatch(/^[a-f0-9]{64}$/)
  const frozen = await readProject()
  expect(frozen.version).toBe('1.0.0')
  expect(frozen.oos_trade_count).toBeGreaterThanOrEqual(30)
  expect(frozen.walk_forward_windows).toBeGreaterThanOrEqual(3)

  await page.getByRole('button', { name: '买卖条件', exact: true }).click()
  await expect(builder.getByLabel('策略名称', { exact: true })).toHaveValue(name)
  const saving = page.waitForResponse(response => response.url().endsWith('/strategy-releases') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '保存并订阅运行版本', exact: true }).click()
  const releaseResponse = await saving
  expect(releaseResponse.ok(), await releaseResponse.text()).toBeTruthy()
  const release = await releaseResponse.json()
  expect(release.name).toBe(name)
  expect(release.source_kind).toBe('custom')
  expect(release.strategy_id).toBe(ruleId)
  const templates = await (await page.request.get('/api/v1/custom-strategies')).json()
  const savedRule = templates.find((record: { id: string }) => record.id === ruleId)
  const releasedRule = releaseResponse.request().postDataJSON().custom_strategy
  expect(savedRule.spec).toMatchObject(releasedRule)
  expect(releasedRule).toMatchObject({
    id: ruleId, target_position: .95,
    entry: { combinator: 'all', children: [{ operator: 'crosses_above', right_indicator: { field: 'sma', period: 3 } }] },
    exit: { combinator: 'any', children: [{ operator: 'crosses_below', right_indicator: { field: 'sma', period: 3 } }] },
  })
  await page.getByRole('button', { name: '发布与 Proof' }).click()
  await page.getByRole('button', { name: '直接公开策略', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('已公开 · 无 ZKP 验证')
  await page.getByRole('button', { name: '关闭发布窗口' }).click()

  await showRuntimeMarket(page)
  await page.getByRole('button', { name: '我的策略', exact: true }).click()
  const authorCard = page.getByRole('article').filter({ has: page.getByRole('heading', { name, exact: true }) })
  await authorCard.getByText('设置 BKC 订阅价格', { exact: true }).click()
  await authorCard.getByLabel('Supervisor 收款地址').fill(recipient)
  await authorCard.getByLabel('BKC订阅价格').fill('0.01')
  await authorCard.getByRole('button', { name: '固定价格与收款地址' }).click()
  await expect(authorCard).toContainText('0.01 BKC / 当前版本')
  await authorCard.getByRole('button', { name: '策略版本上链' }).click()
  const anchor = await confirmWalletOrder(page, authorCard.locator('.trine-chain-card'))
  expect(anchor.payload.content_hash).toBe(release.content_hash)
  expect(anchor.payload.claim).toBe('version-anchored-only')

  const context = await browser.newContext()
  const subscriberTraffic: { path: string; status: number }[] = []
  const subscriberErrors: string[] = []
  const subscriber = await context.newPage()
  try {
    subscriber.on('response', response => {
      const path = new URL(response.url()).pathname
      if (path.startsWith('/api/')) subscriberTraffic.push({ path, status: response.status() })
    })
    subscriber.on('pageerror', error => subscriberErrors.push(error.message))
    await login(subscriber, 'outsider')
    await importSyntheticWallet(subscriber, '0x' + '18'.repeat(32))
    await showRuntimeMarket(subscriber)
    const card = subscriber.getByRole('article').filter({ has: subscriber.getByRole('heading', { name, exact: true }) })
    await card.getByText(/版本已存证 · 作者存证/).click()
    await expect(card).toContainText(anchor.transaction_hash)
    await expect(card).toContainText(release.content_hash)
    await card.getByRole('button', { name: '使用 BKC 订阅此版本' }).click()
    const paid = await confirmWalletOrder(subscriber, card.locator('.bkc-order-panel'))
    expect(paid.payload.release_id).toBe(release.id)
    await expect(card.getByText('已订阅此版本')).toBeVisible()
    const subscriptions = await (await subscriber.request.get('/api/v1/strategy-subscriptions')).json()
    const matching = subscriptions.filter((item: { release_id: string }) => item.release_id === release.id)
    expect(matching).toHaveLength(1)

    await route(subscriber, '#single')
    await subscriber.reload()
    const source = subscriber.getByRole('combobox', { name: '策略来源' })
    await source.selectOption(release.id)
    await expect(source).toHaveValue(release.id)
    const capability = await (await subscriber.request.get('/api/v1/compute/capabilities?release_id=' + release.id)).json()
    expect(capability.execution_location).toBe('server_private')
    expect(capability).not.toHaveProperty('strategy')
    const calculating = subscriber.waitForResponse(response =>
      response.url().endsWith('/compute/private-backtests') && response.request().method() === 'POST', { timeout: 45_000 })
    await subscriber.getByRole('button', { name: '运行回测', exact: true }).click()
    const privateResponse = await calculating
    expect(privateResponse.ok(), await privateResponse.text()).toBeTruthy()
    const privateRun = await privateResponse.json()
    expect(privateRun.compute.execution_location).toBe('server_private')
    expect(privateRun.compute.proof_status).toBe('unverified')
    expect(privateRun).not.toHaveProperty('custom_strategy')
    await expect(subscriber.getByRole('region', { name: '回测结果' })).toContainText('平台保密计算')

    await route(subscriber, '#/trading?release=' + release.id + '&subscription=' + matching[0].id)
    const creatingRun = subscriber.waitForResponse(response =>
      response.url().endsWith('/trading/runs') && response.request().method() === 'POST')
    await subscriber.getByRole('button', { name: '启动模拟', exact: true }).click()
    const started = await creatingRun
    expect(started.ok(), await started.text()).toBeTruthy()
    const run = await started.json()
    const path = '/api/v1/trading/runs/' + run.id
    const detail = async () => (await subscriber.request.get(path)).json()
    await expect.poll(async () => (await detail()).signals?.[0]?.bar_time, { timeout: 35_000 }).toBe(end)
    expect((await detail()).fills).toEqual([])
    expect(Number((await detail()).signals[0].target)).toBeGreaterThan(0)
    const next = await publishMarket(subscriber, end, true)
    expect(next.count).toBe(1001)
    expect(next.end).toBe(end + 86_400)
    const instance = subscriber.locator('article[id=' + JSON.stringify(run.id) + ']')
    await instance.getByRole('button', { name: '运行详情', exact: true }).click()
    await expect.poll(async () => (await detail()).fills?.length, { timeout: 40_000 }).toBe(1)
    const fill = (await detail()).fills[0]
    expect(fill.side).toBe('buy')
    expect(Date.parse(fill.executed_at) / 1000).toBe(next.end)
    expect(Number(fill.price)).toBeGreaterThanOrEqual(110)
    const ledger = await (await subscriber.request.get('/api/v1/ledger/trades?run_id=' + run.id)).json()
    expect(ledger.fills.map((trade: { id: string }) => trade.id)).toEqual([fill.id])
    await instance.getByRole('link', { name: '成交与账本' }).click()
    await expect(subscriber).toHaveURL(new RegExp('run=' + run.id + '$'))
    await expect(subscriber.getByRole('row').filter({ hasText: 'BTC-USD' }).first()).toBeVisible()
    await route(subscriber, '#/trading')
    const open = instance.getByRole('button', { name: '运行详情', exact: true })
    if (await open.isVisible()) await open.click()
    await instance.getByRole('button', { name: '停止', exact: true }).click()
    await expect.poll(async () => (await detail()).status).toBe('stopped')
    expect((await detail()).fills.map((trade: { id: string }) => trade.id)).toEqual([fill.id])

    await showRuntimeMarket(subscriber)
    await subscriber.getByRole('navigation', { name: '可运行策略', exact: true })
      .getByRole('button', { name: '我的订阅', exact: true }).click()
    await subscriber.getByRole('button', { name: '取消订阅 ' + name }).click()
    await expect(subscriber.getByRole('article').filter({ hasText: name })).toContainText('已取消')
    const denied = await subscriber.request.post('/api/v1/trading/runs', { data: {
      release_id: release.id, subscription_id: matching[0].id, market: 'CRYPTO',
      environment: 'platform_sim', symbol: 'BTC-USD', interval: '1d', initial_cash: '10000',
    } })
    expect(denied.status()).toBe(403)
    await info.attach('journey.json', { contentType: 'application/json', body: JSON.stringify({
      version: frozen.version, commitment: frozen.commitment, windows: frozen.walk_forward_windows,
      oos_trades: frozen.oos_trade_count, release_hash: release.content_hash, report_hash: report.payload.report_hash,
      market_snapshots: [original.dataset_id, next.dataset_id], fills: 1, fill_candle: next.end,
    }, null, 2) })
    expect(subscriberErrors).toEqual([])
    expect(subscriberTraffic.filter(item => item.status >= 500)).toEqual([])
  } catch (error) {
    const alerts = await subscriber.getByRole('alert').allTextContents().catch(() => [])
    await info.attach('subscriber-diagnostic.json', { contentType: 'application/json', body: JSON.stringify({
      hash: new URL(subscriber.url()).hash, alerts, subscriberTraffic, subscriberErrors,
    }, null, 2) })
    throw error
  } finally {
    await context.close()
  }
})
