import {test,expect,login,route,resetLedger} from './helpers'
import {createHash} from 'node:crypto'
import {readFile} from 'node:fs/promises'
import {fileURLToPath} from 'node:url'
const model=process.env.ATLAS_E2E_OCR_MODEL??fileURLToPath(new URL('../../.artifacts/comprehensive-20261108/samples/eng.traineddata.gz',import.meta.url))
async function openOcr(page:import('@playwright/test').Page){
 await resetLedger(page);await route(page,'#/journal/accounts');await page.getByRole('button',{name:'新增账户',exact:true}).click();await page.getByLabel('账户名称',{exact:true}).fill('E2E OCR');await page.getByRole('button',{name:'保存账户',exact:true}).click();await expect(page.getByRole('dialog')).toBeHidden();await page.locator('.account-card').filter({has:page.getByRole('heading',{name:'E2E OCR',exact:true})}).getByRole('button',{name:/进入账户/}).click();await page.getByRole('button',{name:'识别资产截图',exact:true}).click();return page.getByRole('dialog')
}
for(const [format,mime]of [['png','image/png'],['jpeg','image/jpeg'],['webp','image/webp']]as const){
 test(`OCR-${format} real local Worker WASM recognizes synthetic image and requires explicit ledger confirmation`,async({page,account,context})=>{
  test.setTimeout(90000)
  expect(createHash('sha256').update(await readFile(model)).digest('hex')).toBe('45b4cb346724ac1774f1c36f42f182b887bcdb28ebe63e6fff90ac41f3fcff91')
  await context.route('https://cdn.jsdelivr.net/npm/@tesseract.js-data/**/eng.traineddata.gz',r=>r.fulfill({path:model,contentType:'application/gzip',headers:{'Access-Control-Allow-Origin':'*'}}))
  await login(page,account);const d=await openOcr(page)
  const data=await page.evaluate(mime=>{const c=document.createElement('canvas');c.width=1000;c.height=350;const x=c.getContext('2d')!;x.fillStyle='white';x.fillRect(0,0,1000,350);x.fillStyle='black';x.font='bold 48px Arial';x.fillText('BTC',60,90);x.fillText('$1200.00',500,90);x.fillText('ETH',60,220);x.fillText('$600.00',500,220);return c.toDataURL(mime)},mime)
  await d.locator('input[type=file]').setInputFiles({name:'synthetic.'+format,mimeType:mime,buffer:Buffer.from(data.split(',')[1],'base64')})
  await expect(d.getByText('识别到 2 项资产',{exact:true})).toBeVisible({timeout:60000});expect((await (await page.request.get('/api/ledger')).json()).state.holdings).toHaveLength(0)
  await d.getByLabel('选择 BTC',{exact:true}).check();await d.getByLabel('选择 ETH',{exact:true}).check();for(let i=0;i<2;i++){await d.getByRole('combobox',{name:'采用的计算依据'}).nth(i).selectOption('principal');await d.getByLabel('总投入金额',{exact:true}).nth(i).fill(i?'500':'1000')}await d.getByRole('button',{name:'确认更新 2 项资产'}).click();await expect(d).toBeHidden();const state=(await (await page.request.get('/api/ledger')).json()).state;expect(state.holdings.map((x:{symbol:string})=>x.symbol).sort()).toEqual(['BTC','ETH'])
 })
}
test('OCR-invalid damaged and oversized files leave ledger unchanged and permit retry',async({page,account})=>{
 await login(page,account);const d=await openOcr(page);const input=d.locator('input[type=file]')
 await input.setInputFiles({name:'broken.png',mimeType:'image/png',buffer:Buffer.from('not-an-image')});await expect(d.locator('.form-error')).toContainText(/图片|读取|解码|格式|decode/)
 await input.setInputFiles({name:'too-large.png',mimeType:'image/png',buffer:Buffer.alloc(15*1024*1024+1)});await expect(d.locator('.form-error')).toContainText('不能超过 15 MB');expect((await (await page.request.get('/api/ledger')).json()).state.holdings).toHaveLength(0)
})

test('IMG-01 account SVG rasterizes safely after malformed and over-limit uploads', async ({ page, account }) => {
  await login(page, account)
  await route(page, '#/journal/accounts')
  const name = 'Synthetic SVG ' + Date.now()
  await page.getByRole('button', { name: '新增账户', exact: true }).click()
  const form = page.getByRole('dialog')
  await form.getByLabel('账户名称', { exact: true }).fill(name)
  const input = form.getByLabel('选择账户图片', { exact: true })
  await input.setInputFiles({ name: 'malformed.svg', mimeType: 'image/svg+xml', buffer: Buffer.from('<svg>') })
  await expect(form.getByText(/SVG 文件无法读取/)).toBeVisible()
  await input.setInputFiles({ name: 'too-large.svg', mimeType: 'image/svg+xml', buffer: Buffer.alloc(5 * 1024 * 1024 + 1) })
  await expect(form.getByText(/图片大小需在 5 MB 以内/)).toBeVisible()
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"><rect width="200" height="100" fill="#136ad1"/><script>globalThis.__svgExecuted=true</script></svg>'
  await input.setInputFiles({ name: 'badge.svg', mimeType: 'image/svg+xml', buffer: Buffer.from(svg) })
  await expect(form.getByRole('button', { name: '更换图片', exact: true })).toBeVisible()
  await form.getByRole('button', { name: '保存账户', exact: true }).click()
  await expect(form).toBeHidden()
  await page.reload()
  const card = page.locator('.account-card').filter({ has: page.getByRole('heading', { name, exact: true }) })
  await expect(card.locator('img')).toBeVisible()
  const accounts = (await (await page.request.get('/api/ledger')).json()).state.accounts
  const created = accounts.find((item: { name: string }) => item.name === name)
  expect(created.image).toMatch(/^data:image\/(webp|png|jpeg);base64,/)
  expect(await page.evaluate(() => '__svgExecuted' in globalThis)).toBe(false)
})

test('OCR-review closing review cancels writes and manual correction preserves exact confirmed amounts', async ({ page, account, context }) => {
  test.setTimeout(90_000)
  await context.route('https://cdn.jsdelivr.net/npm/@tesseract.js-data/**/eng.traineddata.gz', request =>
    request.fulfill({ path: model, contentType: 'application/gzip', headers: { 'Access-Control-Allow-Origin': '*' } }))
  await login(page, account)
  const dialog = await openOcr(page)
  const data = await page.evaluate(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 1000
    canvas.height = 300
    const ctx = canvas.getContext('2d')!
    ctx.fillStyle = 'white'
    ctx.fillRect(0, 0, 1000, 300)
    ctx.fillStyle = 'black'
    ctx.font = 'bold 48px Arial'
    ctx.fillText('BTC', 50, 100)
    ctx.fillText('$1234.00', 450, 100)
    return canvas.toDataURL('image/png').split(',')[1]
  })
  const file = { name: 'synthetic-review.png', mimeType: 'image/png', buffer: Buffer.from(data, 'base64') }
  await dialog.locator('input[type=file]').setInputFiles(file)
  await expect(dialog.getByText('识别到 1 项资产', { exact: true })).toBeVisible({ timeout: 60_000 })
  await expect(dialog).toContainText(/OCR \d+%/)
  expect((await (await page.request.get('/api/ledger')).json()).state.holdings).toEqual([])
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  expect((await (await page.request.get('/api/ledger')).json()).state.holdings).toEqual([])
  await page.getByRole('button', { name: '识别资产截图', exact: true }).click()
  await dialog.locator('input[type=file]').setInputFiles(file)
  await expect(dialog.getByText('识别到 1 项资产', { exact: true })).toBeVisible({ timeout: 60_000 })
  await dialog.getByLabel('选择 BTC', { exact: true }).check()
  await dialog.getByLabel('资产名称', { exact: true }).fill('MANUALBTC')
  await dialog.getByLabel('当前金额', { exact: true }).fill('1234.56789012')
  await dialog.getByRole('combobox', { name: '采用的计算依据', exact: true }).selectOption('principal')
  await dialog.getByLabel('总投入金额', { exact: true }).fill('1000.12345678')
  await dialog.getByRole('button', { name: '确认更新 1 项资产', exact: true }).click()
  await expect(dialog).toBeHidden()
  const state = (await (await page.request.get('/api/ledger')).json()).state
  expect(state.holdings.map((item: { symbol: string }) => item.symbol)).toEqual(['MANUALBTC'])
  expect(state.entries.some((entry: { amount: number }) => entry.amount === 1234.56789012)).toBe(true)
  await page.reload()
  expect((await (await page.request.get('/api/ledger')).json()).state.holdings[0].symbol).toBe('MANUALBTC')
})

test('FAULT-14 OCR model download failure returns a retryable error and releases the Worker', async ({ page, account, context }) => {
  test.setTimeout(90_000)
  let attempts = 0
  let closed = 0
  page.on('worker', worker => {
    if (worker.url().includes('portfolio-ocr-worker')) worker.on('close', () => { closed++ })
  })
  const pattern = 'https://cdn.jsdelivr.net/npm/@tesseract.js-data/**/eng.traineddata.gz'
  await context.route(pattern, async request => { attempts++; await request.abort('failed') })
  await login(page, account)
  const dialog = await openOcr(page)
  const image = await page.evaluate(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 900
    canvas.height = 250
    const ctx = canvas.getContext('2d')!
    ctx.fillStyle = 'white'
    ctx.fillRect(0, 0, 900, 250)
    ctx.font = 'bold 48px Arial'
    ctx.fillStyle = 'black'
    ctx.fillText('BTC', 50, 90)
    ctx.fillText('$1200.00', 450, 90)
    return canvas.toDataURL('image/png').split(',')[1]
  })
  const file = { name: 'synthetic-retry.png', mimeType: 'image/png', buffer: Buffer.from(image, 'base64') }
  await dialog.locator('input[type=file]').setInputFiles(file)
  await expect(dialog.locator('.form-error')).toContainText('OCR 模型加载或识别失败', { timeout: 30_000 })
  expect(attempts).toBeGreaterThan(0)
  await expect.poll(() => closed).toBeGreaterThanOrEqual(1)
  expect((await (await page.request.get('/api/ledger')).json()).state.holdings).toEqual([])
  await context.unroute(pattern)
  await context.route(pattern, request => request.fulfill({ path: model, contentType: 'application/gzip', headers: { 'Access-Control-Allow-Origin': '*' } }))
  await dialog.locator('input[type=file]').setInputFiles(file)
  await expect(dialog.getByText('识别到 1 项资产', { exact: true })).toBeVisible({ timeout: 60_000 })
  await expect.poll(() => closed).toBeGreaterThanOrEqual(2)
  expect((await (await page.request.get('/api/ledger')).json()).state.holdings).toEqual([])
})

test('OCR-cancel closing while a model downloads terminates its Worker and leaves ledger untouched', async ({ page, account, context }) => {
  let started: () => void = () => undefined
  let release: () => void = () => undefined
  const downloading = new Promise<void>(resolve => { started = resolve })
  const finish = new Promise<void>(resolve => { release = resolve })
  let workerClosed = false
  page.on('worker', worker => {
    if (worker.url().includes('portfolio-ocr-worker')) worker.on('close', () => { workerClosed = true })
  })
  await context.route('https://cdn.jsdelivr.net/npm/@tesseract.js-data/**/eng.traineddata.gz', async request => {
    started()
    await finish
    await request.abort('failed').catch(() => undefined)
  })
  await login(page, account)
  const dialog = await openOcr(page)
  const image = await page.evaluate(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 400
    canvas.height = 180
    return canvas.toDataURL('image/png').split(',')[1]
  })
  try {
    await dialog.locator('input[type=file]').setInputFiles({ name: 'synthetic-cancel.png', mimeType: 'image/png', buffer: Buffer.from(image, 'base64') })
    await downloading
    await dialog.getByRole('button', { name: '关闭', exact: true }).click()
    await expect(dialog).toBeHidden()
    await expect.poll(() => workerClosed).toBe(true)
    expect((await (await page.request.get('/api/ledger')).json()).state.holdings).toEqual([])
  } finally {
    release()
  }
})

test('OCR-type SVG and disguised non-image input fail explicitly without any ledger change', async ({ page, account }) => {
  await login(page, account)
  const dialog = await openOcr(page)
  const input = dialog.locator('input[type=file]')
  await input.setInputFiles({ name: 'unsupported.svg', mimeType: 'image/svg+xml', buffer: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"/>') })
  await expect(dialog.locator('.form-error')).toContainText('请选择 PNG、JPG 或 WebP')
  await input.setInputFiles({ name: 'disguised.png', mimeType: 'image/png', buffer: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"/>') })
  await expect(dialog.locator('.form-error')).toContainText(/图片|解码|decode|source/)
  expect((await (await page.request.get('/api/ledger')).json()).state.holdings).toEqual([])
})

test('OCR-low-confidence degraded synthetic image remains reviewable and requires explicit confirmation', async ({ page, account, context }, info) => {
  test.setTimeout(90_000)
  await context.route('https://cdn.jsdelivr.net/npm/@tesseract.js-data/**/eng.traineddata.gz', request =>
    request.fulfill({ path: model, contentType: 'application/gzip', headers: { 'Access-Control-Allow-Origin': '*' } }))
  await login(page, account)
  const dialog = await openOcr(page)
  const image = await readFile(fileURLToPath(new URL('./fixtures/low-confidence.png', import.meta.url)))
  await dialog.locator('input[type=file]').setInputFiles({ name: 'synthetic-low-confidence.png', mimeType: 'image/png', buffer: image })
  await expect(dialog.locator('.ocr-result-row').first()).toBeVisible({ timeout: 60_000 })
  const confidenceText = await dialog.locator('.ocr-result-head small').first().innerText()
  const confidence = Number(/OCR (\d+)%/.exec(confidenceText)![1])
  expect(confidence).toBeLessThan(90)
  expect((await (await page.request.get('/api/ledger')).json()).state.holdings).toEqual([])
  const row = dialog.locator('.ocr-result-row').first()
  await row.getByRole('checkbox').check()
  await row.getByLabel('资产名称', { exact: true }).fill('BTC')
  await row.getByLabel('当前金额', { exact: true }).fill('1234')
  await row.getByRole('combobox', { name: '采用的计算依据', exact: true }).selectOption('principal')
  await row.getByLabel('总投入金额', { exact: true }).fill('1000')
  await info.attach('ocr-confidence.json', { body: JSON.stringify({ confidence, synthetic: true, corrected: true }), contentType: 'application/json' })
  await dialog.getByRole('button', { name: '确认更新 1 项资产', exact: true }).click()
  await expect(dialog).toBeHidden()
  expect((await (await page.request.get('/api/ledger')).json()).state.holdings[0].symbol).toBe('BTC')
})
