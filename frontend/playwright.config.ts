import { defineConfig } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import { mkdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

const baseURL = process.env.ATLAS_E2E_URL ?? 'http://127.0.0.1:18221'
const url = new URL(baseURL)
if (!['127.0.0.1','localhost'].includes(url.hostname) || url.port === '18095') {
  throw new Error('E2E must use an isolated loopback fixture, never the deployed site')
}
const fixturePath=process.env.ATLAS_E2E_FIXTURE ?? fileURLToPath(new URL('../.artifacts/e2e-functional-20261108-r2/fixture.json',import.meta.url))
const isolated=JSON.parse(readFileSync(join(dirname(fixturePath),'run.json'),'utf8'))
const fixture=JSON.parse(readFileSync(fixturePath,'utf8'))
if(!isolated.synthetic_only||!fixture.synthetic_only||isolated.origin!==baseURL)throw new Error('Fixture/run manifest does not match isolated target')
const evidence = process.env.ATLAS_E2E_EVIDENCE ?? fileURLToPath(new URL('../.artifacts/comprehensive-20261108/playwright', import.meta.url))
const firefoxHome = evidence + '/firefox-home'
if (process.platform === 'darwin') mkdirSync(firefoxHome, { recursive: true })
export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  outputDir: evidence + '/artifacts',
  reporter: [['list'], ['json', { outputFile: evidence + '/results.json' }], ['html', { outputFolder: evidence + '/html', open: 'never' }]],
  use: { baseURL, viewport: { width: 1440, height: 900 }, locale: 'zh-CN', timezoneId: 'Asia/Shanghai', trace: 'off', screenshot: 'only-on-failure', video: 'off', actionTimeout: 10_000 },
  projects: ['chromium','firefox','webkit'].map(name => ({ name, use: { browserName: name as 'chromium'|'firefox'|'webkit', ...(name === 'firefox' && process.platform === 'darwin' ? { launchOptions: { env: { ...process.env, CFFIXED_USER_HOME: firefoxHome } } } : {}) } })),
})
