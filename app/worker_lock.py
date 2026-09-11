"""The in-memory workspace requires one application process per data directory."""
from __future__ import annotations

import fcntl
from pathlib import Path


class WorkerLock:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = path.open("a+")
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.handle.close()
            raise RuntimeError("此数据目录已有 ClipTalk 实例运行；请使用单 worker，禁止多个进程共享工作区") from error

    def close(self) -> None:
        self.handle.close()
