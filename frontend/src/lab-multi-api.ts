import { labOwnerHeaders } from './lab-strategy-types'
import type { LabDraft, LabMultiCoverage, LabMultiDraft, LabMultiEngine, LabMultiJob, LabMultiSettings, LabReportExport, LabReportPage, LabReportQuery, LabReportTable } from './lab-strategy-types'
import { ApiError, request } from './request'
import type { StrategyRelease } from './types'

export interface LabMultiExample { id: string; name: string }
export interface LabMultiCapabilities {
  available: boolean
  reason: string | null
  engine_id?: LabMultiEngine
  engine_version?: string
  can_release?: boolean
  matching_type?: string
  benchmarks?: Array<{ symbol: string; name: string; start: string; end: string }>
}

const reportQuery = (query: LabReportQuery = {}) => new URLSearchParams(
  Object.entries(query).filter(([, value]) => value !== undefined && value !== '').map(([key, value]) => [key, String(value)]),
).toString()

async function downloadReport(owner: string, id: string, table: LabReportExport, query: LabReportQuery = {}, signal?: AbortSignal) {
  const controller = new AbortController()
  const abort = () => controller.abort(signal?.reason)
  if (signal?.aborted) abort()
  else signal?.addEventListener('abort', abort, { once: true })
  const timer = globalThis.setTimeout(() => controller.abort(), 120_000)
  try {
    const root = (import.meta.env.VITE_API_ROOT ?? '/api/v1').replace(/\/$/, '')
    const params = new URLSearchParams(reportQuery(query))
    params.set('table', table)
    const response = await fetch(`${root}/lab-multi/jobs/${encodeURIComponent(id)}/export?${params}`, {
      credentials: 'include', headers: labOwnerHeaders(owner), signal: controller.signal,
    })
    if (!response.ok) {
      if (response.status === 401) window.dispatchEvent(new Event('atlas-session-expired'))
      const body: unknown = await response.json().catch(() => null)
      const detail = body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string' ? body.detail : null
      throw new ApiError(detail ?? `无法下载回测报告（HTTP ${response.status}）。`, 'http', response.status)
    }
    const filename = response.headers.get('Content-Disposition')?.match(/filename="([a-zA-Z0-9._-]+)"/)?.[1]
      ?? `atlas-report-${id}-${table}.${table === 'snapshot' ? 'json' : table === 'logs' ? 'txt' : 'csv'}`
    return { blob: await response.blob(), filename }
  } catch (reason) {
    if (signal?.aborted) throw signal.reason ?? new DOMException('请求已取消', 'AbortError')
    if (reason instanceof ApiError) throw reason
    throw new ApiError(controller.signal.aborted ? '报告下载超时，请缩小筛选范围后重试。' : '无法下载报告，请检查服务连接。', controller.signal.aborted ? 'timeout' : 'network')
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', abort)
  }
}

export function labMultiRequest<T>(owner: string, path: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers)
  if (owner) headers.set('X-Atlas-Lab-Owner', labOwnerHeaders(owner)['X-Atlas-Lab-Owner'])
  return request<T>(`/lab-multi/${path}`, { ...options, headers })
}

export const labMultiApi = {
  capabilities: (owner: string, signal?: AbortSignal, engine: LabMultiEngine = 'atlas_portfolio') =>
    labMultiRequest<LabMultiCapabilities>(owner, `capabilities?engine_id=${engine}`, { signal }),
  examples: (owner: string, signal?: AbortSignal) => labMultiRequest<LabMultiExample[]>(owner, 'examples', { signal }),
  example: (owner: string, id: string) => labMultiRequest<LabMultiDraft>(owner, `examples/${encodeURIComponent(id)}`),
  fromRelease: (owner: string, id: string, signal?: AbortSignal) => labMultiRequest<LabDraft>(owner, `releases/${encodeURIComponent(id)}/draft`, { signal }),
  inspect: (owner: string, package_b64: string) => labMultiRequest<{ name: string; source: string; settings?: Partial<LabMultiSettings> }>(owner, 'inspect', {
    method: 'POST', body: JSON.stringify({ package_b64 }),
  }),
  preflight: (owner: string, settings: LabMultiSettings, signal?: AbortSignal) => labMultiRequest<LabMultiCoverage>(owner, 'preflight', {
    method: 'POST', body: JSON.stringify({ settings }), signal,
  }),
  jobs: (owner: string, id: string, signal?: AbortSignal) => labMultiRequest<LabMultiJob[]>(owner, `jobs?strategy_id=${encodeURIComponent(id)}`, { signal }),
  job: (owner: string, id: string, signal?: AbortSignal) => labMultiRequest<LabMultiJob>(owner, `jobs/${encodeURIComponent(id)}`, { signal }),
  start: (owner: string, strategy_id: string, expected_revision: number, request_id: string, signal?: AbortSignal) =>
    labMultiRequest<LabMultiJob>(owner, 'jobs', { method: 'POST', body: JSON.stringify({ strategy_id, expected_revision, request_id }), signal }),
  cancel: (owner: string, id: string, signal?: AbortSignal) => labMultiRequest<LabMultiJob>(owner, `jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST', signal }),
  reportRows: (owner: string, id: string, table: LabReportTable, query: LabReportQuery = {}, signal?: AbortSignal) =>
    labMultiRequest<LabReportPage>(owner, `jobs/${encodeURIComponent(id)}/report/${table}?${reportQuery(query)}`, { signal }),
  reportSource: (owner: string, id: string, signal?: AbortSignal) =>
    labMultiRequest<{ source: string; source_sha256: string; revision: number }>(owner, `jobs/${encodeURIComponent(id)}/source`, { signal }),
  downloadReport,
  release: (owner: string, strategy_id: string, expected_revision: number, job_id: string) => labMultiRequest<StrategyRelease>(owner, 'releases', {
    method: 'POST', body: JSON.stringify({ strategy_id, expected_revision, job_id }),
  }),
}

export async function encodeLabPackage(file: File) {
  if (!file.size || file.size > 2_250_000) throw new Error('策略包必须是 2.25 MB 以内的 ZIP 文件。')
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 16_384) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 16_384))
  }
  return btoa(binary)
}
