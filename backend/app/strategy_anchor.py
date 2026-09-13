"""Public strategy-version commitments; no strategy bytes or wallet keys."""

import hashlib
import json
import re

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.supervisor_client import SupervisorClient, SupervisorRPCError

CHAIN_ID = 1051


class AnchorPrepare(BaseModel):
    address: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")


class AnchorConfirm(BaseModel):
    transaction_hash: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")


class StrategyAnchorStore:
    def __init__(self, runtime, client=None):
        self.runtime = runtime
        self.client = client or SupervisorClient()
        with runtime._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS strategy_anchors (
                release_id TEXT PRIMARY KEY, signer TEXT NOT NULL,
                transaction_hash TEXT, block_number INTEGER, block_hash TEXT,
                status TEXT NOT NULL DEFAULT 'pending')""")

    def release(self, owner, identifier, write=False):
        with self.runtime._connect() as conn:
            row = self.runtime._release_for(conn, identifier)
        if row["owner_id"] != owner and (write or not row["published"]):
            raise HTTPException(404, "策略版本不存在")
        return row

    @staticmethod
    def commitment(row):
        result = {
            "domain": "atlas.strategy-version/v1",
            "chain_id": CHAIN_ID,
            "release_id": row["id"],
            "strategy_id": row["strategy_id"],
            "version": row["version"],
            "content_hash": row["content_hash"],
            "publisher_hash": hashlib.sha256(row["owner_id"].encode()).hexdigest(),
        }
        snapshot = json.loads(row["snapshot"])
        if snapshot.get("execution_mode") == "private_runner":
            result["code_commitment"] = snapshot["code_commitment"]
            result["runner_public_key"] = snapshot["runner_public_key"]
        return result

    def status(self, owner, identifier):
        row = self.release(owner, identifier)
        payload = self.commitment(row)
        data = "0x" + json.dumps(payload, sort_keys=True, separators=(",", ":")).encode().hex()
        with self.runtime._connect() as conn:
            anchor = conn.execute(
                "SELECT * FROM strategy_anchors WHERE release_id=?", (identifier,)
            ).fetchone()
        return {
            "commitment": payload,
            "data": data,
            "chain_id": CHAIN_ID,
            "anchor": dict(anchor) if anchor else {"status": "not_anchored"},
            "scope": "版本承诺存证；不证明收益或每次执行正确",
        }

    def prepare(self, owner, identifier, address):
        self.release(owner, identifier, True)
        address = address.lower()
        if not re.fullmatch(r"0x[0-9a-f]{40}", address):
            raise HTTPException(422, "钱包地址无效")
        with self.runtime._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM strategy_anchors WHERE release_id=?", (identifier,)
            ).fetchone()
            if existing and existing["transaction_hash"]:
                raise HTTPException(409, "已有交易待核验，请先核验原交易")
            conn.execute(
                "INSERT INTO strategy_anchors (release_id,signer) VALUES (?,?) "
                "ON CONFLICT(release_id) DO UPDATE SET signer=excluded.signer",
                (identifier, address),
            )
        result = self.status(owner, identifier)
        result["transaction"] = {
            "from": address,
            "to": address,
            "value": "0x0",
            "chainId": hex(CHAIN_ID),
            "data": result["data"],
        }
        return result

    def confirm(self, owner, identifier, tx_hash):
        self.release(owner, identifier, True)
        result = self.status(owner, identifier)
        anchor = result["anchor"]
        if not anchor.get("signer"):
            raise HTTPException(409, "请先准备钱包存证")
        if anchor.get("transaction_hash") not in (None, tx_hash.lower()):
            raise HTTPException(409, "请核验已登记的原交易")
        status, block, block_hash = "submitted", None, None
        try:
            chain = self.client.status()
            if not chain.connected or chain.chain_id != CHAIN_ID:
                raise SupervisorRPCError("Supervisor未连接或链ID不是1051")
            tx = self.client.transaction(tx_hash)
            receipt = self.client.transaction_receipt(tx_hash)
            if tx:
                matches = (
                    str(tx.get("hash", "")).lower() == tx_hash.lower()
                    and str(tx.get("from", "")).lower() == anchor["signer"]
                    and str(tx.get("to", "")).lower() == anchor["signer"]
                    and tx.get("input", "").lower() == result["data"]
                    and int(tx.get("value", "0x1"), 16) == 0
                )
                if not matches:
                    raise HTTPException(422, "交易与策略版本、钱包或零金额存证不匹配")
            if receipt:
                if not tx or str(receipt.get("transactionHash", "")).lower() != tx_hash.lower():
                    raise HTTPException(422, "回执缺少匹配的原始交易")
                if receipt.get("status") == "0x0":
                    status = "failed"
                elif receipt.get("status") == "0x1":
                    block = int(receipt["blockNumber"], 16)
                    block_hash = receipt["blockHash"]
                    canonical = self.client._call("eth_getBlockByNumber", [hex(block), False])
                    if (
                        not canonical
                        or canonical.get("hash") != block_hash
                        or tx.get("blockHash") != block_hash
                        or chain.block_number < block
                    ):
                        raise SupervisorRPCError("回执区块尚未被当前链确认")
                    status = "confirmed"
        except (SupervisorRPCError, ValueError, KeyError, TypeError):
            status, block, block_hash = "unreachable", None, None
        with self.runtime._connect() as conn:
            conn.execute(
                "UPDATE strategy_anchors SET transaction_hash=?,status=?,block_number=?,"
                "block_hash=? WHERE release_id=? AND signer=?",
                (tx_hash.lower(), status, block, block_hash, identifier, anchor["signer"]),
            )
        return self.status(owner, identifier)
