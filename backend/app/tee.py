"""Strict AWS Nitro document verification, not a synthetic TEE implementation.

Success attests a pinned enclave and its channel key. It does NOT on its own
prove a strategy ran, an LLM ran, or a performance number is correct.
"""

from __future__ import annotations

import hashlib
import hmac
import shutil
import subprocess
import tempfile
import time
from io import BytesIO
from pathlib import Path

import cbor2
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils, x25519

AWS_ROOT_SHA256 = "641a0321a3e244efe456463195d606317ed7cdcc3c1756e09893f3c68f79bb5b"


class AttestationError(ValueError):
    pass


def _decode(data: bytes):
    stream = BytesIO(data)
    result = cbor2.CBORDecoder(stream).decode()
    if stream.read(1):
        raise AttestationError("CBOR 后含额外内容")
    return result


class NitroVerifier:
    def __init__(self, root_pem: bytes, measurements: dict[int, str]):
        self.root = x509.load_pem_x509_certificate(root_pem)
        if self.root.fingerprint(hashes.SHA256()).hex() != AWS_ROOT_SHA256:
            raise AttestationError("Nitro 根证书与 AWS 公布的指纹不一致")
        if set(measurements) != {0, 1, 2}:
            raise AttestationError("必须固定 PCR0、PCR1 和 PCR2")
        if any(
            len(v) != 96 or set(v) - set("0123456789abcdef") or v == "0" * 96
            for v in measurements.values()
        ):
            raise AttestationError("PCR 必须为非零 SHA384 值；拒绝调试 Enclave")
        self.measurements = measurements

    def _chain(self, leaf: bytes, chain: list[bytes], now: int):
        if not 1 <= len(chain) <= 5 or any(len(cert) > 4096 for cert in [leaf, *chain]):
            raise AttestationError("证书链大小无效")
        openssl = shutil.which("openssl")
        if not openssl:
            raise AttestationError("未安装证书路径验证器 openssl")
        cert = x509.load_der_x509_certificate(leaf)
        intermediates = [x509.load_der_x509_certificate(der) for der in chain]
        with tempfile.TemporaryDirectory(prefix="atlas-nitro-certs-") as directory:
            root, target, bundle = (
                Path(directory) / name for name in ("root.pem", "leaf.pem", "chain.pem")
            )
            root.write_bytes(self.root.public_bytes(serialization.Encoding.PEM))
            target.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            bundle.write_bytes(
                b"".join(c.public_bytes(serialization.Encoding.PEM) for c in intermediates)
            )
            result = subprocess.run(
                [
                    openssl,
                    "verify",
                    "-x509_strict",
                    "-purpose",
                    "any",
                    "-verify_depth",
                    "5",
                    "-attime",
                    str(now),
                    "-CAfile",
                    str(root),
                    "-no-CApath",
                    "-no-CAstore",
                    "-untrusted",
                    str(bundle),
                    str(target),
                ],
                capture_output=True,
                timeout=5,
                env={},
                check=False,
            )
            if result.returncode:
                raise AttestationError("Nitro 签名证书链、约束或有效期校验失败")
        return cert

    def verify(
        self, document: bytes, *, nonce: bytes, binding: bytes, now: int | None = None
    ) -> dict:
        if not 1 <= len(document) <= 32768 or len(nonce) != 32 or len(binding) != 32:
            raise AttestationError("证明文档或绑定长度无效")
        now = int(time.time()) if now is None else now
        try:
            cose = _decode(document)
            if isinstance(cose, cbor2.CBORTag):
                if cose.tag != 18:
                    raise AttestationError("仅接受 COSE_Sign1")
                cose = cose.value
            protected, unprotected, payload, signature = cose
            if _decode(protected) != {1: -35} or unprotected != {} or len(signature) != 96:
                raise AttestationError("仅接受受保护的 ES384 签名")
            fields = _decode(payload)
            if (
                fields["digest"] != "SHA384"
                or not now * 1000 - 300000 <= fields["timestamp"] <= now * 1000 + 5000
            ):
                raise AttestationError("证明过期、来自未来或摘要算法无效")
            for index, expected in self.measurements.items():
                if not hmac.compare_digest(fields["pcrs"][index], bytes.fromhex(expected)):
                    raise AttestationError("Enclave 测量值不匹配")
            if not hmac.compare_digest(fields["nonce"], nonce) or not hmac.compare_digest(
                fields["user_data"], binding
            ):
                raise AttestationError("证明未绑定当前挑战和任务")
            cert = self._chain(fields["certificate"], fields["cabundle"], now)
            key = cert.public_key()
            if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
                key.curve, ec.SECP384R1
            ):
                raise AttestationError("签名密钥不是 P-384")
            der_signature = utils.encode_dss_signature(
                int.from_bytes(signature[:48]), int.from_bytes(signature[48:])
            )
            key.verify(
                der_signature,
                cbor2.dumps(["Signature1", protected, b"", payload]),
                ec.ECDSA(hashes.SHA384()),
            )
            public_key = serialization.load_der_public_key(fields["public_key"])
            if not isinstance(public_key, x25519.X25519PublicKey):
                raise AttestationError("Enclave 通道公钥必须为 X25519")
            return {
                "attestation_valid": True,
                "document_hash": hashlib.sha256(document).hexdigest(),
                "channel_public_key_der_hex": fields["public_key"].hex(),
                "measurements": self.measurements,
                "performance_verified": False,
            }
        except AttestationError:
            raise
        except Exception as exc:
            raise AttestationError("Nitro 证明结构或密码学验证失败") from exc
