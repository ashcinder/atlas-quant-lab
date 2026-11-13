import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { StrategyPanel } from './StrategyPanel'
afterEach(cleanup)
it('retains ordinary strategy parameters and removes the comparison panel',()=>{
  const noop=vi.fn()
  render(<StrategyPanel asset={null} strategies={[{id:'sma_cross',name:'SMA',category:'趋势',description:'均线',suitable_for:'趋势',risk_level:'中',mode:'single',parameters:[{key:'fast',label:'快速周期',kind:'integer',default:5,minimum:1,maximum:100,step:1,options:null,help:null}]}]} selectedId="sma_cross" values={{fast:5}} capital={10000} commission={.001} slippage={0} spread={0} maxPosition={.5} maxParticipation={.01} stopLoss={0} takeProfit={0} onStrategy={noop} onValue={noop} onCapital={noop} onCommission={noop} onSlippage={noop} onSpread={noop} onMaxPosition={noop} onMaxParticipation={noop} onStopLoss={noop} onTakeProfit={noop} onReset={noop} fundamentals={null} fundamentalsLoading={false} fundamentalsError={null} onFundamentals={noop} />)
  expect(screen.queryByText('比较参数')).toBeNull()
  expect(screen.queryByText('开始比较')).toBeNull()
  expect(screen.getByText('资金与成本')).toBeTruthy()
  expect(screen.getByText('快速周期')).toBeTruthy()
})
