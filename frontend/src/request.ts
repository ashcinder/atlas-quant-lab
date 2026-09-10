const API_ROOT = (import.meta.env.VITE_API_ROOT ?? '/api/v1').replace(/\/$/, '')

export class ApiError extends Error {
  readonly status: number | null
  readonly kind: 'http' | 'network' | 'timeout' | 'invalid_response'

  constructor(message: string, kind: ApiError['kind'], status: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.kind = kind
  }
}

function errorDetail(body: unknown): string | null {
  if (!body || typeof body !== 'object') return null
  if ('error' in body && typeof body.error === 'string') return body.error
  if (!('detail' in body)) return null
  const detail = body.detail
  if (typeof detail === 'string') return detail
  if (!Array.isArray(detail)) return null
  // Pydantic includes the submitted input in errors: never echo it or its context.
  const messages = detail.slice(0, 5).flatMap((item: unknown) => {
    if (!item || typeof item !== 'object' || !('msg' in item) || typeof item.msg !== 'string') return []
    const location = 'loc' in item && Array.isArray(item.loc)
      ? item.loc.filter((part) => typeof part === 'string' || typeof part === 'number').filter((part) => part !== 'body').join('.')
      : ''
    return [`${location ? `${location}：` : ''}${item.msg}`]
  })
  return messages.length ? `请检查输入：${messages.join('；')}` : null
}

export async function request<T>(path: string, options: RequestInit = {}, timeoutMs = 120_000): Promise<T> {
  const controller = new AbortController()
  let timedOut = false
  const forwardAbort = () => controller.abort(options.signal?.reason)
  if (options.signal?.aborted) forwardAbort()
  else options.signal?.addEventListener('abort', forwardAbort, { once: true })
  const timer = globalThis.setTimeout(() => { timedOut = true; controller.abort() }, timeoutMs)
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  headers.set('Accept', 'application/json')
  try {
    const response = await fetch(`${API_ROOT}${path}`, { credentials: 'include', ...options, headers, signal: controller.signal })
    if (!response.ok) {
      if (response.status === 401 && (!headers.has('X-Developer-Token') || response.headers.get('X-Atlas-Session-Required') === '1')) window.dispatchEvent(new Event('atlas-session-expired'))
      const body: unknown = await response.json().catch(() => null)
      throw new ApiError(errorDetail(body) ?? `服务请求失败（HTTP ${response.status}）。请稍后重试或查看系统状态。`, 'http', response.status)
    }
    if (response.status === 204) return undefined as T
    try { return await response.json() as T }
    catch { throw new ApiError('服务返回了无法解析的数据。请检查前后端版本及反向代理配置。', 'invalid_response', response.status) }
  } catch (reason) {
    if (options.signal?.aborted) throw options.signal.reason ?? new DOMException('请求已取消', 'AbortError')
    if (timedOut) throw new ApiError('请求超时。后台任务可能仍在执行，请先查看历史或任务状态，避免重复提交。', 'timeout')
    if (reason instanceof ApiError) throw reason
    throw new ApiError('无法连接服务。请检查网络、后端进程或部署地址，再重试。', 'network')
  } finally {
    clearTimeout(timer)
    options.signal?.removeEventListener('abort', forwardAbort)
  }
}
