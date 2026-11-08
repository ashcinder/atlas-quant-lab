import {test,expect,login,route,savedRun,fixture,password,trackApiRequests} from './helpers'

test('AUTH-01 registration stays disabled and anonymous APIs reject access',async({page})=>{
 await page.goto('/');await expect(page.getByRole('button',{name:'创建账号',exact:true})).toHaveCount(0)
 expect((await page.request.get('/api/v1/runs')).status()).toBe(401)
 expect((await page.request.post('/api/register',{data:{email:'disabled@e2e.example.test',password}})).status()).toBe(403)
})
test('AUTH-02 wrong password reports error then correct login recovers',async({page,account})=>{
 await page.goto('/');await page.getByLabel('登录邮箱').fill(account+'@e2e.example.test');await page.getByLabel('密码',{exact:true}).fill('incorrect-password')
 await page.getByRole('button',{name:'登录 Atlas',exact:true}).click();await expect(page.getByRole('alert')).toBeVisible();await expect(page.getByLabel('登录邮箱')).toBeVisible()
 await page.getByLabel('密码',{exact:true}).fill(password);await page.getByRole('button',{name:'登录 Atlas',exact:true}).click();await expect(page.getByLabel('登录邮箱')).toBeHidden()
})
test('AUTH-03 logout and browser session revocation remove access',async({page,account})=>{
 await login(page,account);await page.request.post('/api/logout');await page.reload();await expect(page.getByLabel('登录邮箱')).toBeVisible();expect((await page.request.get('/api/ledger')).status()).toBe(401)
})
test('NAV-01 direct routes refresh and back preserve the intended workspace',async({page,account})=>{
 const settled=trackApiRequests(page)
 await login(page,account)
 const routes=[
  ['#single',page.getByRole('button',{name:'运行回测',exact:true})],
  ['#portfolio',page.getByRole('heading',{name:'多资产组合构建'})],
  ['#research',page.getByRole('button',{name:'图形化',exact:true})],
  ['#quantjudge',page.getByRole('navigation',{name:'QuantJudge 页面'})],
  ['#/journal/overview',page.locator('.journal-root:not([hidden])')],
  ['#/trading',page.getByRole('button',{name:'新建运行',exact:true}).first()],
 ] as const
 for(const [hash,surface] of routes){
  const open=async(navigate:()=>Promise<unknown>)=>{
   const ready=hash==='#/trading'?page.waitForResponse(response=>response.url().endsWith('/api/v1/trading/accounts')&&response.ok()):undefined
   await navigate();await expect(surface).toBeVisible()
   if(ready)await (await ready).finished()
   await settled()
  }
  await open(()=>route(page,hash))
  await open(()=>page.reload())
 }
 await page.goBack()
 await expect(page).toHaveURL(/#\/journal\/overview$/)
 await expect(page.locator('.journal-root:not([hidden])')).toBeVisible()
})
test('MARKET-01 search actual catalog and select a different symbol',async({page,account})=>{
 await login(page,account);const sidebar=page.getByRole('complementary',{name:'标的列表'})
 await sidebar.getByPlaceholder('代码、名称或类别').fill('ETH');await sidebar.getByRole('button',{name:/ETH-USD/}).click();await expect(page.locator('.symbol-block strong')).toHaveText('ETH-USD')
 await sidebar.getByPlaceholder('代码、名称或类别').fill('不可能存在的测试资产名称');await expect(sidebar.getByText('没有匹配标的')).toBeVisible()
})
test('MARKET-02 five intervals source choices and chart indicators are operable',async({page,account})=>{
 await login(page,account)
 for(const name of ['15分','1时','4时','周','日']){await page.getByRole('button',{name,exact:true}).click();await expect(page.getByRole('button',{name,exact:true})).toHaveAttribute('aria-pressed','true')}
 for(const value of ['demo','binance','yahoo','auto']){await page.getByLabel('行情数据源').selectOption(value);await expect(page.getByLabel('行情数据源')).toHaveValue(value)}
 await page.getByRole('button',{name:'折线图',exact:true}).click();await expect(page.getByRole('button',{name:'折线图',exact:true})).toHaveAttribute('aria-pressed','true')
 await page.getByRole('button',{name:'K线图',exact:true}).click();await page.getByRole('button',{name:'隐藏成交量',exact:true}).click();await expect(page.getByRole('button',{name:'VOL',exact:true})).toHaveAttribute('aria-pressed','false')
})
test('BT-01 real worker saves unverified result and history survives refresh',async({page,account})=>{
 await login(page,account);const result=await savedRun(page,()=>page.getByRole('button',{name:'运行回测',exact:true}).click())
 expect(result.metrics.total_return).toEqual(expect.any(Number));expect(result.equity.length).toBeGreaterThan(100)
 const stored=await page.request.get('/api/v1/runs/'+result.run_id);expect(stored.ok()).toBeTruthy();expect((await stored.json()).run_id).toBe(result.run_id)
 await page.reload();await page.getByRole('button',{name:'回测历史',exact:true}).click();const history=page.getByRole('dialog',{name:'回测历史'});await expect(history.getByRole('button',{name:'打开 BTC-USD 回测记录'}).first()).toBeVisible()
 await history.getByRole('button',{name:'打开 BTC-USD 回测记录'}).first().click();await expect(page.getByRole('region',{name:'回测结果'})).toContainText('总收益')
})
test('BT-02 result tabs graph controls and missing live evidence stay accurate',async({page,account})=>{
 await login(page,account);await savedRun(page,()=>page.getByRole('button',{name:'运行回测',exact:true}).click());const panel=page.getByRole('region',{name:'回测结果'})
 await expect(panel).toContainText('未经 ZKP 验证');await expect(panel).toContainText('不可评估')
 for(const name of [/交易记录/,/风险分析/,/可信度/,/^概览$/]){await panel.getByRole('tab',{name}).click();await expect(panel.getByRole('tabpanel')).toBeVisible()}
 await page.getByRole('button',{name:'最大化回测面板'}).click();await expect(page.getByRole('button',{name:'还原回测面板'})).toBeVisible()
})
test('BT-03 all visible builtin strategies complete through UI',async({page,account})=>{
 test.setTimeout(120000);await login(page,account)
 const select=page.locator('.strategy-select-wrap .select-shell select');const ids=await select.locator('option').evaluateAll(options=>options.map(o=>(o as HTMLOptionElement).value))
 expect(ids.length).toBeGreaterThanOrEqual(14)
 for(const id of ids){await select.selectOption(id);const result=await savedRun(page,()=>page.getByRole('button',{name:'运行回测',exact:true}).click());expect(result.strategy.id).toBe(id)}
})
test('PORT-01 default CNY portfolio and all three allocation strategies save correctly',async({page,account})=>{
 test.setTimeout(90000);await login(page,account);await route(page,'#portfolio')
 for(const name of ['全天候组合','风险平价','60/40再平衡']){
  await page.getByRole('combobox',{name:'组合策略',exact:true}).selectOption({label:name});const r=await savedRun(page,()=>page.getByRole('button',{name:'运行回测',exact:true}).click());expect(r.assets.length).toBeGreaterThan(1);expect(r.valuation_currency).toBe('CNY')
 }
})
test('SEC-01 other account cannot retrieve a saved result or private object',async({page,browser,account})=>{
 await login(page,account);const r=await savedRun(page,()=>page.getByRole('button',{name:'运行回测',exact:true}).click())
 const context=await browser.newContext({baseURL:test.info().project.use.baseURL as string});const other=await context.newPage();await login(other,'outsider');expect((await other.request.get('/api/v1/runs/'+r.run_id)).status()).toBe(404);await context.close()
})
test('SEC-02 subscription capabilities hide code and reject revoked users',async({page})=>{
 await login(page,'subscriber');const f=fixture()
 const r=await page.request.get('/api/v1/compute/capabilities?release_id='+f.releases.python);expect(r.ok()).toBeTruthy();const cap=await r.json();expect(cap.execution_location).toBe('server_private');expect(JSON.stringify(cap)).not.toContain('target_bps')
 const privateResult=await page.request.post('/api/v1/compute/private-backtests',{data:{release_id:f.releases.python,dataset_id:f.datasets['BTC-USD:1d'].dataset_id,settings:{initial_capital:100000}}});expect(privateResult.ok()).toBeTruthy();expect((await privateResult.json()).compute.execution_location).toBe('server_private')
 await page.request.post('/api/logout');await login(page,'expired');expect((await page.request.get('/api/v1/compute/capabilities?release_id='+f.releases.python)).status()).toBe(403)
})
test('SEC-03 cross-site write wrong JSON and disabled legacy routes fail closed',async({page,account})=>{
 await login(page,account)
 expect((await page.request.post('/api/v1/backtests',{data:{}})).status()).toBe(410)
 expect((await page.request.post('/api/v1/compute/runs',{headers:{Origin:'https://evil.example.test'},data:{}})).status()).toBe(403)
 expect((await page.request.put('/api/ledger',{headers:{'Content-Type':'text/plain'},data:'unsafe'})).status()).toBe(415)
})
