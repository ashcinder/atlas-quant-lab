import { createWorker, PSM } from 'tesseract.js'
import workerPath from 'tesseract.js/dist/worker.min.js?url'
import corePath from 'tesseract.js-core/tesseract-core-lstm.wasm.js?url'

self.onmessage = async (event: MessageEvent<ArrayBuffer>) => {
  let worker: Awaited<ReturnType<typeof createWorker>> | undefined
  let failLoading: (reason: Error) => void = () => undefined
  const loadingError = new Promise<never>((_, reject) => { failLoading = reject })
  try {
    worker = await Promise.race([
      createWorker('eng', 1, {
        workerPath, corePath, workerBlobURL: false,
        // Tesseract reports language-load failures through this callback before
        // returning a worker. Forward it so the owning page can terminate us.
        errorHandler: () => failLoading(new Error('OCR 模型加载或识别失败，请重试')),
        logger: message => self.postMessage({ type: 'progress', ...message }),
      }),
      loadingError,
    ])
    await worker.setParameters({ tessedit_pageseg_mode: PSM.SPARSE_TEXT, preserve_interword_spaces: '1' })
    const result = await worker.recognize(new Blob([event.data], { type: 'image/png' }), {}, { text: true, tsv: true })
    self.postMessage({ type: 'result', tsv: result.data.tsv ?? '' })
  } catch {
    self.postMessage({ type: 'error', message: 'OCR 模型加载或识别失败，请检查网络后重试' })
  } finally {
    await worker?.terminate()
  }
}
