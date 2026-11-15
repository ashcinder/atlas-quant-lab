/** Native browser tab zoom, using a disposable Chromium profile and zoom API. */
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { chromium } from '../../frontend/node_modules/playwright/index.mjs'

const [runDir, outputDir] = process.argv.slice(2)
if (!runDir || !outputDir) throw Error('usage: chromium-native-zoom.mjs RUN_DIRECTORY OUTPUT_DIRECTORY')
const run = JSON.parse(await readFile(join(runDir, 'run.json'), 'utf8'))
if (!run.synthetic_only || !/^http:\/\/127\.0\.0\.1:\d+$/.test(run.origin) || run.port === 18095) {
  throw Error('Only the disposable Docker site is allowed')
}
await mkdir(outputDir, { recursive: true })
const tmp = await mkdtemp(join(tmpdir(), 'atlas-chromium-zoom-'))
const extension = join(tmp, 'extension')
await mkdir(extension)
await writeFile(join(extension, 'manifest.json'), JSON.stringify({
  name: 'Disposable Atlas zoom probe', version: '1', manifest_version: 3,
  permissions: ['tabs'], background: { service_worker: 'worker.js' },
}))
await writeFile(join(extension, 'worker.js'), '')
const context = await chromium.launchPersistentContext(join(tmp, 'profile'), {
  channel: 'chromium', headless: true, viewport: null,
  args: ['--window-size=1440,900', '--disable-extensions-except=' + extension, '--load-extension=' + extension],
})
const report = { browser: 'Chromium', method: 'chrome.tabs.setZoom/getZoom', images: run.images, surfaces: [] }
try {
  const worker = context.serviceWorkers()[0] ?? await context.waitForEvent('serviceworker')
  const page = context.pages()[0] ?? await context.newPage()
  await page.goto(run.origin)
  const setZoom = async factor => worker.evaluate(async ({ origin, factor }) => {
    const tab = (await chrome.tabs.query({})).find(item => item.url?.startsWith(origin + '/'))
    if (!tab) throw Error('Test tab missing')
    await chrome.tabs.setZoom(tab.id, factor)
    return chrome.tabs.getZoom(tab.id)
  }, { origin: run.origin, factor })
  await page.getByLabel('登录邮箱').fill('user95@e2e.example.test')
  await page.getByLabel('密码', { exact: true }).fill(process.env.ATLAS_E2E_PASSWORD ?? 'Only-E2E-Fixture-2026!')
  await page.getByRole('button', { name: '登录 Atlas', exact: true }).click()
  await page.getByRole('button', { name: '运行回测', exact: true }).waitFor()
  const metrics = () => page.evaluate(() => ({ width: innerWidth, height: innerHeight, dpr: devicePixelRatio, cssZoom: getComputedStyle(document.documentElement).zoom }))
  const normal = await metrics()
  report.zoom = await setZoom(2)
  await page.waitForFunction(width => innerWidth <= width / 2 + 4, normal.width)
  report.normal = normal
  report.zoomed = await metrics()
  if (report.zoom !== 2 || report.zoomed.cssZoom !== normal.cssZoom) throw Error('Native zoom is not 200 percent')

  const surfaces = [
    ['#single', page.getByRole('button', { name: '运行回测', exact: true })],
    ['#portfolio', page.getByRole('button', { name: '选择资产', exact: true })],
    ['#research', page.getByRole('button', { name: '新建策略', exact: true })],
    ['#quantjudge', page.getByRole('button', { name: '创建策略身份', exact: true })],
    ['#/journal/accounts', page.getByRole('button', { name: '新增账户', exact: true })],
    ['#/trading', page.getByRole('button', { name: '新建运行', exact: true }).first()],
    ['#/proof', page.getByRole('link', { name: /qzp_/ }).first()],
  ]
  for (const [hash, control] of surfaces) {
    await page.evaluate(hash => { location.hash = hash }, hash)
    try {
      await control.waitFor({ timeout: 8000 })
      await control.scrollIntoViewIfNeeded()
      const geometry = await control.evaluate(element => {
        const rect = element.getBoundingClientRect()
        const target = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2)
        return { left: rect.left, right: rect.right, width: innerWidth,
          hit: Boolean(target && element.contains(target)), scrollWidth: document.documentElement.scrollWidth }
      })
      const nativeZoom = await setZoom(2)
      const passed = geometry.left >= -1 && geometry.right <= geometry.width + 1 &&
        geometry.hit && nativeZoom === 2
      report.surfaces.push({ hash, nativeZoom, ...geometry, passed })
      await page.screenshot({ path: join(outputDir, hash.replace(/[^a-z]+/g, '-') + '.png') })
    } catch (error) {
      report.surfaces.push({ hash, passed: false, error: error.message.split('\n')[0] })
    }
  }
  report.passed = report.surfaces.every(surface => surface.passed)
} finally {
  await context.close()
  await rm(tmp, { recursive: true, force: true })
  await writeFile(join(outputDir, 'result.json'), JSON.stringify(report, null, 2))
}
if (!report.passed) process.exitCode = 1
