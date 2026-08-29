from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


class SupervisorRPCError(RuntimeError):
    pass


@dataclass(frozen=True)
class SupervisorStatus:
    connected: bool
    rpc_url: str
    chain_id: int | None = None
    block_number: int | None = None
    error: str | None = None


class SupervisorClient:
    """Narrow JSON-RPC adapter; it never imports or modifies Supervisor source/configuration."""

    def __init__(self, rpc_url: str | None = None, timeout: float = 0.8):
        self.rpc_url = (rpc_url or os.getenv("QUANTJUDGE_SUPERVISOR_RPC_URL") or "http://127.0.0.1:42515").rstrip("/")
        self.timeout = timeout

    def _call(self, method: str, params: list[Any]) -> Any:
        try:
            response = httpx.post(
                self.rpc_url,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SupervisorRPCError(f"Supervisor RPC 不可用: {exc}") from exc
        if payload.get("error"):
            raise SupervisorRPCError(f"Supervisor RPC {method} 失败: {payload['error']}")
        if "result" not in payload:
            raise SupervisorRPCError(f"Supervisor RPC {method} 响应缺少 result")
        return payload["result"]

    @staticmethod
    def _hex_int(value: Any) -> int:
        if not isinstance(value, str) or not value.startswith("0x"):
            raise SupervisorRPCError("链端返回了无效的十六进制整数")
        return int(value, 16)

    def status(self) -> SupervisorStatus:
        try:
            chain_id = self._hex_int(self._call("eth_chainId", []))
            block_number = self._hex_int(self._call("eth_blockNumber", []))
            return SupervisorStatus(True, self.rpc_url, chain_id, block_number)
        except (SupervisorRPCError, ValueError) as exc:
            return SupervisorStatus(False, self.rpc_url, error=str(exc))

    def transaction_receipt(self, transaction_hash: str) -> dict[str, Any] | None:
        result = self._call("eth_getTransactionReceipt", [transaction_hash])
        if result in (None, "0x"):
            return None
        if not isinstance(result, dict):
            raise SupervisorRPCError("链端返回了无效的交易回执")
        return result

    def transaction(self, transaction_hash: str) -> dict[str, Any] | None:
        result = self._call("eth_getTransactionByHash", [transaction_hash])
        if result is None:
            return None
        if not isinstance(result, dict):
            raise SupervisorRPCError("链端返回了无效的交易")
        return result

    def submit_signed_transaction(self, signed_raw_transaction: str) -> str:
        """Submit bytes signed by an external wallet. This service never holds private keys."""
        result = self._call("eth_sendRawTransaction", [signed_raw_transaction])
        if not isinstance(result, str) or not result.startswith("0x"):
            raise SupervisorRPCError("链端未返回有效交易哈希")
        return result
