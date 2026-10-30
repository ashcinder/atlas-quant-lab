"""One shared, non-queuing budget for expensive interactive work.

The API uses one worker. Background research holds its lease until completion,
including cancellation; polling and health requests never consume a slot.
"""
from threading import Lock

from fastapi import HTTPException


class WorkLimits:
    def __init__(self, maximum: int = 2):
        self.maximum = maximum
        self._owners: set[str] = set()
        self._lock = Lock()

    def acquire(self, owner: str) -> None:
        with self._lock:
            if owner in self._owners or len(self._owners) >= self.maximum:
                raise HTTPException(429, "计算任务繁忙：每个账号限1项，全局限2项，请稍后重试", headers={"Retry-After": "3"})
            self._owners.add(owner)

    def release(self, owner: str) -> None:
        with self._lock:
            self._owners.discard(owner)


work_limits = WorkLimits()


def expensive_request(method: str, path: str) -> bool:
    import re

    if method == "POST" and path in {
        "/api/v1/backtests", "/api/v1/portfolio/backtests",
        "/api/v1/strategy-code/assist", "/api/v1/ai-settings/test",
    }:
        return True
    patterns = (
        ("POST", r"/api/v1/quantjudge/agents/[^/]+/packages/[^/]+/execute"),
        ("POST", r"/api/v1/quantjudge/agents/[^/]+/zk-proofs"),
        ("POST", r"/api/v1/quantjudge/zk-proofs/[^/]+/verify"),
        ("GET", r"/api/v1/quantjudge/zk-proofs/[^/]+/bundle"),
        ("GET", r"/api/v1/quantjudge/reports/[^/]+/verify"),
    )
    return any(method == verb and re.fullmatch(pattern, path) for verb, pattern in patterns)
