"""Trusted local source mapping; uploaded manifests never select code or paths."""
import hashlib
import json
from pathlib import Path

EXPERIMENTAL_PROFILE = 'atlas_program_backtest_risc0_v3_experimental'
IMAGE_ID = '86a4381bd862c632e72dfa19fc0b1c3115ec314570eedb7fb0a195158b3e04d4'
R0BF_SHA256 = '0963461252a4833d7144e66dfa53e5b32656901545bfc500c022b0d69a8af0e3'
MANIFEST_SHA256 = '2c15173c53a9031265a6f2cb921d5e71ca39d3fa41686ecd9f180f2d330640ba'
SOURCE_ROOT = Path(__file__).resolve().parents[2] / 'strategy/zkvm/source-snapshots'


def source_snapshot(profile, image_id, source_root=SOURCE_ROOT):
    if profile != EXPERIMENTAL_PROFILE:
        return None
    if image_id != IMAGE_ID:
        raise ValueError('实验profile与冻结源码Image ID不匹配')
    root = source_root / IMAGE_ID
    manifest_path = root / 'manifest.json'
    if root.is_symlink() or manifest_path.is_symlink():
        raise ValueError('源码快照不能是符号链接')
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != MANIFEST_SHA256:
        raise ValueError('受信源码清单已改变')
    manifest = json.loads(manifest_bytes)
    if (manifest['profile'], manifest['image_id'], manifest['r0bf_sha256']) != (profile, IMAGE_ID, R0BF_SHA256):
        raise ValueError('受信源码身份不一致')
    files = {'manifest.json': manifest_bytes}
    for name, expected in manifest['files'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('源码快照路径越界')
        path = root / relative
        if any(part.is_symlink() for part in [path, *path.parents] if part != root.parent):
            raise ValueError('源码快照不能是符号链接')
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('源码快照路径越界')
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError('受信源码文件已改变')
        files[name] = content
    metadata = {'schema': 'atlas.guest-source.v1', 'profile': profile, 'image_id': IMAGE_ID,
                'r0bf_sha256': R0BF_SHA256, 'manifest_sha256': MANIFEST_SHA256,
                'bundle_path': 'guest-source/manifest.json'}
    return metadata, files


def verify_bundled_source(folder, profile, image_id, declared):
    snapshot = source_snapshot(profile, image_id)
    if snapshot is None:
        # Legacy bundles have no source snapshot requirement.
        if declared is not None:
            raise ValueError('旧profile不能声明未登记的源码快照')
        return False
    metadata, files = snapshot
    if declared != metadata:
        raise ValueError('包内源码映射与受信checkout不一致')
    root = Path(folder) / 'guest-source'
    if root.is_symlink():
        raise ValueError('源码包不能是符号链接')
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() or p.is_symlink()}
    if actual != set(files):
        raise ValueError('源码快照文件缺失或包含未登记文件')
    for name, expected in files.items():
        path = root / name
        if (path.is_symlink() or not path.resolve().is_relative_to(root.resolve())
                or path.read_bytes() != expected):
            raise ValueError('包内源码快照已改变')
    return True
