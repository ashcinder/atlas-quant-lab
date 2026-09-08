"""Capability-gated, developer-authenticated private execution endpoints."""

import base64
import hashlib
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.execution import run_private_strategy
from app.execution_models import ExecutionRequest
from app.sandbox import RunnerFailure, RunnerUnavailable
from app.tee import AttestationError, NitroVerifier


class AttestationSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    document_base64: str = Field(min_length=1, max_length=44000)


def execution_router(studio, proofs):
    router = APIRouter(prefix="/api/v1/quantjudge")
    with sqlite3.connect(studio.path) as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS qj_tee_challenges (
            id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, package_id TEXT NOT NULL,
            nonce TEXT NOT NULL, binding TEXT NOT NULL, expires INTEGER NOT NULL,
            consumed INTEGER NOT NULL DEFAULT 0)""")

    def access(agent_id, package_id, token):
        try:
            return studio.get_package(agent_id, package_id, token)
        except PermissionError as exc:
            raise HTTPException(401, "开发者凭证无效") from exc
        except KeyError as exc:
            raise HTTPException(404, "策略包不存在") from exc

    def verifier():
        root = os.environ.get("ATLAS_NITRO_ROOT_CERT")
        pcrs = os.environ.get("ATLAS_NITRO_PCRS")
        if not root or not pcrs:
            raise RunnerUnavailable("未配置真实 Nitro 根证书和经审核的 PCR 测量值")
        return NitroVerifier(
            Path(root).read_bytes(), {int(k): v for k, v in json.loads(pcrs).items()}
        )

    @router.get("/studio/execution-capabilities")
    def capabilities():
        return {
            "python": {
                "configured": os.environ.get("ATLAS_RUNNER_ENABLED") == "1",
                "runtime": "gvisor",
                "verified_available": False,
                "scope": "single_asset_atlas_strategy_v1",
                "operator_confidential": False,
            },
            "ai": {
                "configured": bool(os.environ.get("ATLAS_AI_MODEL")),
                "provider": "local_ollama",
                "hardware_attested": False,
            },
            "tee": {
                "configured": bool(os.environ.get("ATLAS_NITRO_PCRS")),
                "scope": "nitro_attested_channel",
                "execution_available": False,
            },
            "general_python_zkp": False,
        }

    @router.post("/agents/{agent_id}/packages/{package_id}/execute")
    def execute(
        agent_id: str,
        package_id: str,
        request: ExecutionRequest,
        developer_token: str | None = Header(default=None, alias="X-Developer-Token"),
    ):
        access(agent_id, package_id, developer_token)
        try:
            _, path = proofs.market_dataset(request.market_data_hash)
            dataset = json.loads(path.read_text())["dataset"]
            archive = studio.download_package(agent_id, package_id, developer_token)
            return run_private_strategy(archive, dataset, request)
        except RunnerUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except (RunnerFailure, ValueError) as exc:
            raise HTTPException(422, "隔离执行未完成：" + str(exc)[:240]) from exc
        except KeyError as exc:
            raise HTTPException(404, "请先登记有效的市场数据集") from exc

    @router.post("/agents/{agent_id}/packages/{package_id}/tee/challenge")
    def challenge(
        agent_id: str,
        package_id: str,
        developer_token: str | None = Header(default=None, alias="X-Developer-Token"),
    ):
        package = access(agent_id, package_id, developer_token)
        try:
            verifier()  # Validate configuration before issuing a challenge.
        except (RunnerUnavailable, ValueError, OSError) as exc:
            raise HTTPException(503, "可信执行环境尚未配置或配置无效") from exc
        identifier, nonce = secrets.token_hex(16), secrets.token_hex(32)
        statement = {
            "domain": "ATLAS_NITRO_CHANNEL_V1",
            "agent_id": agent_id,
            "package_hash": package["content_hash"],
            "nonce": nonce,
        }
        binding = hashlib.sha256(
            json.dumps(statement, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        expires = int(time.time()) + 300
        with sqlite3.connect(studio.path) as connection:
            connection.execute(
                "DELETE FROM qj_tee_challenges WHERE expires < ?", (int(time.time()),)
            )
            count = connection.execute(
                "SELECT count(*) FROM qj_tee_challenges WHERE agent_id=? AND consumed=0",
                (agent_id,),
            ).fetchone()[0]
            if count >= 8:
                raise HTTPException(429, "未完成的 TEE 挑战过多")
            connection.execute(
                "INSERT INTO qj_tee_challenges VALUES (?, ?, ?, ?, ?, ?, 0)",
                (identifier, agent_id, package_id, nonce, binding, expires),
            )
        return {
            "id": identifier,
            "nonce": nonce,
            "user_data": binding,
            "statement": statement,
            "expires": expires,
            "performance_verified": False,
        }

    @router.post("/agents/{agent_id}/packages/{package_id}/tee/verify")
    def verify(
        agent_id: str,
        package_id: str,
        request: AttestationSubmission,
        developer_token: str | None = Header(default=None, alias="X-Developer-Token"),
    ):
        access(agent_id, package_id, developer_token)
        with sqlite3.connect(studio.path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM qj_tee_challenges WHERE id=? AND agent_id=? "
                "AND package_id=? AND consumed=0 AND expires>=?",
                (request.challenge_id, agent_id, package_id, int(time.time())),
            ).fetchone()
        if row is None:
            raise HTTPException(409, "挑战已过期、已使用或不属于当前策略包")
        try:
            result = verifier().verify(
                base64.b64decode(request.document_base64, validate=True),
                nonce=bytes.fromhex(row["nonce"]),
                binding=bytes.fromhex(row["binding"]),
            )
        except RunnerUnavailable as exc:
            raise HTTPException(503, "TEE 验证器未配置") from exc
        except (AttestationError, ValueError, OSError) as exc:
            raise HTTPException(422, "硬件证明验证失败") from exc
        with sqlite3.connect(studio.path) as connection:
            changed = connection.execute(
                "UPDATE qj_tee_challenges SET consumed=1 WHERE id=? AND consumed=0 AND expires>=?",
                (request.challenge_id, int(time.time())),
            ).rowcount
            if changed != 1:
                raise HTTPException(409, "挑战已被并发消费或已过期")
        return result

    return router
