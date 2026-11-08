import { test as base, expect, type Page, type Request } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
export const password = process.env.ATLAS_E2E_PASSWORD ?? 'Only-E2E-Fixture-2026!'
export const fixturePath = process.env.ATLAS_E2E_FIXTURE ?? fileURLToPath(new URL('../../.artifacts/e2e-functional-20261108-r2/fixture.json',import.meta.url))
export const fixture = () => JSON.parse(readFileSync(fixturePath,'utf8'))
export function trackApiRequests(page: Page) {
  const pending = new Set<Request>()
  let changedAt = Date.now()
  page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/')) { pending.add(request); changedAt = Date.now() } })
  page.on('requestfinished', request => { pending.delete(request); changedAt = Date.now() })
  page.on('requestfailed', request => { pending.delete(request); changedAt = Date.now() })
  return () => expect.poll(() => pending.size === 0 && Date.now() - changedAt >= 500, { message: 'Current API requests finish and remain quiet before reload' }).toBe(true)
}
export async function login(page:Page, name='user00', pass=password) {
  await page.goto('/')
  await page.getByLabel('登录邮箱').fill(name+'@e2e.example.test')
  await page.getByLabel('密码',{exact:true}).fill(pass)
  const response=page.waitForResponse(r=>r.url().endsWith('/api/login')&&r.request().method()==='POST')
  await page.getByRole('button',{name:'登录 Atlas',exact:true}).click()
  expect((await response).status()).toBe(200)
  await expect(page.getByLabel('登录邮箱')).toBeHidden()
  await expect(page.getByRole('button',{name:'运行回测',exact:true})).toBeVisible()
}
export async function route(page:Page, hash:string) {
  await page.evaluate(hash=>{location.hash=hash},hash)
  await expect(page).toHaveURL(new RegExp(hash.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'$'))
}
export async function resetLedger(page:Page) {
 const r=await page.request.get('/api/ledger');expect(r.ok()).toBeTruthy();const old=await r.json()
 const response=await page.request.post('/api/reset',{data:{confirmation:'清空',keepAccounts:false,revision:old.revision}});expect(response.ok()).toBeTruthy()
}
export async function savedRun(page:Page, action:()=>Promise<unknown>) {
 const pending=page.waitForResponse(r=>r.url().endsWith('/api/v1/compute/runs')&&r.request().method()==='POST')
 await action();const r=await pending;expect(r.status()).toBe(201);const result=await r.json()
 expect(result.compute.execution_location).toBe('browser');expect(result.compute.proof_status).toBe('unverified')
 await expect(page.getByRole('region',{name:'回测结果'}).getByText('总收益',{exact:true})).toBeVisible()
 return result
}
export const test=base.extend<{account:string;pageErrors:string[]}>({
 account:async({browserName},provide,testInfo)=>{void browserName;let n=0;for(const c of testInfo.title)n=(n*31+c.charCodeAt(0))%100;await provide('user'+String(n).padStart(2,'0'))},
 pageErrors:[async({page},provide,info)=>{const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=500&&!info.title.startsWith('FAULT-'))errors.push('Unexpected HTTP '+r.status()+' '+new URL(r.url()).pathname)});await provide(errors);expect(errors,'Uncaught browser exceptions').toEqual([])},{auto:true}],
})
export {expect}
