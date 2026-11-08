import {createHash} from 'node:crypto'
import {readFile} from 'node:fs/promises'
import {test,expect,login,route,fixture} from './helpers'

test('JOURNEY-author save exact rule snapshot publish and start pause resume stop',async({page,account})=>{
 const unwantedComputes:string[]=[];page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/v1/compute/runs'))unwantedComputes.push(r.url())})
 await login(page,account);await route(page,'#research');await page.getByRole('button',{name:'模板',exact:true}).click()
 const name='E2E Journey '+Date.now();await page.getByLabel('策略名称',{exact:true}).fill(name)
 const created=page.waitForResponse(r=>r.url().endsWith('/api/v1/strategy-releases')&&r.request().method()==='POST')
 await page.getByRole('button',{name:'保存并订阅运行版本',exact:true}).click();const release=await (await created).json();expect(release.name).toBe(name)
 await expect(page.getByRole('link',{name:/已订阅 v/})).toBeVisible();await page.getByRole('button',{name:/发布与 Proof/}).click()
 await page.getByRole('button',{name:'直接公开策略',exact:true}).click();await expect(page.getByRole('alert')).toContainText('已公开 · 无 ZKP 验证');await page.getByRole('button',{name:'关闭发布窗口'}).click()
 await page.getByRole('link',{name:/已订阅 v/}).click();await expect(page.getByRole('dialog',{name:'新建策略运行'})).toBeVisible()
 const pending=page.waitForResponse(r=>r.url().endsWith('/api/v1/trading/runs')&&r.request().method()==='POST')
 await page.getByRole('button',{name:'启动模拟',exact:true}).click();const response=await pending;expect(response.ok()).toBeTruthy();const run=await response.json();expect(run.release_id).toBe(release.id)
 const detail=()=>page.request.get('/api/v1/trading/runs/'+run.id).then(r=>r.json())
 for(const [action,status] of [['pause','paused'],['resume','active'],['stop','stopped']] as const){await expect.poll(async()=>{const r=await page.request.post('/api/v1/trading/runs/'+run.id+'/'+action);if(r.status()===409)return 'busy';expect(r.ok(),await r.text()).toBeTruthy();return (await detail()).status}).toBe(status)}
 await page.reload();expect((await detail()).status).toBe('stopped');expect(unwantedComputes).toEqual([])
})

test('TRADE-01 simulated account order exact confirmation replay query cancel',async({page,account})=>{
 await login(page,account);await route(page,'#/trading');await page.getByRole('button',{name:'接入模拟账户',exact:true}).click()
 const dialog=page.getByRole('dialog');await dialog.getByLabel('模拟 API Key',{exact:true}).fill('synthetic-key-'+account);await dialog.getByLabel('模拟 API Secret',{exact:true}).fill('synthetic-secret-for-isolated-tests')
 await dialog.getByRole('checkbox').check();await dialog.getByRole('button',{name:'验证连接并保存',exact:true}).click();await expect(dialog).toContainText('模拟账户已验证并保存')
 await page.getByRole('button',{name:'关闭操作面板'}).click();await page.getByRole('button',{name:'人工下单',exact:true}).click()
 await page.getByLabel('交易对',{exact:true}).fill('BTC-USDT');await page.getByLabel('数量（基础币）').fill('0.001');await page.getByLabel('限价（USDT）').fill('10000')
 const previewed=page.waitForResponse(r=>r.url().endsWith('/orders/preview'));await page.getByRole('button',{name:'预览订单',exact:true}).click();const order=await (await previewed).json()
 await expect(page.getByRole('heading',{name:'核对模拟订单'})).toBeVisible();await expect(page.getByRole('button',{name:'确认提交订单'})).toBeDisabled()
 await page.getByLabel('确认文字',{exact:true}).fill('确认模拟下单');const submitted=page.waitForResponse(r=>r.url().endsWith('/orders/'+order.id+'/confirm'));await page.getByRole('button',{name:'确认提交订单'}).click();expect((await submitted).ok()).toBeTruthy()
 const replay=await page.request.post('/api/v1/trading/orders/'+order.id+'/confirm',{data:{confirmation:'确认模拟下单'}});expect(replay.ok()).toBeTruthy()
 const refreshed=await page.request.post('/api/v1/trading/orders/'+order.id+'/refresh');expect(refreshed.ok()).toBeTruthy();expect((await refreshed.json()).result.exchange_status).toBe('NEW')
 const cancelled=await page.request.post('/api/v1/trading/orders/'+order.id+'/cancel',{data:{confirmation:'确认撤单'}});expect(cancelled.ok()).toBeTruthy();expect((await cancelled.json()).result.exchange_status).toBe('CANCELED')
 const list=await (await page.request.get('/api/v1/trading/orders')).json();expect(list.filter((x:{id:string})=>x.id===order.id)).toHaveLength(1)
})

test('PROOF-01 pinned real receipt verification and download retain genuine evidence',async({page,account})=>{
 await login(page,account);const id=fixture().proof_id;expect(id,'Real historical proof must be imported').toBeTruthy()
 await route(page,'#/proof/'+id)
 const verification=page.waitForResponse(response=>response.url().endsWith('/verify')&&response.request().method()==='POST')
 await page.getByRole('button',{name:'验证 Proof',exact:true}).click()
 const response=await verification;expect(response.ok()).toBeTruthy();expect((await response.json()).valid).toBe(true)
 await expect(page.getByRole('heading',{name:'本次密码学验证通过'})).toBeVisible()
 const downloading=page.waitForEvent('download');await page.getByRole('link',{name:'下载原始 receipt',exact:true}).click()
 const download=await downloading
 expect(createHash('sha256').update(await readFile(await download.path())).digest('hex')).toBe('6c85feec41f6ad8bd64f3520984a9886ff877df1eac5f41298993157d58bd2d3')
})

test('ALERT-01 create pause resume delete alert remains owner scoped',async({page,account})=>{
 await login(page,account);await page.getByRole('button',{name:'提醒中心',exact:true}).click();const drawer=page.getByRole('dialog',{name:'提醒中心'});await drawer.getByRole('button',{name:'新建提醒'}).click()
 const name='E2E Alert '+Date.now();await drawer.getByLabel('提醒名称').fill(name);await drawer.getByLabel('阈值').fill('100');await drawer.getByRole('button',{name:'保存提醒'}).click()
 await expect(drawer.getByText(name,{exact:true})).toBeVisible();await drawer.getByRole('button',{name:'停用提醒'}).last().click();await expect(drawer.getByRole('button',{name:'启用提醒'}).last()).toBeVisible();await drawer.getByRole('button',{name:'启用提醒'}).last().click()
 page.once('dialog',d=>d.accept());await drawer.getByRole('button',{name:'删除提醒 '+name}).click();await expect(drawer.getByText(name,{exact:true})).toBeHidden()
})

test('AI-01 synthetic provider session settings test clear never browser-persist key',async({page,account})=>{
 await login(page,account);await page.getByRole('button',{name:'本地设置',exact:true}).click();await page.getByText('AI 服务配置',{exact:true}).click();const section=page.locator('.ai-settings');await section.getByLabel('API Key',{exact:true}).fill('synthetic-isolated-provider-key');await expect(section.getByRole('button',{name:'保存配置'})).toBeDisabled();await section.getByRole('checkbox').check();await section.getByRole('button',{name:'保存配置'}).click();await expect(section.getByRole('status')).toContainText('已保存到当前登录会话')
 await section.getByRole('button',{name:'测试连接（少量用量）'}).click();await expect(section.getByRole('status')).toContainText('连接成功');expect(await section.getByLabel('API Key',{exact:true}).inputValue()).toBe('')
 const storage=await page.evaluate(()=>JSON.stringify({local:{...localStorage},session:{...sessionStorage}}));expect(storage).not.toContain('synthetic-isolated-provider-key');const status=await (await page.request.get('/api/v1/ai-settings')).text();expect(status).not.toContain('synthetic-isolated-provider-key')
 await section.getByRole('button',{name:'清除',exact:true}).click();await expect(section.getByRole('status')).toContainText('已清除');await expect(section.getByRole('button',{name:'测试连接（少量用量）'})).toBeDisabled()
})

test('RUNTIME-02 switching retained trading workspace stops demand heartbeats',async({page})=>{
 await login(page,'author');const r=await page.request.post('/api/v1/trading/runs',{data:{release_id:fixture().releases.public,market:'CRYPTO',environment:'platform_sim',symbol:'BTC-USD',interval:'1d',initial_cash:'10000'}});expect(r.ok()).toBeTruthy();const run=await r.json()
 expect((await page.request.post('/api/v1/trading/runs/'+run.id+'/start')).ok()).toBeTruthy()
 const heartbeat=page.waitForResponse(response=>response.url().endsWith('/compute/runtime/'+run.id+'/heartbeat')&&response.ok())
 await route(page,'#/trading');await heartbeat;await page.waitForLoadState('networkidle')
 await route(page,'#/journal/overview');await expect(page.locator('.journal-root:not([hidden])')).toBeVisible()
 const requests:string[]=[];page.on('request',r=>{if(r.url().includes('/compute/runtime/'))requests.push(new URL(r.url()).pathname)})
 await page.clock.install();await page.clock.fastForward(31000);await page.waitForLoadState('networkidle');expect(requests).toEqual([])
 await page.request.post('/api/v1/trading/runs/'+run.id+'/stop')
})
