import { fileURLToPath } from 'node:url'
import { test, expect, login, route, resetLedger } from './helpers'
import type { Locator, Page } from '@playwright/test'

const ocrModel = process.env.ATLAS_E2E_OCR_MODEL ?? fileURLToPath(
  new URL('../../.artifacts/comprehensive-20261108/samples/eng.traineddata.gz', import.meta.url),
)

async function openByKeyboard(trigger: Locator) {
  await trigger.focus()
  await expect(trigger).toBeFocused()
  await trigger.press('Enter')
}

async function expectFocusInside(dialog: Locator) {
  await expect.poll(() => dialog.evaluate(node => node.contains(document.activeElement))).toBe(true)
}

async function createReadyRuntimeVersion(page: Page) {
  await route(page, '#research')
  await page.getByRole('button', { name: '模板', exact: true }).click()
  await page.getByLabel('策略名称', { exact: true }).fill('Keyboard publish ' + Date.now())
  await page.getByRole('button', { name: '保存并订阅运行版本', exact: true }).click()
  await expect(page.getByRole('link', { name: /已订阅 v/ })).toBeVisible()
}

test('A11Y-14 native publish-and-Proof returns focus after native Escape', async ({ page, account }) => {
  await login(page, account)
  await createReadyRuntimeVersion(page)
  const trigger = page.getByRole('button', { name: '发布与 Proof', exact: true })
  await openByKeyboard(trigger)
  const dialog = page.getByRole('dialog', { name: '发布与 Proof', exact: true })
  await expect(dialog).toBeVisible()
  await expectFocusInside(dialog)
  await page.keyboard.press('Tab')
  await expectFocusInside(dialog)
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
})

test('A11Y-15 native indicator picker contains focus and restores its trigger', async ({ page, account }) => {
  await login(page, account)
  await route(page, '#single')
  const trigger = page.getByRole('button', { name: /金融指标/ })
  await openByKeyboard(trigger)
  const dialog = page.getByRole('dialog', { name: '技术指标', exact: true })
  await expectFocusInside(dialog)
  await dialog.getByRole('button', { name: '完成', exact: true }).focus()
  await page.keyboard.press('Tab')
  const focus = await dialog.evaluate(node => ({ inside: node.contains(document.activeElement), tag: document.activeElement?.tagName, documentFocused: document.hasFocus(), modal: node.matches(':modal') }))
  await test.info().attach('native-dialog-tab-boundary', { body: JSON.stringify(focus), contentType: 'application/json' })
  if (!focus.inside) {
    // Native dialogs may hand the boundary Tab to browser chrome, never another page control.
    expect(focus.modal).toBe(true)
    expect(focus.tag).toBe('BODY')
    await page.keyboard.press('Tab')
  }
  await expectFocusInside(dialog)
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
})

test('A11Y-16 modeless local settings has explicit non-modal boundary and Escape return', async ({ page, account }) => {
  await login(page, account)
  const trigger = page.getByRole('button', { name: '本地设置', exact: true })
  await openByKeyboard(trigger)
  const popover = page.getByRole('dialog', { name: '本地设置', exact: true })
  // Product currently exposes this as a modeless popover, not an aria-modal dialog.
  await expect(popover).not.toHaveAttribute('aria-modal', 'true')
  const close = popover.getByRole('button', { name: '关闭本地设置', exact: true })
  await expect(close).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect.poll(() => popover.evaluate(node => !node.contains(document.activeElement))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(popover).toBeHidden()
  await expect(trigger).toBeFocused()
})

test('A11Y-17 OCR review traps focus, Escape cancels, and returns to OCR trigger', async ({ page, account, context }) => {
  test.setTimeout(90_000)
  await context.route('https://cdn.jsdelivr.net/npm/@tesseract.js-data/**/eng.traineddata.gz', request =>
    request.fulfill({ path: ocrModel, contentType: 'application/gzip', headers: { 'Access-Control-Allow-Origin': '*' } }))
  await login(page, account)
  await resetLedger(page)
  await route(page, '#/journal/accounts')
  await page.getByRole('button', { name: '新增账户', exact: true }).click()
  const accountDialog = page.getByRole('dialog')
  await accountDialog.getByLabel('账户名称', { exact: true }).fill('Keyboard OCR ' + Date.now())
  await accountDialog.getByRole('button', { name: '保存账户', exact: true }).click()
  const card = page.locator('.account-card').filter({ has: page.getByRole('heading', { name: /Keyboard OCR/ }) })
  await card.getByRole('button', { name: /进入账户/ }).click()
  const trigger = page.getByRole('button', { name: '识别资产截图', exact: true })
  await openByKeyboard(trigger)
  const dialog = page.getByRole('dialog', { name: '识别资产截图', exact: true })
  await expectFocusInside(dialog)
  const data = await page.evaluate(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 900; canvas.height = 250
    const ctx = canvas.getContext('2d')!
    ctx.fillStyle = 'white'; ctx.fillRect(0, 0, 900, 250)
    ctx.fillStyle = 'black'; ctx.font = 'bold 48px Arial'
    ctx.fillText('BTC', 50, 100); ctx.fillText('$1234.00', 450, 100)
    return canvas.toDataURL('image/png').split(',')[1]
  })
  await dialog.locator('input[type=file]').setInputFiles({
    name: 'keyboard-ocr.png', mimeType: 'image/png', buffer: Buffer.from(data, 'base64'),
  })
  await expect(dialog.getByText('识别到 1 项资产', { exact: true })).toBeVisible({ timeout: 60_000 })
  await dialog.getByLabel('选择 BTC', { exact: true }).check()
  const confirm = dialog.getByRole('button', { name: '确认更新 1 项资产', exact: true })
  await confirm.focus()
  await page.keyboard.press('Tab')
  await expectFocusInside(dialog)
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
  expect((await (await page.request.get('/api/ledger')).json()).state.holdings).toEqual([])
})


test('A11Y-18 Escape closes only the foreground dialog above modeless settings', async ({ page, account }) => {
  await login(page, account)
  const settingsTrigger = page.getByRole('button', { name: '本地设置', exact: true })
  await openByKeyboard(settingsTrigger)
  const settings = page.getByRole('dialog', { name: '本地设置', exact: true })
  const statusTrigger = page.getByRole('button', { name: '系统状态', exact: true }).first()
  await openByKeyboard(statusTrigger)
  const status = page.getByRole('dialog', { name: /系统状态与能力/ })
  await expectFocusInside(status)
  await page.keyboard.press('Escape')
  await expect(status).toBeHidden()
  await expect(settings).toBeVisible()
  await expect(statusTrigger).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(settings).toBeHidden()
  await expect(settingsTrigger).toBeFocused()
})

test('A11Y-19 revealing a retained picker cannot steal focus from a foreground dialog', async ({ page, account }) => {
  await login(page, account)
  await route(page, '#portfolio')
  await openByKeyboard(page.getByRole('button', { name: '选择资产', exact: true }))
  const picker = page.getByRole('dialog', { name: '选择组合标的' })
  await route(page, '#single')
  await openByKeyboard(page.getByRole('button', { name: '系统状态', exact: true }).first())
  const status = page.getByRole('dialog', { name: /系统状态与能力/ })
  await route(page, '#portfolio')
  await expectFocusInside(status)
  await page.keyboard.press('Escape')
  await expect(status).toBeHidden()
  await expect(picker).toBeVisible()
  await expectFocusInside(picker)
  await page.keyboard.press('Tab')
  await expectFocusInside(picker)
})

// Historical r23 browser path. The code workbench has no legacy project/visual editor entry.
test.skip('A11Y-20 a retained discard confirmation cannot consume a foreground Escape', async ({ page, account }) => {
  await login(page, account)
  await route(page, '#research')
  await openByKeyboard(page.getByRole('button', { name: '新建策略项目', exact: true }))
  const editor = page.getByRole('dialog', { name: '创建策略项目', exact: true })
  await editor.getByLabel('项目名称', { exact: true }).fill('Retained confirmation draft')
  await page.keyboard.press('Escape')
  const confirm = page.getByRole('alertdialog')
  await expectFocusInside(confirm)
  await route(page, '#single')
  await openByKeyboard(page.getByRole('button', { name: '系统状态', exact: true }).first())
  const status = page.getByRole('dialog', { name: /系统状态与能力/ })
  await route(page, '#research')
  await expectFocusInside(status)
  await page.keyboard.press('Escape')
  await expect(status).toBeHidden()
  await expect(confirm).toBeVisible()
  await expectFocusInside(confirm)
  await page.keyboard.press('Tab')
  await expectFocusInside(confirm)
  await page.keyboard.press('Escape')
  await expect(confirm).toBeHidden()
  await expect(editor.getByLabel('项目名称', { exact: true })).toHaveValue('Retained confirmation draft')
})
