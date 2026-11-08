import {test,expect,login,route,savedRun} from './helpers'
test('LAB-01 project create invalid symbol edit and refresh preserve identity',async({page,account})=>{
 await login(page,account);await route(page,'#research');await page.getByRole('button',{name:'新建策略项目',exact:true}).click()
 const dialog=page.getByRole('dialog');const name='E2E Project '+Date.now()
 await dialog.locator('[name=project-name]').fill(name);await dialog.locator('[name=project-thesis]').fill('Synthetic test thesis with repeatable transaction-cost-aware evidence.')
 await dialog.locator('[name=asset-symbol]').fill('无匹配标的');await dialog.getByRole('button',{name:'创建策略项目',exact:true}).click();await expect(dialog).toContainText('请输入标的代码或名称')
 await dialog.locator('[name=asset-symbol]').fill('BTC-USD');await dialog.getByRole('button',{name:'创建策略项目',exact:true}).click();await expect(dialog).toBeHidden();await expect(page.getByLabel('选择策略项目')).toContainText(name)
 await page.reload();await expect(page.getByLabel('选择策略项目')).toContainText(name)
})
test('LAB-02 template snapshot saves and actual worker backtest completes',async({page,account})=>{
 await login(page,account);await route(page,'#research');await page.getByRole('button',{name:'模板',exact:true}).click()
 await page.getByLabel('策略名称',{exact:true}).fill('E2E Local Preset');await page.getByRole('button',{name:'保存副本',exact:true}).click();await expect(page.getByText('参数副本已保存到当前浏览器，可从“我的参数副本”载入。',{exact:true})).toBeVisible()
 await savedRun(page,()=>page.getByRole('button',{name:'运行模板回测',exact:true}).click())
})
test('LAB-03 bounded Python checks and backtests with no provider key',async({page,account})=>{
 await login(page,account);await route(page,'#research');await page.getByRole('button',{name:'代码',exact:true}).click();await page.getByRole('button',{name:'检查代码',exact:true}).click();await expect(page.locator('body')).toContainText('通过')
 const result=await savedRun(page,()=>page.getByRole('button',{name:'进行回测',exact:true}).click());expect(result.strategy.id).toBe('python_bounded')
})
test('LAB-04 visual rules add condition and backtest',async({page,account})=>{
 await login(page,account);await route(page,'#research');await page.getByRole('button',{name:'买卖条件',exact:true}).click();await page.getByRole('button',{name:'添加入场条件',exact:true}).click();await expect(page.getByLabel('入场条件组合')).toBeVisible()
 await savedRun(page,()=>page.getByRole('button',{name:'运行自定义回测',exact:true}).click())
})
test('LAB-05 parameter research completes in browser and keeps results',async({page,account})=>{
 test.setTimeout(90000);await login(page,account);await route(page,'#research');await page.getByRole('button',{name:'参数测试',exact:true}).click()
 const saved=page.waitForResponse(r=>r.url().endsWith('/api/v1/compute/runs')&&r.request().method()==='POST')
 await page.getByRole('button',{name:'运行稳健性研究',exact:true}).click();const response=await saved;expect(response.ok()).toBeTruthy();const result=await response.json();expect(result.compute.execution_location).toBe('browser');expect(result.tested_combinations).toBeGreaterThan(0)
})

test('LAB-06 parameter comparison uses worker and applies ranked values without server fallback',async({page,account})=>{
 await login(page,account);await route(page,'#research');await page.getByRole('button',{name:'参数测试',exact:true}).click();const sweep=page.locator('.parameter-sweep:visible');await sweep.getByText('比较参数',{exact:true}).click();await sweep.getByRole('checkbox',{name:'快速周期',exact:true}).check();await sweep.getByLabel('快速周期 最小值',{exact:true}).fill('5');await sweep.getByLabel('快速周期 最大值',{exact:true}).fill('10');await sweep.getByLabel('快速周期 每次增加',{exact:true}).fill('5')
 const legacy:string[]=[];page.on('request',r=>{if(r.url().endsWith('/api/v1/backtests'))legacy.push(r.url())});await sweep.getByRole('button',{name:'开始比较'}).click();await expect(sweep.getByRole('status')).toContainText('成功 2');expect(legacy).toEqual([]);await expect(sweep.getByRole('button',{name:'使用这组'})).toHaveCount(2)
})

test('LAB-07 completed research survives reload with exact saved candidate table',async({page,account})=>{
 await login(page,account);await route(page,'#research');await page.getByRole('button',{name:'参数测试',exact:true}).click();const saved=page.waitForResponse(r=>r.url().endsWith('/api/v1/compute/runs')&&r.request().method()==='POST');await page.getByRole('button',{name:'运行稳健性研究',exact:true}).click();expect((await saved).ok()).toBeTruthy();const rows=page.locator('.research-table tbody tr');await expect(rows.first()).toBeVisible();const text=await rows.allTextContents();await page.reload();await page.getByRole('button',{name:'参数测试',exact:true}).click();await expect(page.locator('.research-table tbody tr').first()).toBeVisible();expect(await page.locator('.research-table tbody tr').allTextContents()).toEqual(text)
})

test('LAB-08 cancel and refresh interruption remain explicit and allow a new research',async({page,account})=>{
 await login(page,account);await route(page,'#research');await page.getByRole('button',{name:'参数测试',exact:true}).click();await page.getByRole('button',{name:'运行稳健性研究',exact:true}).click();await page.locator('.research-progress').getByRole('button',{name:'取消',exact:true}).click();await expect(page.locator('.research-results')).toContainText('研究已取消')
 await page.getByRole('button',{name:'运行稳健性研究',exact:true}).click();await expect(page.locator('.research-progress')).toBeVisible();await page.reload();await page.getByRole('button',{name:'参数测试',exact:true}).click();await expect(page.locator('.research-results')).toContainText(/页面已关闭，研究已中断|研究已取消/);await expect(page.getByRole('button',{name:'运行稳健性研究',exact:true})).toBeEnabled()
})
test('MARKET-03 unsupported favourites control states its unavailable capability',async({page,account})=>{
 await login(page,account);await expect(page.getByRole('button',{name:'收藏标的（尚未接入）',exact:true})).toBeDisabled();await expect(page.getByRole('button',{name:'收藏标的（尚未接入）',exact:true})).toHaveAttribute('title','收藏功能尚未接入')
})

test('TABS-01 opener copied session scope cannot interrupt an active original research',async({page,account,context})=>{
 await login(page,account);await route(page,'#research');await page.getByRole('button',{name:'参数测试',exact:true}).click();await page.getByRole('button',{name:'运行稳健性研究',exact:true}).click();await expect(page.locator('.research-progress')).toBeVisible();const scope=await page.evaluate(()=>sessionStorage.getItem('atlas.compute.tab'));const opened=context.waitForEvent('page');await page.evaluate(()=>window.open(location.href));const other=await opened;await other.getByRole('button',{name:'参数测试',exact:true}).click();await expect.poll(()=>other.evaluate(()=>sessionStorage.getItem('atlas.compute.tab'))).not.toBe(scope);await expect(page.locator('.research-table tbody tr').first()).toBeVisible();await expect(page.locator('.research-results')).not.toContainText('研究已中断');await other.close()
})
