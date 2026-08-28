#!/usr/bin/env python3
"""Import-only container smoke test; never downloads model weights."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


REQUIRED_MODULES = (
    "fastapi", "uvicorn", "httpx", "multipart", "pydantic", "starlette",
    "cryptography", "cv2", "PIL", "numpy", "scipy", "sklearn", "funasr",
    "faster_whisper", "ctranslate2", "torch", "torchaudio", "transformers",
    "safetensors", "sentencepiece", "paddle", "paddleocr",
)


def main() -> int:
    profile = os.environ.get("CLIPTALK_INSTALL_PROFILE", "cpu")
    if profile not in {"cpu", "gpu"}:
        raise RuntimeError(f"unsupported CLIPTALK_INSTALL_PROFILE: {profile}")
    versions: dict[str, str] = {}
    for name in REQUIRED_MODULES:
        module = importlib.import_module(name)
        versions[name] = str(getattr(module, "__version__", "installed"))
    from app.main import app

    assert app.title == "ClipTalk Video Editor"
    print(json.dumps({"ok": True, "profile": profile, "modules": versions}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
