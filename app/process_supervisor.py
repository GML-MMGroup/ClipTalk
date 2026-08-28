from __future__ import annotations

import subprocess
import threading
import weakref
from typing import Any


class ProcessSupervisor:
    """Own child processes so shutdown and cancellation cannot orphan FFmpeg."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processes: weakref.WeakSet[subprocess.Popen[Any]] = weakref.WeakSet()

    def start(self, command: list[str], **kwargs: Any) -> subprocess.Popen[Any]:
        process = subprocess.Popen(command, **kwargs)
        with self._lock:
            self._processes.add(process)
        return process

    def forget(self, process: subprocess.Popen[Any] | None) -> None:
        if process is None:
            return
        with self._lock:
            self._processes.discard(process)

    def terminate(self, process: subprocess.Popen[Any] | None, timeout: float = 3.0) -> None:
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=timeout)
        finally:
            self.forget(process)

    def shutdown(self) -> None:
        with self._lock:
            processes = list(self._processes)
        for process in processes:
            self.terminate(process)


process_supervisor = ProcessSupervisor()
