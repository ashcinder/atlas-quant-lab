export function recognizePortfolioImage(
  bytes: ArrayBuffer,
  signal: AbortSignal,
  onProgress: (message: { status: string; progress: number }) => void,
): Promise<string> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException('识别已取消', 'AbortError')); return }
    // Own the outer worker from the start of model loading. Terminating it also
    // terminates its Tesseract child, including a failed or pending initializer.
    const worker = new Worker(new URL('./portfolio-ocr-worker.ts', import.meta.url), { type: 'module' })
    const finish = () => {
      clearTimeout(timeout)
      signal.removeEventListener('abort', abort)
      worker.terminate()
    }
    const fail = (error: Error) => { finish(); reject(error) }
    const abort = () => fail(new DOMException('识别已取消', 'AbortError'))
    const timeout = setTimeout(() => fail(new Error('OCR 加载或识别超时，请检查网络后重试')), 90_000)
    signal.addEventListener('abort', abort, { once: true })
    worker.onerror = event => { event.preventDefault(); fail(new Error('OCR 引擎启动失败，请重试')) }
    worker.onmessage = event => {
      const message = event.data
      if (message.type === 'progress') onProgress(message)
      else if (message.type === 'result') { finish(); resolve(message.tsv) }
      else if (message.type === 'error') fail(new Error(message.message))
    }
    worker.postMessage(bytes, [bytes])
  })
}
