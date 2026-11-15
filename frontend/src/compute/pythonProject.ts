import runner from './python_project_runner.py?raw'
import bootstrap from './portable_runner.py?raw'
import type { Bar } from '../types'
import { runIsolatedPython } from './portablePython'

const worker = `
  py.FS.writeFile('/atlas-project.zip',new Uint8Array(data.archive));
  await py.runPythonAsync(${JSON.stringify(runner)});
  if (data.action === "inspect") {
    const project=JSON.parse(py.runPython('inspect_project()'));
    self.postMessage({kind:'done',project});
    return;
  }
  if (data.action === 'preview') {
    py.globals.set('_preview_path',data.path);
    const preview=JSON.parse(py.runPython('preview_project_file(_preview_path)'));
    self.postMessage({kind:'done',preview});
    return;
  }
  py.globals.set('_edits_json',JSON.stringify(data.edits));
  py.runPython('_edits = json.loads(_edits_json)');
  if (data.action === 'export' || data.action === 'save') {
    py.runPython('export_project(_edits)');
    const project=data.action === 'save' ? JSON.parse(py.runPython('inspect_project("/atlas-edited.zip")')) : undefined;
    const archive=py.FS.readFile('/atlas-edited.zip').buffer;
    self.postMessage({kind:'done',archive,project},[archive]);
    return;
  }
  py.globals.set('_entry',data.entry);
  const staged=JSON.parse(py.runPython('stage_project(_entry, _edits)'));
  const bundled={
    numpy:'numpy',pandas:'pandas',scipy:'scipy',sklearn:'scikit-learn',
    joblib:'joblib',threadpoolctl:'threadpoolctl',tzdata:'tzdata'
  };
  const packages=new Set(['tzdata']);
  for (const name of staged.modules) {
    if (Object.hasOwn(bundled,name)) packages.add(bundled[name]);
  }
  await py.loadPackage([...packages]);
  py.globals.set('_root',staged.root);
  if (data.action === 'targets') {
    await py.runPythonAsync(${JSON.stringify(bootstrap)});
    py.globals.set('_bars',JSON.stringify(data.bars));
    py.globals.set('_params',JSON.stringify(data.params || {}));
    const targets=JSON.parse(await py.runPythonAsync('run_namespace(execute_project(_entry, _root, True), _bars, _params)'));
    self.postMessage({kind:'done',targets});
    return;
  }
  await py.runPythonAsync('_log = execute_project(_entry, _root)');
  const report=JSON.parse(py.runPython('collect_report(_root, _log)'));
  const archive=py.FS.readFile('/atlas-report.zip').buffer;
  self.postMessage({kind:'done',report,archive},[archive]);
`

export interface PythonProject {
  scripts: string[]
  files: { path: string; size: number }[]
  sources: Record<string, string>
  root: string
}

export type ImportedPythonProject = PythonProject & { file: File; libraryId?: string }

export type ProjectFilePreview = { kind: 'text'; text: string; truncated: boolean } | { kind: 'binary' | 'encoding' }

export interface ProjectReportSummary {
  path: string
  data: Record<string, unknown>
  equity?: Record<string, string | number>[]
  trades?: Record<string, string | number>[]
}

export interface ProjectReport {
  log: string
  summaries: ProjectReportSummary[]
  warnings: string[]
  archive: Blob
}

async function readArchive(file: File, signal: AbortSignal) {
  if (!file.name.toLowerCase().endsWith('.zip') || file.size === 0) {
    throw new Error('请选择包含 Python 源码的 ZIP 项目')
  }
  if (file.size > 64 * 1024 * 1024) throw new Error('ZIP 不能超过 64 MiB')
  signal.throwIfAborted()
  return file.arrayBuffer()
}

export async function inspectPythonProject(file: File, signal: AbortSignal) {
  const archive = await readArchive(file, signal)
  return runIsolatedPython({ archive, action: 'inspect' }, result => result.project as PythonProject, signal, worker)
}

export async function runPythonProject(file: File, entry: string, edits: Record<string, string>, signal: AbortSignal) {
  const archive = await readArchive(file, signal)
  return runIsolatedPython({ archive, entry, edits, action: 'run' }, result => {
    const report = result.report as Omit<ProjectReport, 'archive'>
    if (!(result.archive instanceof ArrayBuffer) || !report) throw new Error('项目报告格式无效')
    return { ...report, archive: new Blob([result.archive], { type: 'application/zip' }) }
  }, signal, worker)
}

export async function exportPythonProject(file: File, edits: Record<string, string>, signal: AbortSignal) {
  const archive = await readArchive(file, signal)
  return runIsolatedPython({ archive, edits, action: 'export' }, result => {
    if (!(result.archive instanceof ArrayBuffer)) throw new Error('项目 ZIP 格式无效')
    return new Blob([result.archive], { type: 'application/zip' })
  }, signal, worker)
}


export async function savePythonProject(file: File, edits: Record<string, string>, signal: AbortSignal): Promise<ImportedPythonProject> {
  const archive = await readArchive(file, signal)
  return runIsolatedPython({ archive, edits, action: 'save' }, result => {
    if (!(result.archive instanceof ArrayBuffer) || !result.project) throw new Error('项目 ZIP 格式无效')
    return {
      ...(result.project as PythonProject),
      file: new File([result.archive], file.name, { type: 'application/zip' }),
    }
  }, signal, worker)
}

export async function previewPythonProjectFile(file: File, path: string, signal: AbortSignal) {
  const archive = await readArchive(file, signal)
  return runIsolatedPython({ archive, path, action: 'preview' }, result => result.preview as ProjectFilePreview, signal, worker)
}

export async function projectTargets(file: File, entry: string, edits: Record<string, string>, bars: Bar[], params: Record<string, unknown>, signal: AbortSignal): Promise<number[]> {
  const archive = await readArchive(file, signal)
  return runIsolatedPython({ archive, entry, edits, bars, params, action: 'targets' }, result => {
    const targets = result.targets
    if (!Array.isArray(targets) || targets.length !== bars.length || targets.some(value => typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1)) throw new Error('项目目标仓位序列无效')
    return targets as number[]
  }, signal, worker)
}

export async function prepareProjectPlan(file: File, entry: string, edits: Record<string, string>, bars: Bar[], datasetId: string, signal: AbortSignal) {
  const snapshot = Object.keys(edits).length ? await exportPythonProject(file, edits, signal) : file
  const hex = (bytes: ArrayBuffer) => Array.from(new Uint8Array(bytes), value => value.toString(16).padStart(2, '0')).join('')
  const fingerprint = hex(await crypto.subtle.digest('SHA-256', await snapshot.arrayBuffer()))
  const source = '# Trine Python project SHA-256 ' + fingerprint + '\n# entry ' + entry
  const sourceHash = hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(source)))
  const targets = await projectTargets(file, entry, edits, bars, {}, signal)
  return {
    source,
    plan: { dataset_id: datasetId, source_sha256: sourceHash, name: file.name.replace(/\.zip$/i, '').slice(0, 80),
      start: bars[0].time, end: bars.at(-1)!.time, targets },
  }
}
