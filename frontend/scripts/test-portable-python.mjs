import {loadPyodide} from 'pyodide'
import {readFile,writeFile,mkdir} from 'node:fs/promises'
import {fileURLToPath} from 'node:url'
import {createHash} from 'node:crypto'
const root=fileURLToPath(new URL('../',import.meta.url))
const runtime=await loadPyodide({indexURL:root+'public/python-runtime/',jsglobals:Object.create(null)})
const bootstrap=await readFile(root+'src/compute/portable_runner.py','utf8')
await runtime.runPythonAsync(bootstrap)
const payload=JSON.parse(await readFile(process.argv[2],'utf8'))
const source=await readFile(process.argv[3],'utf8')
await runtime.loadPackagesFromImports(source)
runtime.globals.set('_source',source)
runtime.globals.set('_bars',JSON.stringify(payload.bars))
const start=performance.now()
const targets=JSON.parse(await runtime.runPythonAsync('run_strategy(_source, _bars)'))
const result={dataset_id:payload.dataset_id,source_sha256:createHash('sha256').update(source).digest('hex'),
 name:process.argv[4]??'自由Python策略',start:payload.bars[0].time,end:payload.bars.at(-1).time,targets}
await writeFile(process.argv[2]+'.plan.json',JSON.stringify(result))
process.stdout.write(JSON.stringify({count:targets.length,elapsed_seconds:(performance.now()-start)/1000,min:targets.reduce((a,b)=>Math.min(a,b),1),max:targets.reduce((a,b)=>Math.max(a,b),0)})+'\n')
