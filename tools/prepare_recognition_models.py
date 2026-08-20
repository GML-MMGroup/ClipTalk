#!/usr/bin/env python3
"""Prepare optional v4 recognition models without changing server startup."""

from __future__ import annotations

import argparse
import os
import urllib.request
from pathlib import Path


OPENCV_MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
        "face_detection_yunet_2023mar.onnx"
    ),
    "face_recognition_sface_2021dec.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/"
        "face_recognition_sface_2021dec.onnx"
    ),
}


def download(url: str, target: Path) -> None:
    if target.is_file() and target.stat().st_size > 1024:
        print(f"ready: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    urllib.request.urlretrieve(url, temporary)
    temporary.replace(target)
    print(f"downloaded: {target}")


def prefetch_huggingface(cache: Path, include_audio: bool, include_grounding: bool) -> None:
    from transformers import AutoModel, AutoProcessor

    models = [os.getenv("HIGHLIGHT_SIGLIP_MODEL", "google/siglip2-base-patch16-224")]
    if include_audio:
        models.append(os.getenv("HIGHLIGHT_CLAP_MODEL", "laion/clap-htsat-fused"))
    if include_grounding:
        models.append(os.getenv("HIGHLIGHT_GROUNDING_MODEL", "IDEA-Research/grounding-dino-tiny"))
    for model_id in models:
        print(f"preparing: {model_id}")
        AutoProcessor.from_pretrained(model_id, cache_dir=str(cache))
        AutoModel.from_pretrained(model_id, cache_dir=str(cache))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--prefetch", action="store_true", help="also prefetch SigLIP2")
    parser.add_argument("--audio", action="store_true", help="prefetch CLAP")
    parser.add_argument("--grounding", action="store_true", help="prefetch Grounding DINO")
    args = parser.parse_args()
    cache = args.data_root / "models" / "recognition"
    download(OPENCV_MODELS["face_detection_yunet_2023mar.onnx"], cache / "face_detection_yunet_2023mar.onnx")
    download(OPENCV_MODELS["face_recognition_sface_2021dec.onnx"], cache / "face_recognition_sface_2021dec.onnx")
    if args.prefetch or args.audio or args.grounding:
        prefetch_huggingface(cache, args.audio, args.grounding)


if __name__ == "__main__":
    main()
