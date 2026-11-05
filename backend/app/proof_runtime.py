"""Side-effect-free limits for new proof generation, never receipt verification."""
from dataclasses import dataclass
import json
import os

MAX_PROOF_INPUT_BYTES = 16 * 1024 * 1024
MAX_MARKET_TEXT_BYTES = 4096
MARKET_TEXT_FIELDS = ('source', 'symbol', 'interval', 'adjustment')


def bounded_environment_integer(name, minimum, maximum, default=None):
    raw = os.environ.get(name)
    if raw is None:
        return default
    if (not raw.isascii() or not raw.isdecimal() or len(raw) > 10
            or not minimum <= int(raw) <= maximum):
        raise ValueError(f'{name}必须是{minimum}到{maximum}之间的整数')
    return int(raw)


def proof_segment_limit_po2():
    return bounded_environment_integer('ATLAS_PROOF_SEGMENT_PO2', 16, 20)


def proof_disk_segments_enabled():
    raw = os.environ.get('ATLAS_PROOF_DISK_SEGMENTS', '0')
    if raw not in {'0', '1'}:
        raise ValueError('ATLAS_PROOF_DISK_SEGMENTS必须为0或1')
    return raw == '1'


@dataclass(frozen=True)
class ProofSettings:
    threads: int
    segment_limit_po2: int | None
    disk_segments: bool


def proof_settings():
    return ProofSettings(
        bounded_environment_integer('ATLAS_PROOF_THREADS', 1, 3, default=1),
        proof_segment_limit_po2(), proof_disk_segments_enabled())


def read_proof_json(path):
    with path.open('rb') as handle:
        data = handle.read(MAX_PROOF_INPUT_BYTES + 1)
    if len(data) > MAX_PROOF_INPUT_BYTES:
        raise ValueError('证明输入不能超过16MiB')
    return json.loads(data)


def validate_market_input(dataset):
    for field in MARKET_TEXT_FIELDS:
        value = dataset.get(field)
        if not isinstance(value, str):
            raise ValueError(f'行情{field}必须是字符串，最多4096个UTF-8字节')
        try:
            size = len(value.encode('utf-8'))
        except UnicodeError:
            raise ValueError(f'行情{field}必须是有效UTF-8字符串') from None
        if size > MAX_MARKET_TEXT_BYTES:
            raise ValueError(f'行情{field}不能超过4096个UTF-8字节')
    bars = dataset.get('bars')
    if not isinstance(bars, list) or not 3 <= len(bars) <= 20_000:
        raise ValueError('证明行情需要3–20000根K线')


def validate_witness_input(witness):
    validate_market_input(witness['market'])
    # Match private witness files, not only their smaller compact form.
    if len(json.dumps(witness, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')) > MAX_PROOF_INPUT_BYTES:
        raise ValueError('证明输入不能超过16MiB')
