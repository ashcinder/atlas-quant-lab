import {afterEach,expect,it,vi} from 'vitest'
import {portableFrameDocument,runPortablePython} from './portablePython'

const bars=Array.from({length:40},(_,i)=>({time:1700000000+i*60,open:10,high:11,low:9,close:10,volume:100}))
afterEach(()=>{vi.useRealTimers();document.querySelectorAll('iframe').forEach(f=>f.remove())})

it('restricts the isolated runtime to local public package assets',()=>{
 const html=portableFrameDocument('https://atlas.test/api/v1/python-runtime/')
 expect(html).toContain("default-src 'none'")
 expect(html).toContain('connect-src https://atlas.test/api/v1/python-runtime/')
 expect(html).toContain('jsglobals:Object.create(null)')
 expect(html.endsWith('</script>')).toBe(true)
 expect(()=>portableFrameDocument('javascript:alert(1)')).toThrow('无效')
 expect(()=>portableFrameDocument('https://atlas.test/api/v1/private/')).toThrow('无效')
})

it('rejects unsolicited frame messages and validates every returned target',async()=>{
 const pending=runPortablePython('def target(c): return 0.5',bars)
 const frame=document.querySelector('iframe')!
 expect(frame.getAttribute('sandbox')).toBe('allow-scripts')
 const send=vi.spyOn(frame.contentWindow!,'postMessage')
 window.dispatchEvent(new MessageEvent('message',{source:window,data:{kind:'ready'}}))
 expect(send).not.toHaveBeenCalled()
 window.dispatchEvent(new MessageEvent('message',{source:frame.contentWindow,data:{kind:'ready'}}))
 const id=send.mock.calls[0][0].id
 const rejected=expect(pending).rejects.toThrow('无效')
 window.dispatchEvent(new MessageEvent('message',{source:frame.contentWindow,data:{kind:'done',id,targets:bars.map(()=>NaN)}}))
 await rejected
})

it.each(['trine-session-lock','atlas-session-expired','pagehide'])('stops Python when %s occurs',async(event)=>{
 const pending=runPortablePython('def target(c):\n    while True: pass',bars)
 const rejected=expect(pending).rejects.toMatchObject({name:'AbortError'})
 window.dispatchEvent(new Event(event))
 await rejected
})

it('does not create an interpreter for an already-cancelled run',async()=>{
 const abort=new AbortController();abort.abort()
 await expect(runPortablePython('def target(c): return 1',bars,{},abort.signal)).rejects.toMatchObject({name:'AbortError'})
 expect(document.querySelector('iframe')).toBeNull()
})
