import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'
import { createReadStream, readFileSync, statSync } from 'node:fs'
import type { Plugin } from 'vite'

const proofRuntime = 'assets/browser-proof-runtime'
const bbFiles = ['index.js', 'barretenberg.js', 'barretenberg-threads.js', 'main.worker.js', 'thread.worker.js',
  'index.js.LICENSE.txt', 'main.worker.js.LICENSE.txt', 'thread.worker.js.LICENSE.txt']
const proofAssets: Record<string, string> = {
  ...Object.fromEntries(bbFiles.map(name => [name, `@aztec/bb.js/dest/browser/${name}`])),
  'acvm_js_bg.wasm': '@noir-lang/acvm_js/web/acvm_js_bg.wasm',
  'noirc_abi_wasm_bg.wasm': '@noir-lang/noirc_abi/web/noirc_abi_wasm_bg.wasm',
}
const moduleFile = (path: string) => fileURLToPath(new URL(`./node_modules/${path}`, import.meta.url))
const browserProofRuntime: Plugin = {
  name: 'browser-proof-runtime',
  configureServer(server) {
    const prefix = `${server.config.base}${proofRuntime}/`
    server.middlewares.use((req, res, next) => {
      const url = req.url?.split('?')[0] ?? ''
      const name = url.slice(prefix.length)
      if (!url.startsWith(prefix) || !Object.hasOwn(proofAssets, name)) return next()
      const path = moduleFile(proofAssets[name])
      res.setHeader('Content-Type', name.endsWith('.wasm') ? 'application/wasm' : name.endsWith('.txt') ? 'text/plain' : 'text/javascript')
      res.setHeader('Content-Length', String(statSync(path).size))
      createReadStream(path).pipe(res)
    })
  },
  generateBundle() {
    for (const [name, path] of Object.entries(proofAssets)) {
      this.emitFile({ type: 'asset', fileName: `${proofRuntime}/${name}`, source: readFileSync(moduleFile(path)) })
    }
  },
}

export default defineConfig({
  plugins: [react(), browserProofRuntime],
  worker: { format: 'es' },
  optimizeDeps: { include: ['@noir-lang/noir_js'] },
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  test: {
    include: ['src/**/*.test.{ts,tsx}'],
    environment: 'jsdom',
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
