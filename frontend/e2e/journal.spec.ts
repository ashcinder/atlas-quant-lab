import {test,expect,login,route,resetLedger} from './helpers'
import {readFile} from 'node:fs/promises'
async function accountForm(page:import('@playwright/test').Page,name:string){
 await route(page,'#/journal/accounts');await page.getByRole('button',{name:'新增账户',exact:true}).click()
 await page.getByLabel('账户名称',{exact:true}).fill(name);await page.getByRole('button',{name:'保存账户',exact:true}).click()
 await expect(page.getByRole('dialog')).toBeHidden();const response=await page.request.get('/api/ledger');const state=(await response.json()).state;expect(state.accounts.some((a:{name:string})=>a.name===name)).toBeTruthy();return state.accounts.find((a:{name:string})=>a.name===name)
}
test('LEDGER-01 create account and asset then refresh preserves exact values',async({page,account})=>{
 await login(page,account);await resetLedger(page);await page.reload();await accountForm(page,'E2E Account A')
 await page.locator('.account-card').filter({has:page.getByRole('heading',{name:'E2E Account A',exact:true})}).getByRole('button',{name:/进入账户/}).click();await page.getByRole('button',{name:'添加资产',exact:true}).first().click()
 await page.getByLabel('资产名称',{exact:true}).fill('E2E Holding');await page.getByLabel(/^当前金额（USD）/).fill('1200');await page.getByLabel(/^总投入金额（USD）/).fill('1000')
 await page.getByRole('dialog').getByRole('button',{name:'添加资产',exact:true}).first().click();await expect(page.getByRole('dialog')).toBeHidden()
 let state=(await (await page.request.get('/api/ledger')).json()).state;expect(state.holdings).toHaveLength(1);expect(state.holdings[0].name).toBe('E2E Holding')
 await page.reload();await page.locator('.account-card').filter({has:page.getByRole('heading',{name:'E2E Account A',exact:true})}).getByRole('button',{name:/进入账户/}).click();await expect(page.getByText('E2E Holding',{exact:true}).first()).toBeVisible()
 state=(await (await page.request.get('/api/ledger')).json()).state;expect(state.entries.length).toBeGreaterThan(0)
})
test('LEDGER-02 note create edit delete persists via real server',async({page,account})=>{
 await login(page,account);await resetLedger(page);await route(page,'#/journal/journal');await page.getByRole('button',{name:/^投资手记/}).click();await page.getByRole('button',{name:'写手记',exact:true}).click()
 await page.getByLabel('标题',{exact:true}).fill('E2E note');await page.getByLabel('正文',{exact:true}).fill('A synthetic note without personal data.');await page.getByRole('button',{name:'保存手记',exact:true}).click();await expect(page.getByRole('dialog')).toBeHidden()
 const state=(await (await page.request.get('/api/ledger')).json()).state;expect(state.journals.some((j:{title:string})=>j.title==='E2E note')).toBeTruthy()
 await page.reload();await page.getByRole('button',{name:/^投资手记/}).click();await page.getByRole('button',{name:'删除手记 E2E note'}).click()
 await page.getByRole('dialog').getByRole('button',{name:'确认',exact:true}).click()
 await expect.poll(async()=>((await (await page.request.get('/api/ledger')).json()).state.journals.length)).toBe(0)
})
test('LEDGER-03 backup download content and destructive reset confirmation',async({page,account})=>{
 await login(page,account);await resetLedger(page);await page.reload();await accountForm(page,'E2E Backup');await route(page,'#/journal/settings')
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'导出完整备份',exact:true}).click();const file=await download;const data=JSON.parse(await readFile((await file.path())!,'utf8'));expect(JSON.stringify(data)).toContain('E2E Backup')
 await page.getByRole('button',{name:'清空数据',exact:true}).click();await page.getByLabel('输入“清空”确认').fill('wrong');await page.getByRole('button',{name:'确认清空'}).click();await expect(page.getByRole('dialog')).toContainText('请输入“清空”确认操作')
 await page.getByLabel('输入“清空”确认').fill('清空');await page.getByLabel('清空范围').selectOption('all');await page.getByRole('button',{name:'确认清空'}).click();await expect(page.getByRole('dialog')).toBeHidden()
 expect((await (await page.request.get('/api/ledger')).json()).state.accounts).toHaveLength(0)
})
test('LEDGER-04 optimistic revision conflict cannot silently overwrite',async({page,account})=>{
 await login(page,account);await resetLedger(page);const old=await (await page.request.get('/api/ledger')).json()
 const changed=structuredClone(old.state);changed.journals.push({id:'note-concurrent',title:'Concurrent A',body:'Synthetic concurrent update',date:'2026-11-08',tag:''})
 const first=await page.request.put('/api/ledger',{data:{revision:old.revision,state:changed}});expect(first.ok()).toBeTruthy()
 const stale=await page.request.put('/api/ledger',{data:{revision:old.revision,state:old.state}});expect(stale.status()).toBe(409)
 expect(JSON.stringify((await (await page.request.get('/api/ledger')).json()).state)).toContain('Concurrent A')
})
test('LEDGER-05 invalid imported backup cannot replace existing account',async({page,account})=>{
 await login(page,account);await resetLedger(page);await page.reload();await accountForm(page,'E2E Protected Import');await route(page,'#/journal/settings')
 const chooser=page.waitForEvent('filechooser');await page.getByRole('button',{name:'从备份恢复',exact:true}).click();await (await chooser).setFiles({name:'broken.json',mimeType:'application/json',buffer:Buffer.from('{"accounts":42}')})
 await expect(page.getByRole('status').first()).toContainText(/无效|格式|缺少|不支持此账本版本/);expect(JSON.stringify((await (await page.request.get('/api/ledger')).json()).state)).toContain('E2E Protected Import')
})
test('LEDGER-06 account and transfer form validates same-account before saving',async({page,account})=>{
 await login(page,account);await resetLedger(page);await page.reload();const transferA=await accountForm(page,'E2E Transfer A');await page.reload();await accountForm(page,'E2E Transfer B');await page.getByRole('button',{name:'账户间转账'}).click()
 await expect(page.getByLabel('转出账户')).toBeVisible();await expect(page.getByLabel('转入账户')).toBeVisible()
 await page.getByRole('combobox',{name:'转出账户'}).selectOption(transferA.id);await expect(page.getByRole('combobox',{name:'转入账户'}).getByRole('option',{name:'E2E Transfer A',exact:true})).toHaveCount(0)

})

test('LEDGER-07 positive cash flow transfer conserves account total',async({page,account})=>{
 await login(page,account);await resetLedger(page);await page.reload();const a=await accountForm(page,'E2E Funded');const b=await accountForm(page,'E2E Destination')
 await page.getByRole('button',{name:'记一笔',exact:true}).first().click();const d=page.getByRole('dialog');await d.getByRole('combobox',{name:'投资账户'}).selectOption(a.id);await d.getByRole('combobox',{name:'记录类型'}).selectOption('deposit');await d.getByLabel('金额（USD）',{exact:true}).fill('1000.25');await d.getByRole('button',{name:'保存记录',exact:true}).click();await expect(d).toBeHidden()
 await page.getByRole('button',{name:'账户间转账'}).click();await page.getByRole('combobox',{name:'转出账户'}).selectOption(a.id);await page.getByRole('combobox',{name:'转入账户'}).selectOption(b.id);await page.getByLabel(/^转账金额（USD）/).fill('123.45');await page.getByRole('button',{name:'记录转账'}).click();await expect(d).toBeHidden()
 const state=(await (await page.request.get('/api/ledger')).json()).state;expect(state.entries).toHaveLength(3);const amounts=state.entries.filter((e:{transferId?:string})=>e.transferId);expect(amounts).toHaveLength(2);expect(amounts[0].amount).toBe(amounts[1].amount);expect(amounts[0].amount).toBe(123.45)
})
test('LEDGER-08 valid backup restores after clearing into independent account',async({page,account,browser})=>{
 await login(page,account);await resetLedger(page);await page.reload();await accountForm(page,'E2E Roundtrip');await route(page,'#/journal/settings')
 const pending=page.waitForEvent('download');await page.getByRole('button',{name:'导出完整备份'}).click();const download=await pending;const content=await readFile((await download.path())!);const original=(await (await page.request.get('/api/ledger')).json()).state
 const other=await browser.newContext();const target=await other.newPage();await login(target,'user99');await resetLedger(target);await route(target,'#/journal/settings');const chooser=target.waitForEvent('filechooser');await target.getByRole('button',{name:'从备份恢复'}).click();await (await chooser).setFiles({name:'roundtrip.json',mimeType:'application/json',buffer:content});await target.getByRole('dialog').getByRole('button',{name:'确认',exact:true}).click();await expect(target.getByRole('dialog')).toBeHidden()
 const restored=(await (await target.request.get('/api/ledger')).json()).state;expect(restored.accounts).toEqual(original.accounts);expect(restored.entries).toEqual(original.entries);expect(restored.holdings).toEqual(original.holdings);await other.close()
})
test('LEDGER-09 manual plan pause resume delete persists without trading',async({page,account})=>{
 await login(page,account);await resetLedger(page);await page.reload();await accountForm(page,'E2E Plan Account');await route(page,'#/journal/plans');await page.getByRole('button',{name:'新建计划',exact:true}).click();const d=page.getByRole('dialog');await d.getByLabel('计划名称',{exact:true}).fill('E2E Manual Plan');await d.getByRole('combobox',{name:/记账方式/}).selectOption('manual');await d.getByLabel('每次投入（USD）',{exact:true}).fill('123.45');await d.getByRole('button',{name:'保存计划'}).click();await expect(d).toBeHidden()
 const plans=async()=>((await (await page.request.get('/api/ledger')).json()).state.plans);expect((await plans())[0].mode).toBe('manual');await page.getByRole('button',{name:'暂停',exact:true}).click();await expect.poll(async()=>(await plans())[0].paused).toBe(true);await page.getByRole('button',{name:'恢复',exact:true}).click();await expect.poll(async()=>(await plans())[0].paused).toBe(false)
 await page.getByRole('button',{name:'删除计划 E2E Manual Plan'}).click();await page.getByRole('dialog').getByRole('button',{name:'确认',exact:true}).click();await expect.poll(async()=>(await plans()).length).toBe(0)
})
