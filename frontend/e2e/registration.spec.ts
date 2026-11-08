import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { test, expect, fixturePath, password, route } from './helpers'

const manifest = JSON.parse(readFileSync(join(dirname(fixturePath), 'run.json'), 'utf8'))

test('AUTH-05 enabled registration validates input, retains its session and rejects duplicates', async ({ page }, info) => {
  test.skip(manifest.registration_enabled !== true, 'Requires the isolated registration-enabled project')
  const address = `qa-${info.project.name}-${Date.now()}@e2e.example.test`
  await page.goto('/')
  await page.getByRole('button', { name: '创建账号', exact: true }).click()
  await page.getByLabel('登录邮箱').fill(address)
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByLabel('确认密码', { exact: true }).fill(password + 'typo')
  const sent: number[] = []
  page.on('response', response => {
    if (response.url().endsWith('/api/register')) sent.push(response.status())
  })
  const submit = page.getByRole('button', { name: '注册并进入 Atlas', exact: true })
  await submit.click()
  await expect(page.getByRole('alert')).toContainText('两次输入的密码不一致')
  expect(sent).toEqual([])
  await page.getByRole('button', { name: '返回登录', exact: true }).click()
  await expect(submit).toBeHidden()
  await page.getByRole('button', { name: '创建账号', exact: true }).click()
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByLabel('确认密码', { exact: true }).fill(password)
  await submit.click()
  await expect(page.getByRole('button', { name: '运行回测', exact: true })).toBeVisible()
  expect(sent).toEqual([201])
  await page.reload()
  await expect(page.getByRole('button', { name: '运行回测', exact: true })).toBeVisible()
  expect((await page.request.get('/api/ledger')).status()).toBe(200)

  await route(page, '#/journal/settings')
  await page.getByRole('button', { name: '退出登录', exact: true }).filter({ visible: true }).first().click()
  await expect(page.getByRole('button', { name: '登录 Atlas', exact: true })).toBeVisible()
  expect((await page.request.get('/api/ledger')).status()).toBe(401)
  await page.getByRole('button', { name: '创建账号', exact: true }).click()
  await page.getByLabel('登录邮箱').fill(address)
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByLabel('确认密码', { exact: true }).fill(password)
  await submit.click()
  await expect(page.getByRole('alert')).toContainText('该邮箱已注册')
  expect(sent).toEqual([201, 409])
  await page.getByRole('button', { name: '返回登录', exact: true }).click()
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录 Atlas', exact: true }).click()
  await expect(page.getByLabel('登录邮箱')).toBeHidden()
})
