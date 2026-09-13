"""Accept signed decisions from a developer-owned runner, never source code."""

import json
import time
from decimal import Decimal

import pandas as pd
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import quote_probe


class PrivateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str = Field(pattern=r"^atlas.private-decision/v1$")
    run_id: str = Field(pattern=r"^run_[a-f0-9]{18}$")
    release_id: str = Field(pattern=r"^rel_[a-f0-9]{18}$")
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    nonce: str = Field(pattern=r"^[a-f0-9]{32}$")
    issued_at: float = Field(gt=0, allow_inf_nan=False)
    target: str = Field(pattern=r"^(?:0(?:\.[0-9]{1,8})?|1(?:\.0{1,8})?)$")
    signature: str = Field(pattern=r"^[a-f0-9]{128}$")


def signing_bytes(body):
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


class PrivateRunnerStore:
    def __init__(self, runtime):
        self.runtime = runtime
        with runtime._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS private_decisions (
                run_id TEXT NOT NULL, nonce TEXT NOT NULL, issued_at REAL NOT NULL,
                received_at REAL NOT NULL, payload TEXT NOT NULL, signature TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'reserved', PRIMARY KEY(run_id,nonce))""")

    def submit(self, body: PrivateDecision):
        now = time.time()
        if abs(now - body.issued_at) > 30:
            raise HTTPException(422, "签名信号已过期或客户端时间不正确")
        store = self.runtime
        with store._connect() as conn:
            run = conn.execute("SELECT * FROM strategy_runs WHERE id=?", (body.run_id,)).fetchone()
            if not run:
                raise HTTPException(403, "签名或运行授权无效")
            release = store._release_for(conn, run["release_id"])
        public = json.loads(release["snapshot"])
        if (
            public.get("execution_mode") != "private_runner"
            or body.release_id != release["id"]
            or body.content_hash != release["content_hash"]
        ):
            raise HTTPException(403, "签名或运行授权无效")
        payload = body.model_dump(exclude={"signature"})
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(public["runner_public_key"])).verify(
                bytes.fromhex(body.signature), signing_bytes(payload)
            )
        except (InvalidSignature, ValueError, KeyError):
            raise HTTPException(403, "签名或运行授权无效") from None
        with store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT * FROM strategy_runs WHERE id=?", (body.run_id,)
            ).fetchone()
            prior = conn.execute(
                "SELECT MAX(issued_at) FROM private_decisions WHERE run_id=?", (body.run_id,)
            ).fetchone()[0]
            if (
                current["status"] != "active"
                or current["environment"] != "platform_sim"
                or current["symbol"] != "BTC-USDT"
                or current["lease_until"] > now
                or body.issued_at < float(current["execution_not_before"])
                or now - (current["last_bar_time"] or 0) < 10
            ):
                raise HTTPException(409, "实例未运行、正在处理或未到下次执行时间")
            if prior is not None and body.issued_at <= prior:
                raise HTTPException(409, "拒绝重复或倒序信号")
            if conn.execute(
                "SELECT 1 FROM private_decisions WHERE run_id=? AND nonce=?",
                (body.run_id, body.nonce),
            ).fetchone():
                raise HTTPException(409, "拒绝重复信号")
            conn.execute(
                "INSERT INTO private_decisions "
                "(run_id,nonce,issued_at,received_at,payload,signature) VALUES (?,?,?,?,?,?)",
                (
                    body.run_id,
                    body.nonce,
                    body.issued_at,
                    now,
                    signing_bytes(payload).decode(),
                    body.signature,
                ),
            )
            conn.execute(
                "UPDATE strategy_runs SET lease_until=? WHERE id=?", (now + 45, body.run_id)
            )
        try:
            book = quote_probe.quote()
            stamp = int(time.time())
            if abs(time.time() - body.issued_at) > 30:
                raise HTTPException(422, "报价返回时信号已过期")
            with store._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                current = conn.execute(
                    "SELECT * FROM strategy_runs WHERE id=?", (body.run_id,)
                ).fetchone()
                if (
                    current["status"] != "active"
                    or current["execution_not_before"] != run["execution_not_before"]
                ):
                    raise HTTPException(409, "运行状态已改变，本次信号作废")
            quantity = Decimal(current["quantity"])
            equity = Decimal(current["cash"]) + quantity * book["bidPrice"]
            buying = Decimal(body.target) * equity > quantity * book["bidPrice"]
            sample = pd.DataFrame(
                [
                    {
                        "open": book["askPrice"] if buying else book["bidPrice"],
                        "close": book["bidPrice"],
                        "volume": book["askQty"] if buying else book["bidQty"],
                    }
                ]
            )
            processed = store._process_bar(
                run["owner_id"],
                body.run_id,
                release,
                sample,
                pd.Series([float(body.target)]),
                pd.Series(["开发者本地签名信号 · 平台实时报价模拟成交"]),
                [stamp],
                0,
                quoted=True,
                decision_target=body.target,
                execution_epoch=run["execution_not_before"],
            )
            with store._connect() as conn:
                conn.execute(
                    "UPDATE private_decisions SET status=? WHERE run_id=? AND nonce=?",
                    ("processed" if processed else "discarded", body.run_id, body.nonce),
                )
            return {"accepted": bool(processed), "run_id": body.run_id, "nonce": body.nonce}
        except Exception:
            with store._connect() as conn:
                conn.execute(
                    "UPDATE private_decisions SET status='failed' WHERE run_id=? AND nonce=?",
                    (body.run_id, body.nonce),
                )
            raise
        finally:
            with store._connect() as conn:
                conn.execute("UPDATE strategy_runs SET lease_until=0 WHERE id=?", (body.run_id,))
