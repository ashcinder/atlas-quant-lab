import { test, expect, login, route } from './helpers'

const python = 'def init(context):\n    context.ready = False\n\ndef handle_bar(context, bar_dict):\n    pass\n'

test('LAB-01 creates a private native strategy directly and restores it after reload', async ({ page, account }) => {
  await login(page, account)
  await route(page, '#research')
  await page.getByRole('button', { name: '新建策略', exact: true }).click()
  const editor = page.getByLabel('Python 策略代码')
  await expect(editor).toHaveValue(/def init\(context\):/)
  await expect(page.getByRole('heading', { name: '编辑策略', exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: '新建策略类型', exact: true })).toHaveCount(0)
  await expect(page.getByLabel('回测引擎', { exact: true })).toHaveCount(0)
  await expect(page.getByLabel('策略编程语言', { exact: true })).toHaveCount(0)
  await editor.fill(python)
  const name = 'E2E Native Private Strategy ' + Date.now()
  await page.getByLabel('代码策略名称').fill(name)
  await page.getByLabel('共享初始资金（元）', { exact: true }).fill('12345')
  const created = page.waitForResponse(response => response.url().endsWith('/api/v1/lab-strategies') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '保存策略', exact: true }).click()
  const response = await created
  expect(response.status()).toBe(201)
  const saved = await response.json()
  expect(saved.kind).toBe('multi_python')
  expect(saved.settings.engine_id).toBe('rqalpha')
  await expect(page.getByText('已保存', { exact: true })).toBeVisible()
  await page.reload()
  await page.getByRole('button', { name: '打开 ' + name, exact: true }).click()
  await expect(editor).toHaveValue(python)
  await expect(page.getByLabel('共享初始资金（元）', { exact: true })).toHaveValue('12345')
})

test('LAB-02 imports native Python without classification and checks its actual protocol', async ({ page, account }) => {
  await login(page, account)
  await route(page, '#research')
  const legacyRuns: string[] = []
  page.on('request', request => {
    if (request.method() === 'POST' && /\/api\/v1\/(backtests|strategy-releases)$/.test(new URL(request.url()).pathname)) legacyRuns.push(request.url())
  })
  await page.locator('.lab-library input[type="file"]').setInputFiles({
    name: 'E2E Native Import.py', mimeType: 'text/x-python', buffer: Buffer.from(python),
  })
  const editor = page.getByLabel('Python 策略代码')
  await expect(editor).toHaveValue(python)
  await expect(page.getByRole('region', { name: '导入策略类型', exact: true })).toHaveCount(0)
  const created = page.waitForResponse(response => response.url().endsWith('/api/v1/lab-strategies') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '保存策略', exact: true }).click()
  expect((await created).status()).toBe(201)
  const checked = page.waitForResponse(response => response.url().endsWith('/api/v1/lab-multi/check') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '检查代码', exact: true }).click()
  expect((await checked).request().postDataJSON().engine_id).toBe('rqalpha')
  await expect(page.getByText('语法与入口静态检查通过', { exact: true })).toBeVisible()
  await expect(page.getByText('仅静态检查，未运行策略。', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '运行回测', exact: true })).toBeDisabled()
  expect(legacyRuns).toEqual([])
})

test('LAB-03 offers save, discard and cancel when leaving a dirty native draft', async ({ page, account }) => {
  await login(page, account)
  await route(page, '#research')
  await page.getByRole('button', { name: '新建策略', exact: true }).click()
  await page.getByLabel('Python 策略代码').fill(python)
  await page.getByRole('button', { name: '行情与回测', exact: true }).click()
  const dialog = page.getByRole('alertdialog')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: '取消，保留当前内容', exact: true }).click()
  await expect(page.getByLabel('Python 策略代码')).toHaveValue(python)
  await page.getByRole('button', { name: '行情与回测', exact: true }).click()
  await dialog.getByRole('button', { name: '放弃修改', exact: true }).click()
  await expect(page).toHaveURL(/#single$/)
})

test('MARKET-03 unsupported favourites control states its unavailable capability', async ({ page, account }) => {
  await login(page, account)
  const favourites = page.getByRole('button', { name: '收藏标的（尚未接入）', exact: true })
  await expect(favourites).toBeDisabled()
  await expect(favourites).toHaveAttribute('title', '收藏功能尚未接入')
})
