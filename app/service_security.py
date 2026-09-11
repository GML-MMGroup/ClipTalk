"""Independent Agent credentials and approved plugin source fingerprints."""
from __future__ import annotations

import hashlib
import os
import secrets
import tempfile
from pathlib import Path


def service_token(path: Path) -> str:
    configured = os.environ.get("CLIPTALK_AGENT_SERVICE_TOKEN", "").strip()
    if configured:
        if len(configured) < 32:
            raise ValueError("CLIPTALK_AGENT_SERVICE_TOKEN 至少需要 32 个字符")
        return configured
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        descriptor, temporary = tempfile.mkstemp(prefix=".agent-token-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w") as stream:
                stream.write(secrets.token_hex(32))
            try:
                os.link(temporary, path)  # Atomic create: never publish partial credentials.
            except FileExistsError:
                pass
        finally:
            Path(temporary).unlink(missing_ok=True)
    token = path.read_text().strip()
    if len(token) < 32:
        raise ValueError("Agent 服务凭据无效，请检查 service-token 文件")
    return token


def plugin_tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    files = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if "node_modules" in relative.parts:
            continue
        if path.is_symlink():
            raise ValueError("Plugin 包不能包含符号链接")
        if path.is_file():
            files.append((relative.as_posix(), path))
    for name, path in sorted(files):
        digest.update(name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).hexdigest().encode() + b"\0")
    return digest.hexdigest()
