import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from './api'
import { request } from './request'
import { computePayload } from './compute/client'

vi.mock('./request',()=>({request:vi.fn()}))
beforeEach(()=>vi.resetAllMocks())
afterEach(()=>vi.useRealTimers())

it('preserves the requested execution model through browser payload filtering',()=>{
 expect(computePayload({symbol:'300750.SZ',execution_model:'unified',api_key:'discard'})).toEqual({symbol:'300750.SZ',execution_model:'unified'})
})

it('uses the complete published range for empty native HF dates and keeps the shared contract choice',async()=>{
 vi.mocked(request).mockResolvedValueOnce({status:'ready',start:1528680600,end:1786069200}).mockResolvedValueOnce({run_id:'actual-native'})
 await api.runBacktest({backtest_engine:'vnpy',execution_model:'unified',symbol:'300750.SZ',asset_class:'equity',data_source:'huggingface',interval:'1m',adjustment:'raw'})
 const call=vi.mocked(request).mock.calls[1]
 expect(call[0]).toBe('/backtests/native')
 const body=JSON.parse(call[1]?.body as string)
 expect(body.execution_model).toBe('unified')
 expect(body.start).toBe(new Date(1528680600*1000).toISOString())
 expect(body.end).toBe(new Date(1786069200*1000).toISOString())
 expect(call[2]).toBe(660000)
})

it('submits crypto minute backtests once and polls until the native report is ready', async () => {
  vi.useFakeTimers()
  vi.mocked(request).mockResolvedValueOnce({ job_id: 'job' })
    .mockResolvedValueOnce({ status: 'running' })
    .mockResolvedValueOnce({ status: 'completed', result: { run_id: 'native-minute' } })
  const run = api.runBacktest({ backtest_engine: 'vnpy', symbol: 'BTC-USD', asset_class: 'crypto', interval: '1m' })
  await vi.advanceTimersByTimeAsync(6000)
  await expect(run).resolves.toEqual({ run_id: 'native-minute' })
  expect(vi.mocked(request).mock.calls.map(([path]) => path)).toEqual([
    '/backtests/native-jobs', '/backtests/native-jobs/job', '/backtests/native-jobs/job',
  ])
})
