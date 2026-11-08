import { test, expect, login, route, savedRun } from './helpers'

test('PORT-02 asset capacity, duplicates, weights and one missing market recover safely', async ({ page, account }) => {
  test.setTimeout(100_000)
  await login(page, account)
  await route(page, '#portfolio')
  const rows = page.locator('.allocation-row:not(.header)')
  await expect(rows.first()).toBeVisible()
  const original = await rows.locator('strong').allTextContents()
  const picker = page.getByRole('dialog', { name: '选择组合标的' })
  const open = page.getByRole('button', { name: '选择资产', exact: true })
  await open.click()
  const search = picker.getByLabel('搜索可添加资产')
  await search.fill(original[0])
  await expect(picker.getByRole('checkbox', { name: new RegExp(original[0], 'i') })).toHaveCount(0)
  await search.clear()
  await picker.getByRole('checkbox').first().locator('..').click()
  await picker.getByRole('button', { name: '取消', exact: true }).click()
  await expect(rows).toHaveCount(original.length)

  await open.click()
  const candidates = picker.getByRole('checkbox')
  for (let slot = 0; slot < 12 - original.length; slot++) {
    await candidates.nth(slot).locator('..').click()
    await expect(candidates.nth(slot)).toBeChecked()
  }
  await expect(candidates.nth(12 - original.length)).toBeDisabled()
  await picker.getByRole('button', { name: '添加所选资产', exact: true }).click()
  await expect(rows).toHaveCount(12)
  await expect(open).toBeDisabled()
  const names = await rows.locator('strong').allTextContents()
  expect(new Set(names).size).toBe(12)
  for (const asset of names.slice(2)) await page.getByRole('button', { name: '移除 ' + asset, exact: true }).click()
  await expect(rows).toHaveCount(2)
  await expect(page.getByRole('button', { name: '移除 ' + names[0], exact: true })).toBeDisabled()
  await expect(open).toBeEnabled()

  await page.getByLabel(names[0] + ' 目标权重', { exact: true }).fill('30')
  await page.getByLabel(names[1] + ' 目标权重', { exact: true }).fill('20')
  await expect(page.locator('.weight-total')).toContainText('50.00%')
  await page.getByRole('button', { name: '归一化至100%', exact: true }).click()
  await expect(page.getByLabel(names[0] + ' 目标权重', { exact: true })).toHaveValue('60.0')
  await expect(page.getByLabel(names[1] + ' 目标权重', { exact: true })).toHaveValue('40.0')
  await expect(page.locator('.weight-total')).toContainText('100.00%')

  const routePattern = '**/api/v1/market/manifest?*'
  let missing = 0
  await page.route(routePattern, async request => {
    if (new URL(request.request().url()).searchParams.get('symbol') !== names[1]) return request.continue()
    missing++
    await request.fulfill({ status: 202, json: { status: 'preparing', message: names[1] + ' 行情尚未发布' } })
  })
  let saved = 0
  page.on('request', request => {
    if (request.url().endsWith('/api/v1/compute/runs') && request.method() === 'POST') saved++
  })
  const run = page.getByRole('button', { name: '运行回测', exact: true })
  await run.click()
  await expect(page.getByText(names[1] + ' 行情尚未发布', { exact: true })).toBeVisible()
  expect(missing).toBeGreaterThan(0)
  expect(saved).toBe(0)
  await page.unroute(routePattern)
  const recovered = await savedRun(page, () => run.click())
  expect(recovered.assets.map((asset: { symbol: string }) => asset.symbol)).toEqual(names.slice(0, 2))
  expect(saved).toBe(1)
})
