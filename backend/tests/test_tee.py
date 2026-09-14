"""Synthetic PKI/COSE vectors, NOT evidence of a real AWS enclave."""

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import cbor2
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils, x25519

import app.tee as tee


@pytest.fixture
def fixture(monkeypatch):
    now = datetime.now(UTC)
    root_key = ec.generate_private_key(ec.SECP384R1())
    leaf_key = ec.generate_private_key(ec.SECP384R1())
    name = x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "Synthetic test root")])

    def cert(public_key, subject, ca):
        return (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(name)
            .public_key(public_key)
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(
                x509.BasicConstraints(ca=ca, path_length=1 if ca else None), critical=True
            )
            .add_extension(
                x509.KeyUsage(True, False, False, False, False, ca, ca, False, False), critical=True
            )
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False)
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
                critical=False,
            )
            .sign(root_key, hashes.SHA384())
        )

    root = cert(root_key.public_key(), name, True)
    leaf = cert(
        leaf_key.public_key(),
        x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "Synthetic test leaf")]),
        False,
    )
    # Only this unit test replaces the official pin. Production has no override.
    monkeypatch.setattr(tee, "AWS_ROOT_SHA256", root.fingerprint(hashes.SHA256()).hex())
    pcrs = {i: bytes([i + 1]) * 48 for i in (0, 1, 2)}
    verifier = tee.NitroVerifier(
        root.public_bytes(serialization.Encoding.PEM), {k: v.hex() for k, v in pcrs.items()}
    )
    fields = {
        "digest": "SHA384",
        "timestamp": int(time.time() * 1000),
        "pcrs": pcrs,
        "certificate": leaf.public_bytes(serialization.Encoding.DER),
        "cabundle": [root.public_bytes(serialization.Encoding.DER)],
        "nonce": b"n" * 32,
        "user_data": b"b" * 32,
        "public_key": x25519.X25519PrivateKey.generate()
        .public_key()
        .public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo),
    }

    def sign(fields):
        protected, payload = cbor2.dumps({1: -35}), cbor2.dumps(fields)
        signature = leaf_key.sign(
            cbor2.dumps(["Signature1", protected, b"", payload]), ec.ECDSA(hashes.SHA384())
        )
        r, s = utils.decode_dss_signature(signature)
        return cbor2.dumps(
            cbor2.CBORTag(18, [protected, {}, payload, r.to_bytes(48) + s.to_bytes(48)])
        )

    return verifier, fields, sign


def test_valid_synthetic_attestation_is_only_channel_attestation(fixture):
    verifier, fields, sign = fixture
    result = verifier.verify(sign(fields), nonce=b"n" * 32, binding=b"b" * 32)
    assert result["attestation_valid"]
    assert result["performance_verified"] is False


@pytest.mark.parametrize(
    ("help_text", "expects_no_castore"),
    [
        (
            b"-CAfile -CApath -untrusted -x509_strict -purpose -verify_depth -attime "
            b"-no-CAstore",
            True,
        ),
        (b"-CAfile -CApath -untrusted -x509_strict -purpose -verify_depth -attime", False),
    ],
)
def test_chain_isolates_trust_for_openssl_and_libressl(
    fixture, monkeypatch, help_text, expects_no_castore
):
    verifier, fields, _ = fixture
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[-1] == "-help":
            return SimpleNamespace(returncode=1, stdout=b"", stderr=help_text)
        ca_directory = Path(command[command.index("-CApath") + 1])
        assert ca_directory.is_dir()
        assert not list(ca_directory.iterdir())
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(tee.subprocess, "run", run)
    verifier._chain(fields["certificate"], fields["cabundle"], int(time.time()))

    verify_command = calls[1]
    assert "-CAfile" in verify_command
    assert "-CApath" in verify_command
    assert "-no-CApath" not in verify_command
    assert ("-no-CAstore" in verify_command) is expects_no_castore


def test_chain_fails_closed_without_explicit_trust_path_capability(
    fixture, monkeypatch
):
    verifier, fields, _ = fixture

    def run(command, **kwargs):
        if command[-1] != "-help":
            pytest.fail("certificate verification must not run with unsafe options")
        return SimpleNamespace(
            returncode=1,
            stdout=b"",
            stderr=b"-CAfile -untrusted -x509_strict -purpose -verify_depth -attime",
        )

    monkeypatch.setattr(tee.subprocess, "run", run)
    with pytest.raises(tee.AttestationError, match="缺少严格证书路径验证能力"):
        verifier._chain(fields["certificate"], fields["cabundle"], int(time.time()))


def test_rejects_certificate_outside_validity_window(fixture):
    verifier, fields, sign = fixture
    future = int(time.time()) + 2 * 24 * 60 * 60
    fields["timestamp"] = future * 1000
    with pytest.raises(tee.AttestationError, match="证书链、约束或有效期校验失败"):
        verifier.verify(sign(fields), nonce=b"n" * 32, binding=b"b" * 32, now=future)


@pytest.mark.parametrize("mutation", ["nonce", "binding", "expired", "debug", "signature"])
def test_rejects_tampering_and_wrong_context(fixture, mutation):
    verifier, fields, sign = fixture
    if mutation == "nonce":
        fields["nonce"] = b"x" * 32
    if mutation == "binding":
        fields["user_data"] = b"x" * 32
    if mutation == "expired":
        fields["timestamp"] -= 400000
    if mutation == "debug":
        fields["pcrs"][0] = bytes(48)
    document = sign(fields)
    if mutation == "signature":
        document = document[:-1] + bytes([document[-1] ^ 1])
    with pytest.raises(tee.AttestationError):
        verifier.verify(document, nonce=b"n" * 32, binding=b"b" * 32)
