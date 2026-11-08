import { test, expect, login, route, savedRun } from './helpers'

const strategies = ['all_weather', 'risk_parity', 'sixty_forty']
const frequencies = ['monthly', 'quarterly', 'yearly']
const currencies = ['CNY', 'USD', 'USDT']

for (const [i, strategy] of strategies.entries()) {
  test('PORT-03-' + strategy + ' cross-market settings reach the Worker and saved run', async ({ page, account }) => {
    test.setTimeout(90_000)
    await login(page, account)
    await route(page, '#portfolio')
    await page.getByRole('button', { name: '选择资产', exact: true }).click()
    const picker = page.getByRole('dialog', { name: '选择组合标的' })
    await picker.getByLabel('搜索可添加资产').fill('BTC-USD')
    await picker.getByRole('checkbox', { name: /BTC-USD/ }).locator('..').click()
    await picker.getByRole('button', { name: '添加所选资产', exact: true }).click()
    await expect(picker).toBeHidden()
    await page.getByLabel('组合策略').selectOption(strategy)

    for (const [j, frequency] of frequencies.entries()) {
      const currency = currencies[(i + j) % currencies.length]
      await page.getByRole('button', { name: '本地设置', exact: true }).click()
      const settings = page.getByRole('dialog', { name: '本地设置' })
      await settings.getByRole('combobox', { name: '组合基准币种', exact: true }).selectOption(currency)
      await settings.getByRole('button', { name: '关闭本地设置', exact: true }).click()
      const panel = page.locator('.portfolio-mode')
      await panel.getByLabel('再平衡频率').selectOption(frequency)
      const paid = (i + j) % 2 === 1
      const constrained = j !== 0
      await panel.getByRole('spinbutton', { name: /初始资金/ }).fill('50000')
      await panel.getByRole('spinbutton', { name: /手续费率/ }).fill(paid ? '0.6' : '0')
      await panel.getByRole('spinbutton', { name: /滑点率/ }).fill(paid ? '0.3' : '0')
      await panel.getByRole('spinbutton', { name: /买卖价差/ }).fill(paid ? '0.4' : '0')
      await panel.getByRole('spinbutton', { name: /现金缓冲/ }).fill(constrained ? '20' : '0')
      await panel.getByRole('spinbutton', { name: /单资产上限/ }).fill(constrained ? '40' : '100')
      await panel.getByRole('spinbutton', { name: /目标年化波动/ }).fill(constrained ? '5' : '0')

      const posted = page.waitForRequest(request => request.url().endsWith('/api/v1/compute/runs') && request.method() === 'POST')
      const result = await savedRun(page, () => page.getByRole('button', { name: '运行回测', exact: true }).click())
      expect((await posted).postDataJSON().request).toMatchObject({
        strategy_id: strategy, rebalance: frequency, base_currency: currency,
        initial_capital: 50000, commission_rate: paid ? 0.006 : 0,
        slippage_rate: paid ? 0.003 : 0, spread_rate: paid ? 0.004 : 0,
        cash_buffer: constrained ? 0.2 : 0, max_asset_weight: constrained ? 0.4 : 1,
        volatility_target: constrained ? 0.05 : null,
      })
      expect(result.assets.map((asset: { symbol: string }) => asset.symbol)).toContain('BTC-USD')
      expect(result.assets.map((asset: { symbol: string }) => asset.symbol)).toContain('SPY')
      expect(result.valuation_currency).toBe(currency)
      expect(result.equity.length).toBeGreaterThanOrEqual(60)
      expect(result.trades.every((trade: { cash_after: number }) => trade.cash_after >= -1e-8)).toBe(true)
      if (paid) expect(result.metrics.fees_paid).toBeGreaterThan(0)
      else expect(result.metrics.fees_paid).toBe(0)
      const stored = await page.request.get('/api/v1/runs/' + result.run_id)
      expect(stored.ok()).toBe(true)
      expect(await stored.json()).toMatchObject({
        run_id: result.run_id, valuation_currency: currency, metrics: result.metrics,
      })
    }
  })
}
