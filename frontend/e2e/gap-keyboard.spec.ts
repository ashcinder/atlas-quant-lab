import type { Locator, Page } from '@playwright/test'
import { test, expect, login, route } from './helpers'
import { importSyntheticWallet } from './role-flow'

async function openByKeyboard(trigger: Locator) {
  await trigger.focus()
  await expect(trigger).toBeFocused()
  await trigger.press('Enter')
}

async function focusIn(dialog: Locator) {
  await expect.poll(() => dialog.evaluate(node => node.contains(document.activeElement))).toBe(true)
}

async function closeByKeyboard(page: Page, dialog: Locator, trigger: Locator) {
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
}

// Historical r23 browser path. The code workbench has no legacy project/visual editor entry.
test.skip('A11Y-03 project editor traps keyboard focus and restores it on Escape', async ({ page, account }) => {
  await login(page, account)
  await route(page, '#research')
  const trigger = page.getByRole('button', { name: '新建策略项目', exact: true })
  await openByKeyboard(trigger)
  const dialog = page.getByRole('dialog', { name: '创建策略项目', exact: true })
  await expect(dialog.getByLabel('项目名称', { exact: true })).toBeFocused()
  const close = dialog.getByRole('button', { name: '关闭项目编辑器' })
  const submit = dialog.getByRole('button', { name: '创建策略项目', exact: true })
  await page.keyboard.press('Shift+Tab')
  await expect(close).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(submit).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(close).toBeFocused()
  await closeByKeyboard(page, dialog, trigger)
})

test('A11Y-04 portfolio picker contains keyboard focus and returns it after cancellation', async ({ page, account }) => {
  await login(page, account)
  await route(page, '#portfolio')
  const trigger = page.getByRole('button', { name: '选择资产', exact: true })
  await openByKeyboard(trigger)
  const dialog = page.getByRole('dialog', { name: '选择组合标的' })
  await expect(dialog.getByLabel('搜索可添加资产')).toBeFocused()
  const close = dialog.getByRole('button', { name: '关闭资产选择器' })
  await close.focus()
  await page.keyboard.press('Shift+Tab')
  await expect(dialog.getByRole('button', { name: '取消', exact: true })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(close).toBeFocused()
  await closeByKeyboard(page, dialog, trigger)
})

test('A11Y-05 alerts drawer receives and contains focus and restores its opener', async ({ page, account }) => {
  await login(page, account)
  const trigger = page.getByRole('button', { name: '提醒中心', exact: true })
  await openByKeyboard(trigger)
  const dialog = page.getByRole('dialog', { name: '提醒中心', exact: true })
  await focusIn(dialog)
  const close = dialog.getByRole('button', { name: '关闭提醒中心' })
  await close.focus()
  await page.keyboard.press('Shift+Tab')
  await focusIn(dialog)
  await closeByKeyboard(page, dialog, trigger)
})

test('A11Y-06 date picker and ledger form take keyboard focus and return it on Escape', async ({ page, account }) => {
  await login(page, account)
  const dateTrigger = page.locator('.period-open').first()
  await openByKeyboard(dateTrigger)
  const dateDialog = page.getByRole('dialog', { name: '回测时间设置' })
  await focusIn(dateDialog)
  await expect(dateDialog.getByLabel('回测开始时间')).toBeVisible()
  await closeByKeyboard(page, dateDialog, dateTrigger)
  await route(page, '#/journal/accounts')
  const ledgerTrigger = page.getByRole('button', { name: '新增账户', exact: true })
  await openByKeyboard(ledgerTrigger)
  const ledgerDialog = page.getByRole('dialog')
  await focusIn(ledgerDialog)
  await page.keyboard.press('Tab')
  await focusIn(ledgerDialog)
  await closeByKeyboard(page, ledgerDialog, ledgerTrigger)
})

test('A11Y-07 saved-run history drawer has keyboard entry, wrap and return', async ({ page, account }) => {
  await login(page, account)
  const trigger = page.getByRole('button', { name: '回测历史', exact: true })
  await openByKeyboard(trigger)
  const dialog = page.getByRole('dialog', { name: '回测历史' })
  const close = dialog.getByRole('button', { name: '关闭回测历史', exact: true })
  await expect(close).toBeFocused()
  await page.keyboard.press('Tab')
  await focusIn(dialog)
  await page.keyboard.press('Shift+Tab')
  await expect(close).toBeFocused()
  await closeByKeyboard(page, dialog, trigger)
})

test('A11Y-08 strategy marketplace creation dialog keeps focus within its boundaries', async ({ page, account }) => {
  await login(page, account)
  await route(page, '#quantjudge')
  const trigger = page.getByRole('button', { name: '创建策略身份', exact: true })
  await openByKeyboard(trigger)
  const dialog = page.getByRole('dialog', { name: '创建公开策略身份', exact: true })
  await focusIn(dialog)
  const close = dialog.getByRole('button', { name: '关闭创建窗口', exact: true })
  const cancel = dialog.getByRole('button', { name: '取消', exact: true })
  await close.focus()
  await page.keyboard.press('Shift+Tab')
  await expect(cancel).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(close).toBeFocused()
  await closeByKeyboard(page, dialog, trigger)
})

test('A11Y-09 modeless payment confirmation supports Escape and returns focus without broadcasting', async ({ page }) => {
  await login(page, 'author')
  const release = await (await page.request.post('/api/v1/strategy-releases', { data: {
    name: 'Keyboard payment ' + Date.now(), source_kind: 'builtin', strategy_id: 'sma_cross',
    params: { fast: 5, slow: 20 }, markets: ['CRYPTO'], source_visibility: 'private', published: true,
  } })).json()
  expect((await page.request.put('/api/v1/strategy-releases/' + release.id + '/bkc-offer', {
    data: { recipient: '0x' + '37'.repeat(20), amount_bkc: '0.01' },
  })).ok()).toBe(true)
  await page.context().clearCookies()
  await login(page, 'outsider')
  await importSyntheticWallet(page, '0x' + '39'.repeat(32))
  await route(page, '#quantjudge')
  await page.getByRole('button', { name: '可运行策略', exact: true }).click()
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: release.name, exact: true }) })
  const preparing = page.waitForResponse(response => response.url().endsWith('/' + release.id + '/bkc-order'))
  await card.getByRole('button', { name: '使用 BKC 订阅此版本', exact: true }).click()
  const order = await (await preparing).json()
  expect(order.id).toBeTruthy()
  const trigger = card.getByRole('button', { name: '支付 / 核验 BKC', exact: true })
  await openByKeyboard(trigger)
  const dialog = page.getByRole('dialog', { name: '确认 BKC 支付' })
  await focusIn(dialog)
  await expect(dialog).not.toHaveAttribute('aria-modal', 'true')
  await closeByKeyboard(page, dialog, trigger)
  let releaseBroadcast!: () => void
  let started!: () => void
  const broadcastHeld = new Promise<void>(resolve => { releaseBroadcast = resolve })
  const broadcastStarted = new Promise<void>(resolve => { started = resolve })
  await page.route('**/api/v1/bkc-orders/' + order.id + '/broadcast', async intercepted => {
    started()
    await broadcastHeld
    await intercepted.abort('failed')
  })
  await openByKeyboard(trigger)
  await dialog.getByRole('button', { name: '确认支付', exact: true }).click()
  try {
    await broadcastStarted
    await expect(dialog.getByRole('button', { name: '取消', exact: true })).toBeDisabled()
    await page.keyboard.press('Escape')
    await expect(dialog).toBeVisible()
    await page.keyboard.press('Tab')
    await expect(dialog).toBeVisible()
  } finally { releaseBroadcast() }
  await expect(card.getByRole('alert')).toBeVisible()
  await expect(dialog.getByRole('button', { name: '取消', exact: true })).toBeEnabled()
  await closeByKeyboard(page, dialog, trigger)
  expect((await (await page.request.get('/api/v1/bkc-orders/' + order.id)).json()).transaction_hash).toBeNull()
})

test('A11Y-10 trading composer and unsaved-change confirmation contain focus and cancel safely', async ({ page }) => {
  const { fixture } = await import('./helpers')
  await login(page, 'author')
  await route(page, '#/trading')
  const trigger = page.getByRole('button', { name: '新建运行', exact: true }).first()
  await openByKeyboard(trigger)
  const dialog = page.getByRole('dialog', { name: '新建策略运行' })
  await focusIn(dialog)
  await dialog.getByRole('combobox', { name: '策略版本', exact: true }).selectOption(fixture().releases.public)
  await page.keyboard.press('Shift+Tab')
  await focusIn(dialog)
  await closeByKeyboard(page, dialog, trigger)

  await route(page, '#research')
  await openByKeyboard(page.getByRole('button', { name: '新建策略', exact: true }))
  const name = page.getByLabel('代码策略名称', { exact: true })
  await name.fill('Draft keyboard confirmation')
  await openByKeyboard(page.getByRole('button', { name: '我的策略', exact: true }))
  const confirm = page.getByRole('alertdialog')
  await focusIn(confirm)
  await page.keyboard.press('Tab')
  await focusIn(confirm)
  await page.keyboard.press('Escape')
  await expect(confirm).toBeHidden()
  await expect(name).toHaveValue('Draft keyboard confirmation')
})

test('A11Y-11 system-status dialog opens by keyboard and returns its focus', async ({ page, account }) => {
  await login(page, account)
  const trigger = page.getByRole('button', { name: '系统状态', exact: true }).first()
  await openByKeyboard(trigger)
  const dialog = page.getByRole('dialog', { name: /系统状态/ })
  await focusIn(dialog)
  await page.keyboard.press('Tab')
  await focusIn(dialog)
  await closeByKeyboard(page, dialog, trigger)
})

// Historical r23 browser path. The code workbench has no legacy project/visual editor entry.
test.skip('A11Y-12 retained hidden project drafts cannot intercept another workspace Escape', async ({ page, account }) => {
  await login(page, account)
  await route(page, '#research')
  await openByKeyboard(page.getByRole('button', { name: '新建策略项目', exact: true }))
  const editor = page.getByRole('dialog', { name: '创建策略项目', exact: true })
  await editor.getByLabel('项目名称', { exact: true }).fill('Retained hidden draft')
  await route(page, '#single')
  const trigger = page.getByRole('button', { name: '系统状态', exact: true }).first()
  await openByKeyboard(trigger)
  await closeByKeyboard(page, page.getByRole('dialog', { name: /系统状态/ }), trigger)
  await expect(page.getByRole('alertdialog', { includeHidden: true })).toHaveCount(0)
  await route(page, '#research')
  await expect(editor.getByLabel('项目名称', { exact: true })).toHaveValue('Retained hidden draft')
  await focusIn(editor)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('alertdialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(editor.getByLabel('项目名称', { exact: true })).toHaveValue('Retained hidden draft')
})

test('A11Y-13 a retained portfolio picker restores focus when its workspace returns', async ({ page, account }) => {
  await login(page, account)
  await route(page, '#portfolio')
  await openByKeyboard(page.getByRole('button', { name: '选择资产', exact: true }))
  const picker = page.getByRole('dialog', { name: '选择组合标的' })
  await picker.getByLabel('搜索可添加资产').fill('BTC')
  await route(page, '#single')
  await page.keyboard.press('Escape')
  await route(page, '#portfolio')
  await expect(picker.getByLabel('搜索可添加资产')).toHaveValue('BTC')
  await focusIn(picker)
})
