import { afterEach, describe, expect, it, vi } from 'vitest'
import { request } from './request'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

describe('API transport', () => {
  it('expires the login session on an ordinary 401, but not a developer credential rejection', async () => {
    const expired = vi.fn()
    window.addEventListener('atlas-session-expired', expired)
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response('{}', { status: 401 }))))
    try {
      await expect(request('/runs')).rejects.toMatchObject({ status: 401 })
      expect(expired).toHaveBeenCalledTimes(1)
      await expect(request('/packages', { headers: { 'X-Developer-Token': 'wrong-test-token' } })).rejects.toMatchObject({ status: 401 })
      expect(expired).toHaveBeenCalledTimes(1)
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 401, headers: { 'X-Atlas-Session-Required': '1' } })))
      await expect(request('/packages', { headers: { 'X-Developer-Token': 'valid-test-token' } })).rejects.toMatchObject({ status: 401 })
      expect(expired).toHaveBeenCalledTimes(2)
    } finally { window.removeEventListener('atlas-session-expired', expired) }
  })

  it('formats validation errors without exposing submitted secret inputs', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: [
      { loc: ['body', 'params', 'fast'], msg: 'Must be greater than zero', input: 'private-secret', ctx: { secret: 'secret' } },
    ] }), { status: 422 })))
    await expect(request('/test')).rejects.toMatchObject({ status: 422, message: '请检查输入：params.fast：Must be greater than zero' })
  })

  it('keeps caller credentials and lets the browser generate multipart boundaries', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)
    await request('/upload', { method: 'POST', headers: { 'X-Developer-Token': 'test-only' }, body: new FormData() })
    const headers: Headers = fetchMock.mock.calls[0][1].headers
    expect(fetchMock.mock.calls[0][1].credentials).toBe('include')
    expect(headers.get('X-Developer-Token')).toBe('test-only')
    expect(headers.has('Content-Type')).toBe(false)
  })

  it('times out without automatically retrying a mutation', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn((_url, options: RequestInit) => new Promise((_resolve, reject) => {
      options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    }))
    vi.stubGlobal('fetch', fetchMock)
    const result = expect(request('/save', { method: 'POST' }, 50)).rejects.toMatchObject({ kind: 'timeout' })
    await vi.advanceTimersByTimeAsync(51)
    await result
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('preserves caller cancellation instead of reporting it as a network failure', async () => {
    vi.stubGlobal('fetch', vi.fn((_url, options: RequestInit) => new Promise((_resolve, reject) => {
      options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    })))
    const controller = new AbortController()
    const result = expect(request('/bars', { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' })
    controller.abort()
    await result
  })

  it('distinguishes a proxy HTML response from successful JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>proxy fallback</html>')))
    await expect(request('/test')).rejects.toMatchObject({ kind: 'invalid_response' })
  })
})
