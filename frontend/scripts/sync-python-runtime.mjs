import {readFile,writeFile,mkdir,copyFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import {fileURLToPath} from 'node:url'
import {join} from 'node:path'
const root=fileURLToPath(new URL('../',import.meta.url)),source=join(root,'node_modules/pyodide'),dest=join(root,'public/python-runtime')
await mkdir(dest,{recursive:true})
for(const name of ['pyodide.js','pyodide.mjs','pyodide.asm.mjs','pyodide.asm.wasm','pyodide-lock.json','python_stdlib.zip'])await copyFile(join(source,name),join(dest,name))
const lock=JSON.parse(await readFile(join(source,'pyodide-lock.json'),'utf8')),seen=new Set()
const hash=bytes=>createHash('sha256').update(bytes).digest('hex')
async function obtain(name){
 if(seen.has(name))return;seen.add(name)
 const info=lock.packages[name];if(!info)throw new Error(`Unsupported Pyodide package ${name}`)
 for(const dependency of info.depends)await obtain(dependency)
 const path=join(dest,info.file_name)
 try{if(hash(await readFile(path))===info.sha256)return}catch{}
 const response=await fetch(`https://cdn.jsdelivr.net/pyodide/v314.0.7/full/${info.file_name}`)
 if(!response.ok)throw new Error(`Runtime package ${name}: HTTP ${response.status}`)
 const bytes=Buffer.from(await response.arrayBuffer())
 if(hash(bytes)!==info.sha256)throw new Error(`Runtime hash mismatch: ${name}`)
 await writeFile(path,bytes);process.stdout.write(`Python package ready: ${name}\n`)
}
for(const name of ['numpy','pandas','scikit-learn','tzdata',...process.argv.slice(2)])await obtain(name)
