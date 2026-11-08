import type { Page } from '@playwright/test'
import { expect, route } from './helpers'

export async function importSyntheticWallet(page: Page, secret: string) {
  await page.getByRole('button', { name: '本地设置', exact: true }).click()
  await page.getByText('Supervisor 账户与私钥', { exact: true }).click()
  await page.getByLabel('私钥（首次配置或更换）', { exact: true }).fill(secret)
  await page.getByLabel('本地解锁密码', { exact: true }).fill('Synthetic wallet encryption phrase only')
  await page.getByRole('button', { name: '加密保存', exact: true }).click()
  await expect(page.getByText('账户已解锁', { exact: true })).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: '关闭本地设置', exact: true }).click()
}

export async function showRuntimeMarket(page: Page) {
  await route(page, '#quantjudge')
  await page.getByRole('button', { name: '可运行策略', exact: true }).click()
  await expect(page.getByRole('navigation', { name: '可运行策略', exact: true })).toBeVisible()
}
