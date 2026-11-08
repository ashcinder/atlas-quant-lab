import {render,screen,fireEvent,waitFor} from '@testing-library/react'
import {expect,it,vi} from 'vitest'
import {TemplateStrategyWorkspace} from './TemplateStrategyWorkspace'
import {api} from '../api'
import {defaultPipeline} from './executionPipeline'
vi.mock('../api',()=>({api:{runBacktest:vi.fn()}}))
vi.mock('./ParameterSweep',()=>({ParameterSweep:()=>null}))
vi.mock('./PublishRuntimeStrategy',()=>({PublishRuntimeStrategy:()=>null}))
it('accepts catalog defaults when the suggested increment is not aligned to the minimum',async()=>{
 const onCustomResult=vi.fn();vi.mocked(api.runBacktest).mockResolvedValue({run_id:'test'} as never)
 render(<TemplateStrategyWorkspace asset={{symbol:'BTC-USD',asset_class:'crypto'} as never} strategies={[{id:'scheduled_dca',name:'定额',category:'资金',description:'',parameters:[{key:'amount',label:'金额',kind:'number',default:1000,minimum:1,maximum:10000000,step:100},{key:'aligned',label:'对齐步长',kind:'number',default:.05,minimum:0,maximum:1,step:.005}]} as never]} interval="1d" source="auto" initialCapital={100000} commission={.001} slippage={.0005} spread={0} maxPosition={.95} maxParticipation={.01} onLoading={()=>{}} onError={()=>{}} onCustomResult={onCustomResult} pipeline={defaultPipeline()} storageKey="test-template-validity" />)
 expect((screen.getByLabelText('对齐步长') as HTMLInputElement).step).toBe('0.005')
 expect((screen.getByLabelText('金额') as HTMLInputElement).checkValidity()).toBe(true)
 fireEvent.submit(screen.getByRole('button',{name:'运行模板回测'}).closest('form')!)
 await waitFor(()=>expect(onCustomResult).toHaveBeenCalled())
})
