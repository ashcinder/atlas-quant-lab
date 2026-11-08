// Actual browser contexts and compiled product pages; no source-module imports.
import { chromium } from '../../frontend/node_modules/playwright/index.mjs'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import {createHash} from 'node:crypto'
import { performance } from 'node:perf_hooks'
const [runPath,durationArg='3600',usersArg='50']=process.argv.slice(2)
if(!runPath)throw Error('usage: load.mjs RUN_DIRECTORY [durationSeconds=3600] [users=50]')
const run=JSON.parse(await readFile(runPath+'/run.json','utf8')),fixture=JSON.parse(await readFile(runPath+'/fixture.json','utf8'))
if(!run.synthetic_only||!fixture.synthetic_only||!/^http:\/\/127\.0\.0\.1:\d+$/.test(run.origin)||run.port===18095)throw Error('Refusing non-isolated test target')
const pin=JSON.parse(await readFile(runPath+'/candidate-pin.json','utf8'))
if(!pin.backend_image_matches || !pin.served_dist_matches ||
   pin.image_ids['/'+run.project+'-api-1']!==run.images.api ||
   pin.image_ids['/'+run.project+'-web-1']!==run.images.web) throw Error('Candidate images are not pinned')
const daily=fixture.datasets['BTC-USD:1d']
if(daily.count!==1000) throw Error('Capacity workload requires exactly 1000 daily candles')
const evidence=runPath+'/load-'+Date.now();await mkdir(evidence);await writeFile(runPath+'/latest-load.json',JSON.stringify({evidence}));
const duration=Number(durationArg),users=Number(usersArg)
if(!Number.isFinite(duration)||duration<10||duration>3600||!Number.isInteger(users)||users<1||users>50)throw Error('Invalid bounded load')
const browser=await chromium.launch(),contexts=[],pages=[],metrics={schema:'atlas.e2e-load/v1',run_id:run.run_id,images:run.images,source_fingerprint:pin.source_fingerprint,benchmark_dataset:daily,origin:run.origin,requested_users:users,duration_seconds:duration,started_at:new Date().toISOString(),complete:false,errors:[],groups:[],requests:[],operations:[],client_heap:[]}
let quitting=false,measuring=false
const observed=[]
function recordedRun(result){
 if(typeof result.run_id!=='string'||!result.run_id)throw Error('Saved result has no run ID')
 return {run_id:result.run_id,job_id:result.job_id}
}
const wait=ms=>new Promise(r=>setTimeout(r,ms))
const percentile=(values,q)=>{if(!values.length)return null;const a=values.slice().sort((a,b)=>a-b);return a[Math.min(a.length-1,Math.ceil(a.length*q)-1)]}
async function persist(){await writeFile(evidence+'/progress.json',JSON.stringify({...metrics,requests:undefined,operations:undefined,request_count:metrics.requests.length,operation_count:metrics.operations.length},null,2))}
const timer=setInterval(()=>persist().catch(()=>{}),15000)
try{
 for(let i=0;i<users;i++){
  const rampGroups={5:['market','single','portfolio','ledger','runtime'],10:['market','market','market','single','single','portfolio','research','ledger','runtime','proof'],25:[...Array(9).fill('market'),...Array(5).fill('single'),...Array(2).fill('portfolio'),...Array(2).fill('research'),...Array(4).fill('ledger'),'runtime','runtime','proof']};const group=rampGroups[users]?.[i]??(i<18?'market':i<28?'single':i<32?'portfolio':i<36?'research':i<44?'ledger':i<48?'runtime':'proof')
  const user=users===50?i:group==='runtime'?44+metrics.groups.filter(item=>item.group==='runtime').length:group==='proof'?48:i
  const context=await browser.newContext({baseURL:run.origin,viewport:{width:1280,height:800},locale:'zh-CN'});contexts.push(context)
  await context.addInitScript(()=>{const original=fetch;globalThis.__qaTimes=[];window.fetch=async(...args)=>{const at=performance.now();let status=0;try{const r=await original(...args);status=r.status;return r}finally{globalThis.__qaTimes.push({path:new URL(typeof args[0]==='string'||args[0] instanceof URL?args[0]:args[0].url,location.origin).pathname,ms:performance.now()-at,status,method:args[1]?.method??(args[0] instanceof Request?args[0].method:'GET')})}}})
  context.on('response',response=>{if(!measuring||!response.url().startsWith(run.origin+'/api/'))return;observed.push({user:i,path:new URL(response.url()).pathname,status:response.status()})});context.on('requestfailed',request=>{if(measuring&&!/ERR_ABORTED|NS_BINDING_ABORTED/.test(request.failure()?.errorText??''))metrics.errors.push({user:i,kind:'network',message:request.failure()?.errorText,path:new URL(request.url()).pathname})});
  const page=await context.newPage();page.setDefaultTimeout(10000);pages.push(page);page.on('pageerror',e=>metrics.errors.push({user:i,kind:'pageerror',message:e.message.slice(0,250)}))
  await page.goto('/');await page.getByLabel('登录邮箱').fill(`user${String(user).padStart(2,'0')}@e2e.example.test`);await page.getByLabel('密码',{exact:true}).fill(process.env.ATLAS_E2E_PASSWORD??'Only-E2E-Fixture-2026!');await page.getByRole('button',{name:'登录 Atlas',exact:true}).click();await page.getByRole('button',{name:'运行回测',exact:true}).waitFor()
  metrics.groups.push({user,group})
  if(group==='portfolio')await page.evaluate(()=>{location.hash='#portfolio'})
  if(group==='research'){await page.evaluate(()=>{location.hash='#research'});await page.getByRole('button',{name:'参数测试',exact:true}).click();const choices=page.locator('.strategy-checks input[type=checkbox]');await choices.first().waitFor({state:'attached'});for(let j=0;j<await choices.count();j++)await choices.nth(j).uncheck();await page.getByRole('checkbox',{name:/SMA均线交叉/}).check();await page.getByRole('combobox',{name:'优化策略'}).selectOption('sma_cross');await page.getByLabel(/快速周期逗号/).fill('5,10,15');await page.getByLabel(/慢速周期逗号/).fill('30,45')}
  if(group==='ledger'){await page.evaluate(()=>{location.hash='#/journal/journal'});await page.getByRole('button',{name:/^投资手记/}).click()}
  if(group==='runtime'){
   await page.evaluate(async({release})=>{const previous=await (await fetch('/api/v1/trading/runs')).json();for(const run of previous.filter(r=>r.status!=='stopped'))await fetch('/api/v1/trading/runs/'+run.id+'/stop',{method:'POST'});const post=async(path,data)=>{const r=await fetch('/api/v1'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});if(!r.ok)throw Error('Runtime setup '+path+' '+r.status+': '+await r.text());return r.json()};const s=await (await fetch('/api/v1/strategy-subscriptions')).json();let sub=s.find(x=>x.release_id===release&&x.status==='active');if(!sub)sub=await post('/strategy-subscriptions',{release_id:release});const run=await post('/trading/runs',{release_id:release,subscription_id:sub?.id,market:'CRYPTO',environment:'platform_sim',symbol:'BTC-USD',interval:'1d',initial_cash:'10000'});await post('/trading/runs/'+run.id+'/start',{});globalThis.__qaRun=run.id}, {release:users===50&&i%2?fixture.releases.private:fixture.releases.public})
   await page.evaluate(()=>{location.hash='#/trading'})
  }
  if(group==='proof'){if(!fixture.proof_id)throw Error('Real proof fixture missing');await page.evaluate(id=>{location.hash='#/proof/'+id},fixture.proof_id);await page.getByRole('button',{name:'验证 Proof',exact:true}).waitFor()}
 }
 for(const page of pages)await page.evaluate(()=>globalThis.__qaTimes.splice(0))
 metrics.actual_contexts=contexts.length
 metrics.load_started_at=new Date().toISOString()
 const started=performance.now(),until=started+duration*1000
 measuring=true
 await persist();console.log('READY actual_browser_contexts='+contexts.length)
 await Promise.all(pages.map(async(page,i)=>{
  const group=metrics.groups[i].group;let loops=0
  await wait(i*80)
  while(performance.now()<until&&!quitting){
   const at=performance.now();let ok=true,persisted
   try{
    if(group==='market'){
      await page.getByRole('button',{name:loops%2?'日':'4时',exact:true}).click()
      await page.evaluate(async()=>{for(const path of ['/api/v1/runs','/api/v1/strategy-releases','/api/session']){const r=await fetch(path);if(!r.ok)throw Error('Read '+r.status)}})
    }else if(group==='single'){
      const pending=page.waitForResponse(r=>r.url().endsWith('/api/v1/compute/runs')&&r.request().method()==='POST',{timeout:30000});await page.getByRole('button',{name:'运行回测',exact:true}).click();const r=await pending;if(!r.ok())throw Error('Save '+r.status());const result=await r.json();if(result.compute?.execution_location!=='browser'||result.compute?.proof_status!=='unverified')throw Error('Invalid provenance')
      if(result.equity?.length!==daily.count||!result.compute.dataset_ids?.includes(daily.dataset_id))throw Error('Wrong 1000-candle workload')
      persisted=recordedRun(result)
    }else if(group==='portfolio'){
      const pending=page.waitForResponse(r=>r.url().endsWith('/api/v1/compute/runs')&&r.request().method()==='POST',{timeout:60000});await page.getByRole('button',{name:'运行回测',exact:true}).click();const r=await pending;if(!r.ok())throw Error('Portfolio '+r.status());const result=await r.json();if(result.compute?.execution_location!=='browser'||result.assets?.length<2||result.valuation_currency!=='CNY')throw Error('Invalid portfolio result')
      persisted=recordedRun(result)
    }else if(group==='research'){
      const pending=page.waitForResponse(r=>r.url().endsWith('/api/v1/compute/runs')&&r.request().method()==='POST',{timeout:60000});await page.getByRole('button',{name:'运行稳健性研究',exact:true}).click();const r=await pending;if(!r.ok())throw Error('Research '+r.status());const result=await r.json();if(result.tested_combinations!==6)throw Error('Research expected six combinations, got '+result.tested_combinations)
      if(!result.compute?.dataset_ids?.includes(daily.dataset_id))throw Error('Research used the wrong workload dataset')
      persisted=recordedRun(result)
    }else if(group==='ledger'){
      const card=page.locator('.note-card').filter({has:page.getByRole('heading',{name:'Load bounded note',exact:true})});if(await card.count())await card.getByRole('button',{name:'编辑',exact:true}).click();else await page.getByRole('button',{name:'写手记',exact:true}).click();const dialog=page.getByRole('dialog');await dialog.getByPlaceholder('今天，我想记住什么？').fill('Load bounded note');await dialog.getByPlaceholder('记录你的判断、情绪与下一步。长期来看，思考和数字一样值得保存。').fill('Synthetic bounded stability sample '+loops);const saved=page.waitForResponse(r=>r.url().endsWith('/api/ledger')&&r.request().method()==='PUT');await page.getByRole('button',{name:'保存手记',exact:true}).click();const reply=await saved;if(!reply.ok())throw Error('Ledger UI save failed');await dialog.waitFor({state:'hidden'})
      const body=await reply.json()
      const note=body.state?.journals?.filter(row=>row.title==='Load bounded note')
      if(note?.length!==1||note[0].body!=='Synthetic bounded stability sample '+loops)throw Error('Wrong ledger record')
      persisted={note_id:note[0].id,revision:body.revision,sequence:loops}
    }else if(group==='runtime'){
      await page.evaluate(async()=>{const r=await fetch('/api/v1/trading/runs/'+globalThis.__qaRun);if(!r.ok)throw Error('Runtime '+r.status)})
    }else{
      const verified=page.waitForResponse(r=>r.url().endsWith('/verify')&&r.request().method()==='POST');await page.getByRole('button',{name:'验证 Proof',exact:true}).click();const proof=await verified;if(!proof.ok()||!(await proof.json()).valid)throw Error('Real Proof verification failed');await page.getByRole('heading',{name:'本次密码学验证通过'}).waitFor();const downloading=page.waitForEvent('download');await page.getByRole('link',{name:'下载原始 receipt',exact:true}).click();const download=await downloading;const raw=await readFile(await download.path());if(createHash('sha256').update(raw).digest('hex')!=='6c85feec41f6ad8bd64f3520984a9886ff877df1eac5f41298993157d58bd2d3')throw Error('Receipt download hash mismatch')

    }
   }catch(e){ok=false;metrics.errors.push({user:i,group,message:String(e).slice(0,300)})}
   if(loops%4===0){const heap=await page.evaluate(()=>performance.memory?.usedJSHeapSize??null);metrics.client_heap.push({at:Date.now(),user:i,bytes:heap})}
   metrics.operations.push({at:new Date().toISOString(),user:i,group,ms:performance.now()-at,ok,persisted});loops++
   const collected=await page.evaluate(()=>{const a=globalThis.__qaTimes.splice(0);return a}).catch(()=>[]);metrics.requests.push(...collected.map(x=>({...x,user:i})))
   await wait(Math.min(Math.max(0,until-performance.now()),group==='market'?15000:group==='single'?30000:group==='research'?45000:group==='ledger'?20000:group==='runtime'?15000:45000))
  }
 }))
 for(let i=0;i<pages.length;i++){const rest=await pages[i].evaluate(()=>globalThis.__qaTimes.splice(0)).catch(()=>[]);metrics.requests.push(...rest.map(x=>({...x,user:i})))}
 measuring=false;metrics.observed_responses=observed;metrics.runtime_before_close=[];for(let i=0;i<pages.length;i++)if(metrics.groups[i].group==='runtime'){metrics.runtime_before_close.push({user:metrics.groups[i].user,...await pages[i].evaluate(async()=>{const r=await fetch('/api/v1/trading/runs/'+globalThis.__qaRun);const run=await r.json();return {id:run.id,fills:run.fills?.map(f=>f.id)??[],signals:run.signals?.map(s=>({id:s.id,status:s.status}))??[],status:run.status,last_bar_time:run.last_bar_time}})})};metrics.elapsed_seconds=(performance.now()-started)/1000;metrics.complete=true
 const reads=metrics.requests.filter(r=>r.method==='GET'&&!/market\/files|bundle|receipt/.test(r.path))
 const isSmallWrite=r=>r.method!=='GET'&&(/^\/api\/ledger$/.test(r.path)||/^\/api\/v1\/compute\/runtime\/[^/]+\/(heartbeat|signal)$/.test(r.path))
 const writes=metrics.requests.filter(isSmallWrite)
 const ledgerWrites=writes.filter(r=>r.path==='/api/ledger')
 const upload=metrics.requests.filter(r=>r.method==='POST'&&r.path==='/api/v1/compute/runs')
 const privateTick=metrics.requests.filter(r=>r.method==='POST'&&/^\/api\/v1\/trading\/runs\/[^/]+\/tick$/.test(r.path))
 const proof=metrics.requests.filter(r=>r.method==='POST'&&r.path.endsWith('/verify'))
 metrics.slo={read_p95_ms:percentile(reads.map(r=>r.ms),.95),read_p99_ms:percentile(reads.map(r=>r.ms),.99),small_write_p95_ms:percentile(writes.map(r=>r.ms),.95),ledger_write_p95_ms:percentile(ledgerWrites.map(r=>r.ms),.95),result_upload_p95_ms:percentile(upload.map(r=>r.ms),.95),private_tick_p95_ms:percentile(privateTick.map(r=>r.ms),.95),proof_verify_p95_ms:percentile(proof.map(r=>r.ms),.95),portfolio_p95_ms:percentile(metrics.operations.filter(x=>x.group==='portfolio').map(x=>x.ms),.95),single_p95_ms:percentile(metrics.operations.filter(x=>x.group==='single').map(x=>x.ms),.95),research_p95_ms:percentile(metrics.operations.filter(x=>x.group==='research').map(x=>x.ms),.95),operation_success:metrics.operations.filter(x=>x.ok).length/Math.max(1,metrics.operations.length),request_success:observed.filter(r=>r.status<400).length/Math.max(1,observed.length),unexpected_5xx:observed.filter(r=>r.status>=500).length}
 const everyUserSucceeded=metrics.groups.every((_,index)=>metrics.operations.some(operation=>operation.user===index&&operation.ok));
 metrics.checks={nonempty_reads:reads.length>=users,nonempty_writes:writes.length>0,all_assigned_workloads_observed:everyUserSucceeded,request_success:metrics.slo.request_success>=.995,fifty_real_contexts:users===50&&contexts.length===50,full_hour:duration===3600&&metrics.elapsed_seconds>=3600,read_p95:metrics.slo.read_p95_ms!==null&&metrics.slo.read_p95_ms<=500,read_p99:metrics.slo.read_p99_ms<=1500,write_p95:metrics.slo.small_write_p95_ms<=1500&&(ledgerWrites.length===0||metrics.slo.ledger_write_p95_ms<=1500),single_p95:!metrics.groups.some(g=>g.group==='single')||(metrics.slo.single_p95_ms!==null&&metrics.slo.single_p95_ms<=5000),research_p95:!metrics.groups.some(g=>g.group==='research')||(metrics.slo.research_p95_ms!==null&&metrics.slo.research_p95_ms<=15000),success_rate:metrics.slo.operation_success>=.995,no_5xx:metrics.slo.unexpected_5xx===0,runtime_heartbeats:observed.filter(r=>/\/compute\/runtime\/.+\/heartbeat$/.test(r.path)&&r.status===200).length>=metrics.groups.filter(g=>g.group==='runtime').length*Math.floor(duration/20),no_browser_error:metrics.errors.length===0}
 metrics.diagnostic_pass=metrics.complete&&metrics.errors.length===0&&Object.entries(metrics.checks).filter(([key])=>!['fifty_real_contexts','full_hour'].includes(key)).every(([,value])=>value);metrics.success=Object.values(metrics.checks).every(Boolean)
}catch(error){metrics.failure=String(error);metrics.success=false;process.exitCode=1}
finally{quitting=true;clearInterval(timer);for(const c of contexts)await c.close().catch(()=>{});await browser.close();metrics.finished_at=new Date().toISOString();await writeFile(evidence+'/result.json',JSON.stringify(metrics,null,2));await persist();console.log(JSON.stringify({complete:metrics.complete,success:metrics.success,slo:metrics.slo,failure:metrics.failure}));if(!(duration===3600?metrics.success:metrics.diagnostic_pass))process.exitCode=1}
