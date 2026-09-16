"""Export public verification material only; never infer private witness paths."""
import io
import json
from pathlib import Path
import zipfile


def export_bundle(store, proof_id):
    record = store.get(proof_id)
    statement = record['public_statement']
    _, market = store.market_dataset(statement['market_data_hash'])
    with store._connect() as conn:
        example = conn.execute('SELECT source,witness_json FROM qj_public_programs WHERE proof_id=?', (proof_id,)).fetchone()
    manifest = {'schema': 'atlas.proof.bundle.v1', 'proof_id': proof_id,
                'proof_hash': record['proof_hash'], 'image_id': record['image_id'],
                'public_example': example is not None}
    root = Path(__file__).resolve().parents[2]
    content = io.BytesIO()
    with zipfile.ZipFile(content, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps(manifest, indent=2))
        archive.writestr('journal.json', json.dumps(statement, indent=2))
        archive.writestr('proof.r0', store.receipt_path(proof_id).read_bytes())
        archive.writestr('market.json', market.read_bytes())
        archive.writestr('verify-proof-bundle.py', (root / 'scripts/verify-proof-bundle.py').read_bytes())
        if example:
            archive.writestr('strategy.py', example['source'])
            archive.writestr('witness.public.json', example['witness_json'])
        archive.writestr('README.txt', '''Atlas 离线 Proof 验证包

使用自己信任的 Atlas checkout 构建 atlas-zkvm，并核对固定 profiles.json。
不要把包内 manifest 当作信任根；验证脚本从你的 checkout 读取固定 image ID。
在解压目录执行（将 /path/to/atlas 替换为仓库路径）：
/path/to/atlas/backend/.venv/bin/python /path/to/atlas/scripts/verify-proof-bundle.py --bundle . --repository /path/to/atlas

可加入 --expected-agent 策略ID --expected-return-ppm 整数收益，以核对自己预期的策略和收益。
10000 ppm = 1%。验证不依赖平台服务，不执行策略 Python，只编译支持的子集。
公开样本额外包含源码和 witness，可重放并比对 journal；普通私有策略不包含这些文件。
证明保证承诺数据上的确定性执行，不保证行情来源签名或未来收益。
''')
    return content.getvalue()
