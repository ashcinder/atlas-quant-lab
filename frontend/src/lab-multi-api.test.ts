import { beforeEach, expect, it, vi } from 'vitest'
import { labMultiApi } from './lab-multi-api'
import { request } from './request'

vi.mock('./request', async importOriginal => ({ ...await importOriginal<typeof import('./request')>(), request: vi.fn().mockResolvedValue({ available: true }) }))

beforeEach(() => { vi.clearAllMocks(); vi.unstubAllGlobals() })

it('queries capabilities with an explicit requested engine and account header', async () => {
  const signal = new AbortController().signal
  await labMultiApi.capabilities('owner-a', signal, 'rqalpha')
  const [path, options] = vi.mocked(request).mock.calls[0]
  expect(path).toBe('/lab-multi/capabilities?engine_id=rqalpha')
  expect(options?.signal).toBe(signal)
  expect(new Headers(options?.headers).get('X-Atlas-Lab-Owner')).toBe('owner-a')
})

it('uses RQAlpha explicitly for the unified workflow without probing installed packages', async () => {
  await labMultiApi.capabilities('owner-a')
  expect(request).toHaveBeenCalledWith('/lab-multi/capabilities?engine_id=rqalpha', expect.anything())
})

it('loads industry membership for the requested Beijing date with owner and cancellation scope', async () => {
  const signal = new AbortController().signal
  await labMultiApi.industries('owner-a', signal, '2025-01-02')
  const [path, options] = vi.mocked(request).mock.calls[0]
  expect(path).toBe('/lab-multi/industries?as_of=2025-01-02')
  expect(options?.signal).toBe(signal)
  expect(new Headers(options?.headers).get('X-Atlas-Lab-Owner')).toBe('owner-a')
})

it('omits an unspecified membership date instead of inventing a current or cutoff date', async () => {
  await labMultiApi.industries('owner-a')
  expect(request).toHaveBeenCalledWith('/lab-multi/industries', expect.anything())
})

it('sends bounded report filters and cancellation without changing owner scope', async () => {
  const signal = new AbortController().signal
  await labMultiApi.reportRows('owner-a', 'job/a', 'trades', { offset: 100, limit: 50, symbol: '000001.SZ', side: 'buy', descending: false }, signal)
  const [path, options] = vi.mocked(request).mock.calls[0]
  expect(path).toBe('/lab-multi/jobs/job%2Fa/report/trades?offset=100&limit=50&symbol=000001.SZ&side=buy&descending=false')
  expect(options?.signal).toBe(signal)
  expect(new Headers(options?.headers).get('X-Atlas-Lab-Owner')).toBe('owner-a')
})

it('loads the immutable job source rather than the current draft', async () => {
  await labMultiApi.reportSource('owner-a', 'old-job')
  expect(request).toHaveBeenCalledWith('/lab-multi/jobs/old-job/source', expect.objectContaining({ headers: expect.any(Headers) }))
})

it('downloads all filtered rows through the authenticated export endpoint', async () => {
  const blob = new Blob(['synthetic,csv'])
  const fetcher = vi.fn().mockResolvedValue({ ok: true, headers: new Headers({ 'Content-Disposition': 'attachment; filename="atlas-report-test-trades.csv"' }), blob: async () => blob })
  vi.stubGlobal('fetch', fetcher)
  const result = await labMultiApi.downloadReport('owner-a', 'test', 'trades', { symbol: '000001.SZ', start: '2025-01-02' })
  const [url, options] = fetcher.mock.calls[0]
  expect(url).toBe('/api/v1/lab-multi/jobs/test/export?symbol=000001.SZ&start=2025-01-02&table=trades')
  expect(options.credentials).toBe('include')
  expect(options.headers['X-Atlas-Lab-Owner']).toBe('owner-a')
  expect(result).toEqual({ blob, filename: 'atlas-report-test-trades.csv' })
})

it('makes export errors visible and emits the session-expired signal', async () => {
  const expired = vi.fn()
  window.addEventListener('atlas-session-expired', expired)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({ detail: '请重新登录' }) }))
  await expect(labMultiApi.downloadReport('owner-a', 'test', 'logs')).rejects.toThrow('请重新登录')
  expect(expired).toHaveBeenCalledOnce()
  window.removeEventListener('atlas-session-expired', expired)
})

it('does not trust a download filename containing path separators', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, headers: new Headers({ 'Content-Disposition': 'attachment; filename="../private.json"' }), blob: async () => new Blob() }))
  const result = await labMultiApi.downloadReport('owner-a', 'test', 'snapshot')
  expect(result.filename).toBe('atlas-report-test-snapshot.json')
})
