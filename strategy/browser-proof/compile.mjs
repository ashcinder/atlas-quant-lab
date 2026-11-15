// Run with: npm --prefix frontend run build:browser-proof
import { createRequire } from 'node:module'
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(new URL('../../frontend/package.json', import.meta.url))
const { compile, createFileManager } = require('@noir-lang/noir_wasm')
const project = fileURLToPath(new URL('.', import.meta.url))
const outputDir = new URL('../../frontend/src/browser-proof/', import.meta.url)

async function build(path, file) {
  const { program: { abi, bytecode, noir_version } } = await compile(createFileManager(path))
  const output = new URL(file, outputDir)
  const content = JSON.stringify({ abi, bytecode, noir_version }) + '\n'
  const previous = await readFile(output, 'utf8').catch(error => {
    if (error.code !== 'ENOENT') throw error
  })
  if (previous !== content) await writeFile(output, content)
}

// Preserve the original circuit and its v1 proof format.
await build(project, 'sma-circuit.json')

const source = await readFile(join(project, 'src/main.nr'), 'utf8')
const baseCount = 'global BARS: u32 = 32;'
if (!source.includes(baseCount)) throw new Error('Base circuit length has changed.')

const temp = await mkdtemp(join(tmpdir(), 'atlas-browser-proof-'))
try {
  await mkdir(join(temp, 'src'))
  await writeFile(join(temp, 'Nargo.toml'), await readFile(join(project, 'Nargo.toml')))
  for (const count of [64, 128]) {
    await writeFile(join(temp, 'src/main.nr'), source.replace(baseCount, `global BARS: u32 = ${count};`))
    await build(temp, `sma-circuit-${count}.json`)
  }
} finally {
  await rm(temp, { recursive: true, force: true })
}
