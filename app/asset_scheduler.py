from __future__ import annotations

import threading
import time
from concurrent.futures import Executor
from typing import Any, Callable


class SingleFlightAssetScheduler:
    """Run one background asset build per identity with failure cooldown."""

    default_cooldown_seconds = 10.0

    def __init__(
        self,
        *,
        executor: Executor,
        prepare: Callable[[str], Any],
        cooldown_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.executor = executor
        self.prepare = prepare
        self.cooldown_seconds = (
            self.default_cooldown_seconds if cooldown_seconds is None else cooldown_seconds
        )
        self.clock = clock
        self.lock = threading.Lock()
        self.scheduled: set[str] = set()
        self.failures: dict[str, tuple[float, str]] = {}

    def schedule(self, job_id: str, identity: str, *, force: bool = False) -> bool:
        with self.lock:
            if identity in self.scheduled:
                return False
            if force:
                self.failures.pop(identity, None)
            failure = self.failures.get(identity)
            if failure and self.clock() - failure[0] < self.cooldown_seconds:
                return False
            self.failures.pop(identity, None)
            self.scheduled.add(identity)

        def generate() -> None:
            try:
                self.prepare(job_id)
                with self.lock:
                    self.failures.pop(identity, None)
            except Exception as error:
                with self.lock:
                    self.failures[identity] = (self.clock(), str(error)[:500])
            finally:
                with self.lock:
                    self.scheduled.discard(identity)

        try:
            self.executor.submit(generate)
        except RuntimeError:
            with self.lock:
                self.scheduled.discard(identity)
            return False
        return True

    def is_scheduled(self, identity: str) -> bool:
        with self.lock:
            return identity in self.scheduled

    def failure(self, identity: str) -> str | None:
        with self.lock:
            failure = self.failures.get(identity)
            if not failure:
                return None
            if self.clock() - failure[0] >= self.cooldown_seconds:
                self.failures.pop(identity, None)
                return None
            return failure[1]

    def forget(self, identity: str) -> None:
        with self.lock:
            self.failures.pop(identity, None)
