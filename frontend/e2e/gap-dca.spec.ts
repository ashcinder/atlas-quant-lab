import { test, expect, login, route, resetLedger } from './helpers'

test('PLAN-03 automatic bookkeeping backfills once across reload and another tab without trading', async ({ page, account, context }) => {
  await login(page, account)
  await resetLedger(page)
  await page.reload()
  await route(page, '#/journal/accounts')
  await page.getByRole('button', { name: '新增账户', exact: true }).click()
  let dialog = page.getByRole('dialog')
  await dialog.getByLabel('账户名称', { exact: true }).fill('Synthetic automatic plan account')
  await dialog.getByRole('button', { name: '保存账户', exact: true }).click()
  await expect(dialog).toBeHidden()

  await route(page, '#/journal/plans')
  await expect(page.getByText(/这不代表实际扣款或成交/)).toBeVisible()
  await page.getByRole('button', { name: '新建计划', exact: true }).click()
  dialog = page.getByRole('dialog')
  const name = 'Synthetic automatic plan'
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
  await dialog.getByLabel('计划名称', { exact: true }).fill(name)
  await dialog.getByRole('combobox', { name: /记账方式/ }).selectOption('auto')
  await dialog.getByLabel('每次投入（USD）', { exact: true }).fill('23.45')
  await dialog.getByRole('combobox', { name: '投入频率', exact: true }).selectOption('daily')
  await dialog.getByLabel('执行时间 · 北京时间', { exact: true }).fill('00:00')
  await dialog.getByLabel('开始日期', { exact: true }).fill(today)
  const tradingPosts: string[] = []
  page.on('request', r => {
    if (r.method() !== 'GET' && /\/trading\//.test(r.url())) tradingPosts.push(r.url())
  })
  await dialog.getByRole('button', { name: '保存计划', exact: true }).click()
  await expect(dialog).toBeHidden()
  const ledger = async () => (await (await page.request.get('/api/ledger')).json()).state
  const first = await ledger()
  expect(first.entries).toHaveLength(1)
  expect(first.entries[0]).toMatchObject({ kind: 'deposit', amount: 23.45, date: today, automatic: true })
  expect(first.entries[0].planKey).toContain(first.plans[0].id)
  expect(first.entries[0].note).toContain('不代表实际成交')

  const other = await context.newPage()
  try {
    await Promise.all([page.reload(), other.goto('/#/journal/plans')])
    await expect(other.getByText(name, { exact: true }).first()).toBeVisible()
    await expect(page.getByText(name, { exact: true }).first()).toBeVisible()
    expect((await ledger()).entries).toEqual(first.entries)
    const card = page.locator('.plan-card').filter({ hasText: name })
    await card.getByRole('button', { name: '暂停', exact: true }).click()
    await expect(card.getByRole('button', { name: '恢复', exact: true })).toBeVisible()
    await page.reload()
    expect((await ledger()).plans[0].paused).toBe(true)
    expect((await ledger()).entries).toEqual(first.entries)
  } finally {
    await other.close()
  }
  expect(tradingPosts).toEqual([])
})
