import runner from './python_project_runner.py?raw'
import { runIsolatedPython } from './portablePython'

const worker = `
  py.FS.writeFile('/atlas-project.zip',new Uint8Array(data.archive));
  await py.runPythonAsync(${JSON.stringify(runner)});
  if (data.action === "inspect") {
    const project=JSON.parse(py.runPython('inspect_project()'));
    self.postMessage({kind:'done',project});
    return;
  }
  py.globals.set('_edits_json',JSON.stringify(data.edits));
  py.runPython('_edits = json.loads(_edits_json)');
  if (data.action === 'export') {
    py.runPython('export_project(_edits)');
    const archive=py.FS.readFile('/atlas-edited.zip').buffer;
    self.postMessage({kind:'done',archive},[archive]);
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

export interface ProjectReport {
  log: string
  summaries: { path: string; data: Record<string, unknown> }[]
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
