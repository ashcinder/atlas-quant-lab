import {test,expect,login,savedRun,fixture} from './helpers'
test('FAULT-01 HTTP 500 backtest save reports failure and retry recovers',async({page,account})=>{
 await login(page,account);await page.route('**/api/v1/compute/runs',r=>r.fulfill({status:500,contentType:'application/json',body:'{"error":"Synthetic save outage"}'}))
 await page.getByRole('button',{name:'运行回测',exact:true}).click();await expect(page.locator('.error-banner')).toContainText('Synthetic save outage')
 await page.unroute('**/api/v1/compute/runs');await savedRun(page,()=>page.getByRole('button',{name:'运行回测',exact:true}).click())
})
test('FAULT-02 corrupt market chunk hash refuses computation then retry recovers',async({page,account})=>{
 await page.route('**/api/v1/market/files/*.json',r=>r.fulfill({status:200,contentType:'application/json',body:'{"bars":[]}'}));await login(page,account)
 await page.getByRole('button',{name:'运行回测',exact:true}).click();await expect(page.locator('.error-banner')).toContainText('哈希校验失败')
 await page.unroute('**/api/v1/market/files/*.json');await page.reload();await savedRun(page,()=>page.getByRole('button',{name:'运行回测',exact:true}).click())
})
test('FAULT-03 missing manifest shows preparation without provider fallback',async({page,account})=>{
 await page.route('**/api/v1/market/manifest?**',r=>r.fulfill({status:202,contentType:'application/json',body:'{"status":"preparing","message":"Synthetic dataset preparation"}'}));await login(page,account)
 await expect(page.locator('.error-banner')).toContainText('Synthetic dataset preparation');await page.getByRole('button',{name:'运行回测',exact:true}).click();await expect(page.locator('.error-banner')).toContainText('Synthetic dataset preparation')
})
test('FAULT-04 offline shell reconnect returns to usable login',async({page})=>{
 await page.route('**/api/session',r=>r.abort('failed'));await page.goto('/');await expect(page.getByRole('button',{name:'重新连接'})).toBeVisible();await page.unroute('**/api/session');await page.getByRole('button',{name:'重新连接'}).click();await expect(page.getByLabel('登录邮箱')).toBeVisible()
})
test('FAULT-05 IndexedDB failure is explicit and does not call legacy compute',async({page,account})=>{
 const legacy:string[]=[];page.on('request',r=>{if(/\/api\/v1\/(backtests|portfolio\/backtests)$/.test(new URL(r.url()).pathname))legacy.push(r.url())})
 await page.addInitScript(()=>{Object.defineProperty(window,'indexedDB',{get(){return undefined}})})
 await login(page,account);await page.getByRole('button',{name:'运行回测',exact:true}).click();await expect(page.locator('.error-banner')).toContainText(/IndexedDB|浏览器/);expect(legacy).toEqual([])
})
test('FAULT-06 delayed previous asset cannot replace current market',async({page,account})=>{
 await login(page,account);await page.route('**/api/v1/market/manifest?**',async r=>{const u=new URL(r.request().url());if(u.searchParams.get('symbol')==='ETH-USD')await new Promise(resolve=>setTimeout(resolve,400));await r.continue()})
 const list=page.getByRole('complementary',{name:'标的列表'});await list.getByRole('button',{name:/ETH-USD/}).click();await list.getByRole('button',{name:/SOL-USD/}).click();await expect(page.locator('.symbol-block strong')).toHaveText('SOL-USD');await page.waitForLoadState('networkidle');await expect(page.locator('.symbol-block strong')).toHaveText('SOL-USD')
})
test('FAULT-07 unentitled private request cannot be retried as ordinary server compute',async({page})=>{
 await login(page,'outsider');const f=fixture();const r=await page.request.post('/api/v1/compute/private-backtests',{data:{release_id:f.releases.private,dataset_id:f.datasets['BTC-USD:1d'].dataset_id,settings:{initial_capital:100000}}});expect(r.status()).toBe(403)
})

test('FAULT-08 save rate limit is explicit and retry preserves one result',async({page,account})=>{
 await login(page,account);await page.route('**/api/v1/compute/runs',r=>r.fulfill({status:429,contentType:'application/json',body:'{"detail":"Synthetic rate limit; retry later"}'}));await page.getByRole('button',{name:'运行回测',exact:true}).click();await expect(page.locator('.error-banner')).toContainText('Synthetic rate limit');await page.unroute('**/api/v1/compute/runs');await savedRun(page,()=>page.getByRole('button',{name:'运行回测',exact:true}).click())
})
test('FAULT-09 malformed manifest JSON reports error and fresh reload recovers',async({page,account})=>{
 await page.route('**/api/v1/market/manifest?**',r=>r.fulfill({status:200,contentType:'application/json',body:'{'}));await login(page,account);await expect(page.locator('.error-banner')).toContainText(/解析|JSON|数据/);await page.unroute('**/api/v1/market/manifest?**');await page.reload();await savedRun(page,()=>page.getByRole('button',{name:'运行回测',exact:true}).click())
})
test('FAULT-10 revoked session during compute returns login without saving',async({page,account})=>{
 await login(page,account);await page.route('**/api/v1/compute/identity',r=>r.fulfill({status:401,contentType:'application/json',body:'{"detail":"Synthetic expired session"}'}));await page.getByRole('button',{name:'运行回测',exact:true}).click();await expect(page.getByLabel('登录邮箱')).toBeVisible()
})
test('FAULT-11 unavailable Worker cannot silently fall back to server',async({page,account})=>{
 await page.addInitScript(()=>{Object.defineProperty(window,'Worker',{value:undefined})});await login(page,account);await page.getByRole('button',{name:'运行回测',exact:true}).click();await expect(page.locator('.error-banner')).toContainText('Web Worker')
})
test('FAULT-12 storage quota exhaustion refuses unpersisted compute success',async({page,account})=>{
 await page.addInitScript(()=>{IDBObjectStore.prototype.put=function(){throw new DOMException('Synthetic quota exhausted','QuotaExceededError')}});await login(page,account);await page.getByRole('button',{name:'运行回测',exact:true}).click();await expect(page.locator('.error-banner')).toContainText(/quota|Quota|存储|配额/)
})

test('FAULT-13 a running Worker crashes without saving and the next real run succeeds', async ({ page, account, pageErrors }) => {
  await login(page, account)
  const saveRequests: string[] = []
  page.on('request', request => {
    const path = new URL(request.url()).pathname
    if (request.method() === 'POST' && ['/api/v1/compute/runs', '/api/v1/backtests'].includes(path)) {
      saveRequests.push(path)
    }
  })
  const workerAsset = /\/assets\/worker-[\w-]+\.js$/
  let injected = 0
  await page.route(workerAsset, async intercepted => {
    const response = await intercepted.fetch()
    const script = await response.text()
    const fault = `self.addEventListener('message', (event) => {
      if (event.data?.type === 'start') {
        event.stopImmediatePropagation()
        throw new Error('Synthetic Worker execution fault')
      }
    });\n`
    injected += 1
    await intercepted.fulfill({
      response,
      headers: { ...response.headers(), 'cache-control': 'no-store' },
      body: fault + script,
    })
  })
  await page.getByRole('button', { name: '运行回测', exact: true }).click()
  await expect(page.locator('.error-banner')).toContainText('浏览器计算 Worker 启动或运行失败')
  expect(injected).toBe(1)
  expect(saveRequests).toEqual([])
  await page.unroute(workerAsset)
  await savedRun(page, () => page.getByRole('button', { name: '运行回测', exact: true }).click())
  expect(saveRequests).toEqual(['/api/v1/compute/runs'])
  const injectedError = pageErrors.findIndex(message => message.includes('Synthetic Worker execution fault'))
  if (injectedError !== -1) pageErrors.splice(injectedError, 1)
})
