#!/usr/bin/env python3
"""Download and validate the speech models used by ClipTalk.

Run this once after installing requirements-audiovisual.txt.  FunASR performs
the actual ModelScope downloads; loading every configured component also
proves that the selected PyTorch runtime can execute on the chosen device.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings  # noqa: E402
from app.speech import _sensevoice_instance  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="下载并验证 ClipTalk 的 SenseVoice、VAD 和可选说话人模型",
    )
    parser.add_argument(
        "--device",
        default="",
        help="cpu、cuda:0 或 auto；默认读取 HIGHLIGHT_SENSEVOICE_DEVICE",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=None,
        help="模型缓存目录；默认读取 HIGHLIGHT_SPEECH_MODEL_CACHE",
    )
    parser.add_argument(
        "--with-speakers",
        action="store_true",
        help="同时准备 CAM++ 说话人模型",
    )
    args = parser.parse_args()

    settings = Settings.from_environment()
    cache = (args.cache or settings.speech_model_cache).expanduser().resolve()
    device = args.device.strip() or settings.sensevoice_device
    diarization = bool(args.with_speakers or settings.sensevoice_diarization)
    cache.mkdir(parents=True, exist_ok=True)
    free_gib = shutil.disk_usage(cache).free / 1024**3

    components = [settings.sensevoice_model, settings.sensevoice_vad_model]
    if settings.sensevoice_punc_model:
        components.append(settings.sensevoice_punc_model)
    if diarization:
        components.append(settings.sensevoice_spk_model)

    print("ClipTalk speech model preparation")
    print(f"  cache: {cache}")
    print(f"  requested device: {device}")
    print(f"  free disk: {free_gib:.1f} GiB")
    print(f"  components: {', '.join(components)}")
    print("  missing components will be downloaded from ModelScope")

    if free_gib < 2.0:
        print("error: at least 2 GiB of free disk space is recommended", file=sys.stderr)
        return 2

    try:
        import torch
    except ImportError:
        print(
            "error: PyTorch is not installed; use requirements-audiovisual.txt "
            "for CPU or requirements-audiovisual-cu121.txt for CUDA 12.1",
            file=sys.stderr,
        )
        return 2

    print(f"  torch: {torch.__version__}")
    try:
        _, actual_device = _sensevoice_instance(
            model_name=settings.sensevoice_model,
            device=device,
            vad_model=settings.sensevoice_vad_model,
            punc_model=settings.sensevoice_punc_model,
            spk_model=settings.sensevoice_spk_model,
            diarization=diarization,
            model_cache=cache,
        )
    except Exception as error:
        print(f"error: speech model preparation failed: {error}", file=sys.stderr)
        return 1

    print(f"ready: all speech components loaded successfully on {actual_device}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
