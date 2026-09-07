from __future__ import annotations

import logging
import threading

from app.journal.domain import empty_ledger, materialize_automatic
from app.journal.store import JournalStore


class JournalScheduler:
    """Best-effort periodic materialization; CAS protects concurrent browser writes."""

    def __init__(self, store: JournalStore, interval_seconds: int = 60) -> None:
        self.store = store
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def _run_once(self) -> None:
        for user in self.store.users():
            try:
                old = self.store.read_ledger(user.id, empty_ledger())
                result = materialize_automatic(old["state"])
                if result["state"] != old["state"]:
                    self.store.save_ledger(user.id, result["state"], old["revision"])
            except Exception:
                logging.getLogger(__name__).exception(
                    "Automatic ledger update failed for user %s", user.id
                )

    def _loop(self) -> None:
        while not self.stop_event.wait(self.interval_seconds):
            try:
                self._run_once()
            except Exception:
                continue

    def start(self) -> None:
        self.stop_event.clear()
        self._run_once()
        self.thread = threading.Thread(target=self._loop, name="journal-scheduler", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
