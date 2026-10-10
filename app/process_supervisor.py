from __future__ import annotations

import subprocess
import os
import signal
import threading
from typing import Any


class ProcessSupervisor:
    """Own child processes so shutdown and cancellation cannot orphan FFmpeg."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processes: dict[int, subprocess.Popen[Any]] = {}

    def start(self, command: list[str], **kwargs: Any) -> subprocess.Popen[Any]:
        if os.name == "posix":
            kwargs.setdefault("start_new_session", True)
        process = subprocess.Popen(command, **kwargs)
        process._cliptalk_owned_group = bool(os.name == "posix" and kwargs.get("start_new_session"))
        with self._lock:
            self._processes[process.pid] = process
        return process

    def forget(self, process: subprocess.Popen[Any] | None) -> None:
        if process is None:
            return
        with self._lock:
            self._processes.pop(getattr(process, "pid", None), None)

    def terminate(self, process: subprocess.Popen[Any] | None, timeout: float = 3.0) -> None:
        if process is None:
            return
        try:
            if process.poll() is None:
                if getattr(process, "_cliptalk_owned_group", False) is True:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                else:
                    process.terminate()
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    if getattr(process, "_cliptalk_owned_group", False) is True:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    else:
                        process.kill()
                    process.wait(timeout=timeout)
        finally:
            self.forget(process)

    def shutdown(self) -> None:
        with self._lock:
            processes = list(self._processes.values())
        for process in processes:
            self.terminate(process)


process_supervisor = ProcessSupervisor()
