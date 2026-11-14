"""Load and run an offline project inside the browser's disposable Python filesystem."""

import ast
import contextlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import runpy
import shutil
import stat
import sys
import zipfile


PROJECT = Path("/atlas-project")
OUTPUT = Path("/atlas-output")
SOURCE_LIMIT = 8 * 1024 * 1024
UNPACK_LIMIT = 256 * 1024 * 1024
REPORT_LIMIT = 16 * 1024 * 1024
LOG_LIMIT = 64_000


def project_files(archive):
    entries = archive.infolist()
    if len(entries) > 4000 or sum(info.file_size for info in entries) > UNPACK_LIMIT:
        raise ValueError("项目最多 4000 个条目，解压后不能超过 256 MiB")
    files = {}
    seen = set()
    for info in entries:
        name = info.orig_filename.rstrip("/")
        parts = name.split("/")
        mode = stat.S_IFMT(info.external_attr >> 16)
        if ("\x00" in name or "\\" in name or ":" in name or len(name) > 500
                or any(part in ("", ".", "..") for part in parts)
                or mode not in (0, stat.S_IFDIR, stat.S_IFREG) or info.flag_bits & 1):
            raise ValueError(f"ZIP 含不受支持的路径、链接或加密条目：{name}")
        if name in seen:
            raise ValueError(f"ZIP 中有重名条目：{name}")
        seen.add(name)
        if info.is_dir() or any(part in ("__MACOSX", "__pycache__", ".DS_Store") for part in parts):
            continue
        files[name] = info
    if any(str(parent) in files for name in seen for parent in PurePosixPath(name).parents):
        raise ValueError("ZIP 中的文件名与目录冲突")
    scripts = sorted(name for name in files if name.endswith(".py") and PurePosixPath(name).name != "__init__.py")
    if not scripts:
        raise ValueError("项目里没有可选择的 Python 脚本")
    if sum(files[name].file_size for name in files if name.endswith(".py")) > SOURCE_LIMIT:
        raise ValueError("项目 Python 源码合计不能超过 8 MiB")
    first_parts = {name.split("/", 1)[0] for name in files}
    root = next(iter(first_parts)) if len(first_parts) == 1 and all("/" in name for name in files) else ""
    return files, scripts, root


def inspect_project():
    with zipfile.ZipFile("/atlas-project.zip") as archive:
        files, scripts, root = project_files(archive)
        sources = {}
        for name, info in files.items():
            if name.endswith(".py"):
                try:
                    sources[name] = archive.read(info).decode("utf-8-sig")
                except UnicodeDecodeError:
                    pass
    return json.dumps({
        "scripts": scripts,
        "files": [{"path": name, "size": info.file_size} for name, info in sorted(files.items())],
        "sources": sources,
        "root": root,
    }, ensure_ascii=False)


def preview_project_file(path):
    limit = 512 * 1024
    with zipfile.ZipFile("/atlas-project.zip") as archive:
        files, _, _ = project_files(archive)
        info = files.get(path)
        if info is None:
            raise ValueError("项目中没有此文件")
        with archive.open(info) as stream:
            data = stream.read(limit + 1)
    if b"\x00" in data:
        return json.dumps({"kind": "binary"})
    truncated = len(data) > limit
    if truncated:
        data = data[:limit]
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        if truncated and error.reason == "unexpected end of data" and error.end == len(data):
            text = data[:error.start].decode("utf-8-sig")
        else:
            return json.dumps({"kind": "encoding"})
    return json.dumps({"kind": "text", "text": text, "truncated": truncated}, ensure_ascii=False)


def updated_files(archive, changes):
    files, _, root = project_files(archive)
    prefix = f"{root}/" if root else ""
    edits = {}
    for name, source in changes.items():
        parts = name.split("/")
        if (not name.startswith(prefix) or not name.endswith(".py") or len(name) > 500
                or any(part in ("", ".", "..", "__MACOSX", "__pycache__", ".DS_Store") for part in parts)
                or any(char in name for char in ("\x00", "\\", ":"))):
            raise ValueError(f"Python 文件路径无效：{name}")
        edits[name] = source.encode("utf-8")
    names = files.keys() | edits.keys()
    if len(names) > 4000 or any(str(parent) in names for name in names for parent in PurePosixPath(name).parents):
        raise ValueError("文件数超出限制，或文件名与目录冲突")
    sizes = {name: len(edits[name]) if name in edits else files[name].file_size for name in names}
    if sum(sizes.values()) > UNPACK_LIMIT or sum(size for name, size in sizes.items() if name.endswith(".py")) > SOURCE_LIMIT:
        raise ValueError("编辑后的项目超出大小限制")
    return files, edits, root


def export_project(changes):
    with zipfile.ZipFile("/atlas-project.zip") as archive:
        files, edits, _ = updated_files(archive, changes)
        with zipfile.ZipFile("/atlas-edited.zip", "w", zipfile.ZIP_DEFLATED) as output:
            for name in sorted(files.keys() | edits.keys()):
                if name in edits:
                    output.writestr(name, edits[name])
                else:
                    with archive.open(files[name]) as source, output.open(name, "w") as target:
                        shutil.copyfileobj(source, target)
    if Path("/atlas-edited.zip").stat().st_size > 64 * 1024 * 1024:
        raise ValueError("导出的 ZIP 超过 64 MiB")


def stage_project(entry, changes):
    modules = set()
    with zipfile.ZipFile("/atlas-project.zip") as archive:
        files, edits, root = updated_files(archive, changes)
        names = files.keys() | edits.keys()
        if entry not in names or not entry.endswith(".py") or PurePosixPath(entry).name == "__init__.py":
            raise ValueError("入口脚本不在项目中")
        for name in sorted(names):
            path = PROJECT / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if name in edits:
                path.write_bytes(edits[name])
            else:
                with archive.open(files[name]) as source, path.open("wb") as target:
                    shutil.copyfileobj(source, target)
            if path.suffix == ".py":
                try:
                    tree = ast.parse(path.read_bytes(), filename=name)
                except SyntaxError:
                    if name == entry:
                        raise
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        modules.update(alias.name.split(".")[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                        modules.add(node.module.split(".")[0])
    Path("/atlas-project.zip").unlink()
    return json.dumps({"modules": sorted(modules), "root": root})


class OutputLog(io.TextIOBase):
    def __init__(self):
        self.text = ""

    def write(self, text):
        self.text = (self.text + text[-LOG_LIMIT:])[-LOG_LIMIT:]
        return len(text)


def execute_project(entry, root):
    script = PROJECT / entry
    project_root = PROJECT / root
    OUTPUT.mkdir()
    os.chdir(project_root)
    os.environ["ATLAS_OUTPUT_DIR"] = str(OUTPUT)
    sys.argv = [str(script)]
    sys.path[:0] = [str(script.parent), str(project_root)]
    legacy_output = project_root / ".artifacts/user-strategies/sector-replay"
    if legacy_output.is_dir():
        # The original sector scripts use this fixed output directory.
        # Clear bundled reports in the disposable copy before collecting fresh results.
        shutil.rmtree(legacy_output)
    log = OutputLog()
    package = []
    for parent in script.parents:
        if parent == PROJECT or not (parent / "__init__.py").is_file():
            break
        package.insert(0, parent.name)
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        try:
            if package:
                sys.path.insert(0, str(script.parents[len(package)]))
                runpy.run_module(".".join([*package, script.stem]), run_name="__main__", alter_sys=True)
            else:
                runpy.run_path(str(script), run_name="__main__")
        except SystemExit as error:
            if error.code not in (None, 0):
                raise RuntimeError(f"入口脚本退出（{error.code}）\n{log.text[-3000:]}") from None
    return log.text


def collect_report(root, log):
    folders = (
        (OUTPUT, ""),
        (PROJECT / root / ".artifacts/user-strategies/sector-replay", "sector-replay/"),
    )
    total, summaries, warnings = 0, [], []
    with zipfile.ZipFile("/atlas-report.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("run.log", log)
        count = 0
        written = {"run.log"}
        for folder, prefix in folders:
            for path in sorted(folder.rglob("*")):
                if path.is_symlink() or not path.is_file():
                    continue
                size = path.stat().st_size
                if count >= 500 or total + size > REPORT_LIMIT:
                    if not warnings:
                        warnings.append("部分输出超出下载上限（500 个文件或 16 MiB）")
                    continue
                relative = prefix + path.relative_to(folder).as_posix()
                if relative in written:
                    continue
                bundle.write(path, relative)
                written.add(relative)
                total += size
                count += 1
                if path.name == "summary.json" and size <= 128 * 1024 and len(summaries) < 8:
                    try:
                        report = json.loads(path.read_text(), parse_constant=lambda _: None)
                        if isinstance(report, dict):
                            summaries.append({"path": relative, "data": report})
                    except (ValueError, RecursionError):
                        continue
    return json.dumps({"log": log, "summaries": summaries, "warnings": warnings}, ensure_ascii=False, allow_nan=False)
