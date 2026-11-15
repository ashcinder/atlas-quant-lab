export interface LabProjectEntry {
  id: string
  name: string
  updated_at: string
}

type ProjectStore = 'entries' | 'archives'

function openLibrary(ownerId: string): Promise<IDBDatabase> {
  if (typeof indexedDB === 'undefined') {
    return Promise.reject(new Error('当前浏览器无法保存 ZIP 项目。'))
  }
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(`trine.lab-projects:${encodeURIComponent(ownerId)}`, 1)
    request.onupgradeneeded = () => {
      request.result.createObjectStore('entries')
      request.result.createObjectStore('archives')
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(new Error('无法打开当前浏览器的 ZIP 项目库。'))
  })
}

async function access<T>(ownerId: string, stores: ProjectStore[], mode: IDBTransactionMode, run: (transaction: IDBTransaction) => IDBRequest<T>): Promise<T> {
  const database = await openLibrary(ownerId)
  try {
    return await new Promise((resolve, reject) => {
      const transaction = database.transaction(stores, mode)
      const request = run(transaction)
      transaction.oncomplete = () => resolve(request.result)
      transaction.onabort = () => reject(new Error(mode === 'readwrite'
        ? '保存 ZIP 项目失败，请检查浏览器的可用存储空间。'
        : '无法读取当前浏览器的 ZIP 项目。'))
    })
  } finally {
    database.close()
  }
}

export function listLabProjects(ownerId: string): Promise<LabProjectEntry[]> {
  if (typeof indexedDB === 'undefined') return Promise.resolve([])
  return access(ownerId, ['entries'], 'readonly', transaction => transaction.objectStore('entries').getAll())
}

export async function readLabProject(ownerId: string, entry: LabProjectEntry): Promise<File> {
  const archive: Blob | undefined = await access(ownerId, ['archives'], 'readonly',
    transaction => transaction.objectStore('archives').get(entry.id))
  if (!archive) throw new Error('找不到此 ZIP 文件，请重新导入。')
  return new File([archive], entry.name, { type: archive.type })
}

export async function saveLabProject(ownerId: string, file: File, id: string = crypto.randomUUID()): Promise<LabProjectEntry> {
  const entry = { id, name: file.name, updated_at: new Date().toISOString() }
  await access(ownerId, ['entries', 'archives'], 'readwrite', transaction => {
    transaction.objectStore('archives').put(file, entry.id)
    return transaction.objectStore('entries').put(entry, entry.id)
  })
  return entry
}
