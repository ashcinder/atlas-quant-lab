import { Noir, abi, acvm } from '@noir-lang/noir_js'
import type { CompiledCircuit } from '@noir-lang/noir_js'
import { assertMarketBinding, marketHashFields, parseProof } from './protocol'
import type { BrowserProof, ProofJob, ProofProfile } from './protocol'

const circuits: Record<ProofProfile, () => Promise<{ default: unknown }>> = {
  'atlas-browser-sma-v1': () => import('./sma-circuit.json'),
  'atlas-browser-sma-64-v1': () => import('./sma-circuit-64.json'),
  'atlas-browser-sma-128-v1': () => import('./sma-circuit-128.json'),
}
const runtime = new URL(`${import.meta.env.BASE_URL}assets/browser-proof-runtime/`, self.location.origin)
const options = { keccakZK: true } // The plain UltraHonk mode does not provide witness hiding.

self.onmessage = async ({ data: job }: MessageEvent<ProofJob>) => {
  let backend: InstanceType<typeof import('@aztec/bb.js')['UltraHonkBackend']> | undefined
  try {
    const [{ UltraHonkBackend }, { default: circuitJson }] = await Promise.all([
      import(/* @vite-ignore */ new URL('index.js', runtime).href) as Promise<typeof import('@aztec/bb.js')>,
      circuits[job.market.profile](),
    ])
    const circuit = circuitJson as CompiledCircuit
    backend = new UltraHonkBackend(circuit.bytecode, { threads: 1 })
    let bundle: BrowserProof
    if (job.mode === 'prove') {
      await Promise.all([
        abi.default({ module_or_path: new URL('noirc_abi_wasm_bg.wasm', runtime) }),
        acvm.default({ module_or_path: new URL('acvm_js_bg.wasm', runtime) }),
      ])
      // 31 random bytes fit in the scalar field without reduction.
      let salt: Uint8Array
      do { salt = crypto.getRandomValues(new Uint8Array(31)) } while (salt.every(byte => byte === 0))
      const { witness } = await new Noir(circuit).execute({
        market_hash: marketHashFields(job.market.hash),
        opens: job.market.opens, closes: job.market.closes, fast: job.fast, slow: job.slow,
        salt: `0x${Array.from(salt, byte => byte.toString(16).padStart(2, '0')).join('')}`,
      })
      const { proof, publicInputs } = await backend.generateProof(witness, options)
      bundle = parseProof({
        profile: job.market.profile, dataset_id: job.market.datasetId, window_end: job.market.end, market_data_hash: job.market.hash,
        public_inputs: publicInputs,
        proof: btoa(Array.from(proof, byte => String.fromCharCode(byte)).join('')),
      })
    } else {
      bundle = parseProof(job.bundle)
    }
    assertMarketBinding(bundle, job.market)
    const proof = Uint8Array.from(atob(bundle.proof), char => char.charCodeAt(0))
    if (!await backend.verifyProof({ proof, publicInputs: bundle.public_inputs }, options)) {
      throw new Error('密码学验证失败，证明或公开输出可能已被修改。')
    }
    self.postMessage({ bundle })
  } catch (error) {
    self.postMessage({ error: error instanceof Error ? error.message : '浏览器证明运行失败。' })
  } finally {
    await backend?.destroy()
  }
}
