from __future__ import annotations

import hashlib
import shutil
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "data" / "models" / "recognition"
MODELS = {
    "object_detection_yolox_2022nov.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/main/models/object_detection_yolox/"
        "object_detection_yolox_2022nov.onnx"
    ),
    "person_reid_youtu_2021nov.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/main/models/person_reid_youtureid/"
        "person_reid_youtu_2021nov.onnx"
    ),
}


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for filename, url in MODELS.items():
        destination = TARGET / filename
        if destination.is_file() and destination.stat().st_size > 1_000_000:
            print(f"ready {filename} {destination.stat().st_size} bytes")
            continue
        temporary = destination.with_suffix(".download")
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        temporary.replace(destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        print(f"downloaded {filename} sha256={digest}")


if __name__ == "__main__":
    main()
