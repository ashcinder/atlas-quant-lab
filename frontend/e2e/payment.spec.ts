import {Wallet,Transaction} from 'ethers'
import {test,expect,login,route,password} from './helpers'
import { importSyntheticWallet, showRuntimeMarket } from './role-flow'

test('PAY-01 isolated signed payment pending unauthorized repeat confirm subscription',async({page,browser})=>{
 // A deterministic disposable key used only with the synthetic RPC boundary.
 const wallet=new Wallet('0x'+'12'.repeat(32));await login(page,'author')
 const release=await (await page.request.post('/api/v1/strategy-releases',{data:{name:'E2E Paid Private '+Date.now(),source_kind:'builtin',strategy_id:'sma_cross',params:{fast:5,slow:20},markets:['CRYPTO'],source_visibility:'private',published:true}})).json();expect(release.id).toBeTruthy()
 const offer=await page.request.put('/api/v1/strategy-releases/'+release.id+'/bkc-offer',{data:{recipient:'0x'+'34'.repeat(20),amount_bkc:'0.01'}});expect(offer.ok()).toBeTruthy()
 const context=await browser.newContext();const subscriber=await context.newPage();await login(subscriber,'outsider')
 const prepare=()=>subscriber.request.post('/api/v1/strategy-releases/'+release.id+'/bkc-order',{data:{address:wallet.address}})
 const order=await (await prepare()).json();expect((await (await prepare()).json()).id).toBe(order.id);expect(order.status).toBe('pending')
 const subscriptions=async()=>subscriber.request.get('/api/v1/strategy-subscriptions').then(r=>r.json());expect((await subscriptions()).some((x:{release_id:string})=>x.release_id===release.id)).toBe(false)
 const prepared=await (await subscriber.request.get('/api/v1/bkc-orders/'+order.id+'/signing')).json();const tx=prepared.transaction
 const raw=await wallet.signTransaction({...tx,nonce:Number(tx.nonce),chainId:BigInt(tx.chainId),type:0});const expectedHash=Transaction.from(raw).hash!
 const pending=await subscriber.request.post('/api/v1/bkc-orders/'+order.id+'/confirm',{data:{transaction_hash:expectedHash}});expect(pending.ok()).toBeTruthy();expect((await pending.json()).status).toBe('submitted');expect((await subscriptions()).some((x:{release_id:string})=>x.release_id===release.id)).toBe(false)
 const sent=await subscriber.request.post('/api/v1/bkc-orders/'+order.id+'/broadcast',{data:{raw_transaction:raw}});expect(sent.ok()).toBeTruthy();const hash=(await sent.json()).transaction_hash
 for(let i=0;i<2;i++){const result=await subscriber.request.post('/api/v1/bkc-orders/'+order.id+'/confirm',{data:{transaction_hash:hash}});expect(result.ok()).toBeTruthy();expect((await result.json()).status).toBe('confirmed')}
 const subs=(await subscriptions()).filter((x:{release_id:string})=>x.release_id===release.id);expect(subs).toHaveLength(1)
 await route(subscriber,'#single');await subscriber.reload();await subscriber.getByRole('combobox',{name:'策略来源'}).selectOption(release.id)
 const privateSaved=subscriber.waitForResponse(r=>r.url().endsWith('/api/v1/compute/private-backtests')&&r.request().method()==='POST');await subscriber.getByRole('button',{name:'运行回测',exact:true}).click();const privateRun=await privateSaved;expect(privateRun.ok()).toBeTruthy();const report=await privateRun.json();expect(report.compute.execution_location).toBe('server_private');expect(JSON.stringify(report)).not.toContain('python_source');await expect(subscriber.getByRole('region',{name:'回测结果'})).toContainText('总收益')
 await route(subscriber,'#/trading?release='+release.id+'&subscription='+subs[0].id);const runtime=subscriber.waitForResponse(r=>r.url().endsWith('/api/v1/trading/runs')&&r.request().method()==='POST');await subscriber.getByRole('button',{name:'启动模拟',exact:true}).click();const running=await runtime;expect(running.ok(),await running.text()).toBeTruthy();const started=await running.json();await expect.poll(async()=>{const stop=await subscriber.request.post('/api/v1/trading/runs/'+started.id+'/stop');return stop.ok()}).toBe(true)
 const forbidden=await page.request.get('/api/v1/bkc-orders/'+order.id);expect(forbidden.status()).toBe(404)
 await route(subscriber,'#quantjudge');await context.close()
})

test('AUTH-04 change password revokes another real session and can restore',async({page,account,browser})=>{
 await login(page,account);const other=await browser.newContext();const second=await other.newPage();await login(second,account)
 await route(page,'#/journal/settings');await page.getByRole('button',{name:'修改密码',exact:true}).click();const d=page.getByRole('dialog');await d.getByLabel('当前密码',{exact:true}).fill(password);await d.getByLabel('新密码',{exact:true}).fill(password+'New');await d.getByLabel('再次输入新密码',{exact:true}).fill(password+'New');await d.getByRole('button',{name:'更新密码'}).click();await expect(d).toBeHidden()
 expect((await second.request.get('/api/ledger')).status()).toBe(401)
 const restore=await page.request.post('/api/change-password',{data:{currentPassword:password+'New',newPassword:password}});expect(restore.ok()).toBeTruthy();await other.close()
})

test('PAY-02 lost broadcast response recovers the persisted original hash without granting premature access', async ({ page, browser }) => {
  test.setTimeout(120_000)
  await login(page, 'author')
  const name = 'QA broadcast recovery ' + Date.now()
  const releaseResponse = await page.request.post('/api/v1/strategy-releases', {
    data: {
      name, source_kind: 'builtin', strategy_id: 'sma_cross',
      params: { fast: 5, slow: 20 }, markets: ['CRYPTO'],
      source_visibility: 'private', published: true,
    },
  })
  expect(releaseResponse.ok()).toBeTruthy()
  const release = await releaseResponse.json()
  const offer = await page.request.put('/api/v1/strategy-releases/' + release.id + '/bkc-offer', {
    data: { recipient: '0x' + '51'.repeat(20), amount_bkc: '0.01' },
  })
  expect(offer.ok()).toBeTruthy()
  const context = await browser.newContext()
  try {
    const subscriber = await context.newPage()
    await login(subscriber, 'outsider')
    await importSyntheticWallet(subscriber, '0x' + '15'.repeat(32))
    await showRuntimeMarket(subscriber)
    const card = subscriber.getByRole('article').filter({ has: subscriber.getByRole('heading', { name, exact: true }) })
    const prepared = subscriber.waitForResponse(response => response.url().endsWith('/' + release.id + '/bkc-order'))
    await card.getByRole('button', { name: '使用 BKC 订阅此版本' }).click()
    const order = await (await prepared).json()
    expect(order.status).toBe('pending')
    const routePattern = '**/api/v1/bkc-orders/' + order.id + '/broadcast'
    let broadcastHash = ''
    let attempts = 0
    await subscriber.route(routePattern, async intercepted => {
      attempts++
      const accepted = await intercepted.fetch()
      expect(accepted.ok()).toBeTruthy()
      const body = await accepted.json()
      expect(body.status).toBe('submitted')
      expect(body.message).toContain('广播结果待核验')
      broadcastHash = body.transaction_hash
      await intercepted.abort('failed')
    })
    await card.getByRole('button', { name: '支付 / 核验 BKC' }).click()
    await subscriber.getByRole('dialog', { name: '确认 BKC 支付' }).getByRole('button', { name: '确认支付' }).click()
    await expect(card.getByRole('alert')).toBeVisible()
    expect(attempts).toBe(1)
    expect(broadcastHash).toMatch(/^0x[0-9a-f]{64}$/)
    const list = async () => (await (await subscriber.request.get('/api/v1/strategy-subscriptions')).json())
      .filter((item: { release_id: string }) => item.release_id === release.id)
    expect(await list()).toHaveLength(0)
    expect((await (await subscriber.request.get('/api/v1/bkc-orders/' + order.id)).json()).transaction_hash).toBe(broadcastHash)

    await subscriber.unroute(routePattern)
    await subscriber.reload()
    await showRuntimeMarket(subscriber)
    await card.getByRole('button', { name: '支付 / 核验 BKC' }).click()
    const review = subscriber.getByRole('dialog', { name: '确认 BKC 支付' })
    await expect(review).toContainText(broadcastHash)
    await review.getByRole('button', { name: '核验原交易' }).click()
    await expect.poll(async () => (await list()).length).toBe(1)
    await expect(card.getByText('已订阅此版本')).toBeVisible()
    const stored = await (await subscriber.request.get('/api/v1/bkc-orders/' + order.id)).json()
    expect(stored.status).toBe('confirmed')
    expect(stored.transaction_hash).toBe(broadcastHash)
  } finally {
    await context.close()
  }
})

test('PAY-03 a reverted payment remains failed across reload and cannot grant access', async ({ page, browser }) => {
  await login(page, 'author')
  const release = await (await page.request.post('/api/v1/strategy-releases', {
    data: {
      name: 'QA reverted ' + Date.now(), source_kind: 'builtin', strategy_id: 'sma_cross',
      params: { fast: 5, slow: 20 }, markets: ['CRYPTO'], source_visibility: 'private', published: true,
    },
  })).json()
  expect(release.id).toBeTruthy()
  const offer = await page.request.put('/api/v1/strategy-releases/' + release.id + '/bkc-offer', {
    data: { recipient: '0x' + '52'.repeat(20), amount_bkc: '0.01' },
  })
  expect(offer.ok()).toBeTruthy()
  const context = await browser.newContext()
  try {
    const subscriber = await context.newPage()
    await login(subscriber, 'outsider')
    const wallet = new Wallet('0x' + '16'.repeat(32))
    const request = subscriber.request
    const order = await (await request.post('/api/v1/strategy-releases/' + release.id + '/bkc-order', {
      data: { address: wallet.address },
    })).json()
    const path = '/api/v1/bkc-orders/' + order.id
    const { transaction } = await (await request.get(path + '/signing')).json()
    const raw = await wallet.signTransaction({
      ...transaction, nonce: Number(transaction.nonce), chainId: BigInt(transaction.chainId), type: 0,
    })
    const sent = await request.post(path + '/broadcast', { data: { raw_transaction: raw } })
    expect(sent.ok()).toBeTruthy()
    const { transaction_hash } = await sent.json()
    for (let i = 0; i < 2; i++) {
      const confirmed = await request.post(path + '/confirm', { data: { transaction_hash } })
      expect(confirmed.ok()).toBeTruthy()
      expect((await confirmed.json()).status).toBe('failed')
      if (i === 0) await subscriber.reload()
    }
    const access = await request.post('/api/v1/strategy-subscriptions', { data: { release_id: release.id } })
    expect(access.status()).toBe(402)
    const retry = await request.get(path + '/signing')
    expect(retry.status()).toBe(409)
  } finally {
    await context.close()
  }
})

test('PAY-04 explicitly retry a canonical revert, preserve its receipt and activate only the replacement', async ({ page, browser }) => {
  await login(page, 'author')
  const name = 'Synthetic safe retry ' + Date.now()
  const release = await (await page.request.post('/api/v1/strategy-releases', { data: {
    name, source_kind: 'builtin', strategy_id: 'sma_cross', params: { fast: 5, slow: 20 },
    markets: ['CRYPTO'], source_visibility: 'private', published: true,
  } })).json()
  expect(release.id).toBeTruthy()
  expect((await page.request.put('/api/v1/strategy-releases/' + release.id + '/bkc-offer', {
    data: { recipient: '0x' + '52'.repeat(20), amount_bkc: '0.01' },
  })).ok()).toBe(true)
  const context = await browser.newContext()
  try {
    const buyer = await context.newPage()
    await login(buyer, 'outsider')
    await importSyntheticWallet(buyer, '0x' + '20'.repeat(32))
    await showRuntimeMarket(buyer)
    const card = buyer.getByRole('article').filter({ has: buyer.getByRole('heading', { name, exact: true }) })
    const preparing = buyer.waitForResponse(response => response.url().endsWith('/' + release.id + '/bkc-order'))
    await card.getByRole('button', { name: '使用 BKC 订阅此版本' }).click()
    const original = await (await preparing).json()
    await card.getByRole('button', { name: '支付 / 核验 BKC' }).click()
    const dialog = buyer.getByRole('dialog', { name: '确认 BKC 支付' })
    await dialog.getByRole('button', { name: '确认支付', exact: true }).click()
    await expect(card.getByRole('alert')).toContainText('链上交易失败')
    const old = await (await buyer.request.get('/api/v1/bkc-orders/' + original.id)).json()
    expect(old.status).toBe('failed')
    const subscriptions = async () => (await (await buyer.request.get('/api/v1/strategy-subscriptions')).json())
      .filter((item: { release_id: string }) => item.release_id === release.id)
    expect(await subscriptions()).toEqual([])
    const retried = buyer.waitForResponse(response => response.url().endsWith('/' + original.id + '/retry'))
    await dialog.getByRole('button', { name: '核验失败交易并新建订单', exact: true }).click()
    const replacement = await (await retried).json()
    expect(replacement.id).not.toBe(original.id)
    expect(replacement.status).toBe('pending')
    expect(replacement.transaction_hash).toBeNull()
    await expect(dialog).toContainText(old.transaction_hash)
    expect(await subscriptions()).toEqual([])
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
    await buyer.reload()
    await buyer.getByRole('button', { name: '本地设置', exact: true }).click()
    await buyer.getByText('Supervisor 账户与私钥', { exact: true }).click()
    await buyer.getByLabel('本地解锁密码', { exact: true }).fill('Synthetic wallet encryption phrase only')
    await buyer.getByRole('button', { name: '解锁', exact: true }).click()
    await expect(buyer.getByText('账户已解锁', { exact: true })).toBeVisible()
    await buyer.getByRole('button', { name: '关闭本地设置', exact: true }).click()
    await showRuntimeMarket(buyer)
    await card.getByRole('button', { name: '支付 / 核验 BKC' }).click()
    await expect(dialog).toContainText(replacement.id)
    await expect(dialog).toContainText('原失败订单')
    await dialog.getByRole('button', { name: '确认支付', exact: true }).click()
    await expect(card.getByText('已订阅此版本')).toBeVisible()
    const successful = await (await buyer.request.get('/api/v1/bkc-orders/' + replacement.id)).json()
    expect(successful.status).toBe('confirmed')
    expect(successful.transaction_hash).not.toBe(old.transaction_hash)
    expect(await subscriptions()).toHaveLength(1)
    const retained = await (await buyer.request.get('/api/v1/bkc-orders/' + original.id)).json()
    expect(retained).toMatchObject({ status: 'failed', transaction_hash: old.transaction_hash,
      retry_order_id: replacement.id, current_order_id: replacement.id })
    expect((await page.request.get('/api/v1/bkc-orders/' + original.id)).status()).toBe(404)
  } finally {
    await context.close()
  }
})
