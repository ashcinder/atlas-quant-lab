import shutil

import pytest

from app.proof_sources import (source_snapshot, verify_bundled_source, SOURCE_ROOT,
    EXPERIMENTAL_PROFILE, IMAGE_ID, MANIFEST_SHA256)


def test_frozen_snapshot_matches_fixed_manifest_and_all_source_bytes(tmp_path):
    metadata, files = source_snapshot(EXPERIMENTAL_PROFILE, IMAGE_ID)
    assert metadata['manifest_sha256'] == MANIFEST_SHA256
    assert 'program-core/src/lib.rs' in files
    assert 'program-methods/guest/Cargo.lock' in files
    for name, content in files.items():
        path = tmp_path / 'guest-source' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    assert verify_bundled_source(tmp_path, EXPERIMENTAL_PROFILE, IMAGE_ID, metadata)
    changed = tmp_path / 'guest-source/program-core/src/lib.rs'
    changed.write_bytes(changed.read_bytes() + b'\n// changed\n')
    with pytest.raises(ValueError, match='改变'):
        verify_bundled_source(tmp_path, EXPERIMENTAL_PROFILE, IMAGE_ID, metadata)


def test_legacy_bundle_is_compatible_and_wrong_fixed_image_fails():
    assert source_snapshot('atlas_program_backtest_risc0_v2', 'old') is None
    assert not verify_bundled_source('.', 'atlas_program_backtest_risc0_v2', 'old', None)
    with pytest.raises(ValueError, match='Image ID'):
        source_snapshot(EXPERIMENTAL_PROFILE, '00' * 32)


@pytest.mark.parametrize('change', ['manifest', 'source', 'symlink'])
def test_trusted_snapshot_tamper_cannot_redefine_source_mapping(tmp_path, change):
    shutil.copytree(SOURCE_ROOT / IMAGE_ID, tmp_path / IMAGE_ID)
    if change == 'manifest':
        (tmp_path / IMAGE_ID / 'manifest.json').write_text('{}')
    else:
        path = tmp_path / IMAGE_ID / 'program-core/src/lib.rs'
        if change == 'source':
            path.write_text('changed')
        else:
            path.unlink()
            path.symlink_to(SOURCE_ROOT / IMAGE_ID / 'program-core/src/lib.rs')
    with pytest.raises(ValueError):
        source_snapshot(EXPERIMENTAL_PROFILE, IMAGE_ID, source_root=tmp_path)
