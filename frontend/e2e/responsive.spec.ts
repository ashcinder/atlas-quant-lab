import {test,expect,login,route} from './helpers'
for(const size of [{width:1440,height:900},{width:1920,height:1080},{width:768,height:1024},{width:390,height:844},{width:360,height:800}]){
 test(`RESP-${size.width} all workspaces expose primary controls within viewport`,async({page,account})=>{
  await page.setViewportSize(size);await login(page,account)
  for(const [hash,selector] of [['#single','.run-button'],['#portfolio','.run-button'],['#research','.lab-library-header'],['#/journal/overview','.journal-root:not([hidden])'],['#/trading','.trading-workspace']]){
   await route(page,hash);const surface=page.locator(selector).first();await expect(surface).toBeVisible()
   const layout=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth}));expect(layout.scroll,'Document must not force horizontal viewport scrolling').toBeLessThanOrEqual(layout.width+2)
   if(selector==='.run-button'){const box=await surface.boundingBox();expect(box).not.toBeNull();expect(box!.x).toBeGreaterThanOrEqual(0);expect(box!.x+box!.width).toBeLessThanOrEqual(size.width+2)}
  }
  await test.info().attach('responsive-'+size.width+'.png',{body:await page.screenshot(),contentType:'image/png'})
 })
}
test('A11Y-01 keyboard login and settings Escape restore focus',async({page,account})=>{
 await page.goto('/');await page.getByLabel('登录邮箱').fill(account+'@e2e.example.test');await page.getByLabel('密码',{exact:true}).fill('Only-E2E-Fixture-2026!');await page.getByLabel('密码',{exact:true}).press('Enter');await expect(page.getByLabel('登录邮箱')).toBeHidden()
 await page.getByRole('button',{name:'本地设置',exact:true}).click();await expect(page.getByRole('dialog',{name:'本地设置'})).toBeVisible();await page.keyboard.press('Escape');await expect(page.getByRole('dialog',{name:'本地设置'})).toBeHidden();await expect(page.getByRole('button',{name:'本地设置',exact:true})).toBeFocused();await page.keyboard.press('Enter');await page.getByRole('button',{name:'关闭本地设置'}).focus();await page.keyboard.press('Enter');await expect(page.getByRole('button',{name:'本地设置',exact:true})).toBeFocused()
})
test('A11Y-02 theme and text scaling preserve operation',async({page,account})=>{
 await login(page,account);await page.getByRole('button',{name:'本地设置',exact:true}).click();const settings=page.getByRole('dialog',{name:'本地设置'});await settings.getByRole('combobox',{name:'主题',exact:true}).selectOption('white');await expect(settings.getByRole('combobox',{name:'主题',exact:true})).toHaveValue('white')
 await page.reload();await page.getByRole('button',{name:'本地设置',exact:true}).click();await expect(page.getByRole('dialog',{name:'本地设置'}).getByRole('combobox',{name:'主题',exact:true})).toHaveValue('white')
 await page.evaluate(()=>{document.documentElement.style.fontSize='200%'});await expect(page.getByRole('button',{name:'运行回测',exact:true})).toBeVisible()
})
test('RESP-controls mobile exposes data period history alerts and settings',async({page,account})=>{
 await page.setViewportSize({width:390,height:844});await login(page,account)
 const top=await page.locator('.topbar').boundingBox();const workspace=await page.locator('.workspace-content').first().boundingBox();expect(top).toBeTruthy();expect(workspace).toBeTruthy();expect(top!.y+top!.height).toBeLessThanOrEqual(workspace!.y+1);await expect(page.getByLabel('行情数据源')).toBeVisible();await expect(page.getByRole('button',{name:'15分',exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'回测历史',exact:true})).toBeVisible();await page.getByRole('button',{name:'本地设置',exact:true}).click();await expect(page.getByRole('dialog',{name:'本地设置'})).toBeVisible()
})
