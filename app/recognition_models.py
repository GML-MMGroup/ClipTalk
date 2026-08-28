from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image


_model_lock = threading.RLock()
_models: dict[tuple[str, str, str], Any] = {}


def _torch_device(requested: str = "auto") -> str:
    import torch

    value = str(requested or "auto").lower()
    if value == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if value.startswith("cuda") and not torch.cuda.is_available():
        return "cpu"
    return value


def _normalise_rows(values: Any) -> np.ndarray:
    matrix = np.asarray(values, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)


class SiglipEncoder:
    def __init__(self, model_id: str, *, device: str = "auto", cache_dir: Path | None = None) -> None:
        from transformers import AutoModel, AutoProcessor

        self.device = _torch_device(device)
        key = ("siglip", model_id, self.device)
        with _model_lock:
            loaded = _models.get(key)
            if loaded is None:
                processor = AutoProcessor.from_pretrained(model_id, cache_dir=str(cache_dir) if cache_dir else None)
                model = AutoModel.from_pretrained(model_id, cache_dir=str(cache_dir) if cache_dir else None).eval().to(self.device)
                loaded = (processor, model)
                _models[key] = loaded
        self.processor, self.model = loaded

    def encode_images(self, paths: Iterable[Path], *, batch_size: int = 16) -> np.ndarray:
        import torch

        path_list = list(paths)
        rows: list[np.ndarray] = []
        for position in range(0, len(path_list), max(1, batch_size)):
            images = []
            for path in path_list[position:position + batch_size]:
                with Image.open(path) as source:
                    images.append(source.convert("RGB").copy())
            inputs = self.processor(images=images, return_tensors="pt").to(self.device)
            with torch.inference_mode():
                features = self.model.get_image_features(**inputs)
            rows.append(features.detach().float().cpu().numpy())
        return _normalise_rows(np.concatenate(rows, axis=0)) if rows else np.empty((0, 0), dtype=np.float32)

    def encode_texts(self, texts: Iterable[str], *, batch_size: int = 32) -> np.ndarray:
        import torch

        values = list(texts)
        rows: list[np.ndarray] = []
        for position in range(0, len(values), max(1, batch_size)):
            inputs = self.processor(
                text=values[position:position + batch_size], padding="max_length", max_length=64,
                truncation=True, return_tensors="pt",
            ).to(self.device)
            with torch.inference_mode():
                features = self.model.get_text_features(**inputs)
            rows.append(features.detach().float().cpu().numpy())
        return _normalise_rows(np.concatenate(rows, axis=0)) if rows else np.empty((0, 0), dtype=np.float32)


class TextEncoder:
    """Multilingual E5-compatible encoder for transcript and OCR retrieval."""

    def __init__(self, model_id: str, *, device: str = "auto", cache_dir: Path | None = None) -> None:
        from transformers import AutoModel, AutoTokenizer

        self.device = _torch_device(device)
        key = ("text", model_id, self.device)
        with _model_lock:
            loaded = _models.get(key)
            if loaded is None:
                tokenizer = AutoTokenizer.from_pretrained(model_id, cache_dir=str(cache_dir) if cache_dir else None)
                model = AutoModel.from_pretrained(model_id, cache_dir=str(cache_dir) if cache_dir else None).eval().to(self.device)
                loaded = (tokenizer, model)
                _models[key] = loaded
        self.tokenizer, self.model = loaded

    def encode_texts(
        self, texts: Iterable[str], *, query: bool = False, batch_size: int = 32,
    ) -> np.ndarray:
        import torch

        prefix = "query: " if query else "passage: "
        values = [prefix + str(value) for value in texts]
        rows: list[np.ndarray] = []
        for position in range(0, len(values), max(1, batch_size)):
            inputs = self.tokenizer(
                values[position:position + batch_size], padding=True, truncation=True,
                max_length=512, return_tensors="pt",
            ).to(self.device)
            with torch.inference_mode():
                hidden = self.model(**inputs).last_hidden_state
                mask = inputs["attention_mask"].unsqueeze(-1).expand(hidden.size()).float()
                pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            rows.append(pooled.detach().float().cpu().numpy())
        return _normalise_rows(np.concatenate(rows, axis=0)) if rows else np.empty((0, 0), dtype=np.float32)

class ClapEncoder:
    def __init__(self, model_id: str, *, device: str = "auto", cache_dir: Path | None = None) -> None:
        from transformers import AutoModel, AutoProcessor

        self.device = _torch_device(device)
        key = ("clap", model_id, self.device)
        with _model_lock:
            loaded = _models.get(key)
            if loaded is None:
                processor = AutoProcessor.from_pretrained(model_id, cache_dir=str(cache_dir) if cache_dir else None)
                model = AutoModel.from_pretrained(model_id, cache_dir=str(cache_dir) if cache_dir else None).eval().to(self.device)
                loaded = (processor, model)
                _models[key] = loaded
        self.processor, self.model = loaded

    def encode_audio(self, waveforms: Iterable[np.ndarray], *, sampling_rate: int = 48000, batch_size: int = 8) -> np.ndarray:
        import torch

        values = [np.asarray(value, dtype=np.float32) for value in waveforms]
        rows: list[np.ndarray] = []
        for position in range(0, len(values), max(1, batch_size)):
            inputs = self.processor(audio=values[position:position + batch_size], sampling_rate=sampling_rate, return_tensors="pt", padding=True).to(self.device)
            with torch.inference_mode():
                features = self.model.get_audio_features(**inputs)
            rows.append(features.detach().float().cpu().numpy())
        return _normalise_rows(np.concatenate(rows, axis=0)) if rows else np.empty((0, 0), dtype=np.float32)

    def encode_texts(self, texts: Iterable[str]) -> np.ndarray:
        import torch

        values = list(texts)
        inputs = self.processor(text=values, return_tensors="pt", padding=True).to(self.device)
        with torch.inference_mode():
            features = self.model.get_text_features(**inputs)
        return _normalise_rows(features.detach().float().cpu().numpy())


def _ocr_result_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    payload = getattr(result, "json", None)
    if callable(payload):
        payload = payload()
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = None
    return payload if isinstance(payload, dict) else {}


def _first_result_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return []


class PaddleOcrEngine:
    def __init__(self, *, device: str = "auto", cache_dir: Path | None = None) -> None:
        if cache_dir is not None:
            os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(Path(cache_dir) / "paddlex"))
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        from paddleocr import PaddleOCR

        actual = "gpu:0" if _torch_device(device).startswith("cuda") else "cpu"
        key = ("paddleocr", "PP-OCRv6", actual)
        with _model_lock:
            engine = _models.get(key)
            if engine is None:
                try:
                    engine = PaddleOCR(
                        ocr_version="PP-OCRv6", lang="ch", device=actual,
                        use_doc_orientation_classify=False, use_doc_unwarping=False,
                        use_textline_orientation=False,
                    )
                except (TypeError, ValueError):
                    engine = PaddleOCR(lang="ch", use_angle_cls=False)
                _models[key] = engine
        self.engine = engine

    def recognize(self, paths: Iterable[Path], times: Iterable[float]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path, time_value in zip(paths, times):
            try:
                results = self.engine.predict(str(path))
            except AttributeError:
                results = self.engine.ocr(str(path), cls=False)
            for result in results or []:
                payload = _ocr_result_payload(result)
                data = payload.get("res") if isinstance(payload.get("res"), dict) else payload
                texts = _first_result_value(data, "rec_texts", "texts")
                scores = _first_result_value(data, "rec_scores", "scores")
                boxes = _first_result_value(data, "rec_boxes", "boxes")
                if len(texts):
                    for index, text in enumerate(texts):
                        box = boxes[index] if index < len(boxes) else []
                        flat = np.asarray(box).reshape(-1).tolist() if len(box) else []
                        if len(flat) >= 4:
                            xs, ys = flat[0::2], flat[1::2]
                            flat = [min(xs), min(ys), max(xs), max(ys)]
                        rows.append({"time": float(time_value), "text": str(text), "confidence": float(scores[index]) if index < len(scores) else .5, "box": flat})
                    continue
                # PaddleOCR 2.x fallback shape: [[box, (text, score)], ...]
                legacy = result if isinstance(result, list) else []
                for item in legacy:
                    if not isinstance(item, (list, tuple)) or len(item) < 2:
                        continue
                    box, prediction = item[0], item[1]
                    if not isinstance(prediction, (list, tuple)) or not prediction:
                        continue
                    points = np.asarray(box, dtype=np.float32)
                    rows.append({
                        "time": float(time_value), "text": str(prediction[0]),
                        "confidence": float(prediction[1]) if len(prediction) > 1 else .5,
                        "box": [float(points[:, 0].min()), float(points[:, 1].min()), float(points[:, 0].max()), float(points[:, 1].max())],
                    })
        return rows


class AnonymousFaceEngine:
    def __init__(self, yunet_model: Path, sface_model: Path, *, device: str = "auto") -> None:
        import cv2

        use_cuda = _torch_device(device).startswith("cuda") and hasattr(cv2.dnn, "DNN_TARGET_CUDA")
        backend = cv2.dnn.DNN_BACKEND_CUDA if use_cuda else cv2.dnn.DNN_BACKEND_OPENCV
        target = cv2.dnn.DNN_TARGET_CUDA_FP16 if use_cuda else cv2.dnn.DNN_TARGET_CPU
        self.detector = cv2.FaceDetectorYN.create(str(yunet_model), "", (320, 320), .9, .3, 5000, backend, target)
        self.recognizer = cv2.FaceRecognizerSF.create(str(sface_model), "", backend, target)

    def detect(self, path: Path, *, time_value: float) -> list[dict[str, Any]]:
        import cv2

        image = cv2.imread(str(path))
        if image is None:
            return []
        self.detector.setInputSize((image.shape[1], image.shape[0]))
        _, faces = self.detector.detect(image)
        rows: list[dict[str, Any]] = []
        for index, face in enumerate(faces if faces is not None else []):
            aligned = self.recognizer.alignCrop(image, face)
            embedding = self.recognizer.feature(aligned).reshape(-1).astype(np.float32)
            embedding /= max(float(np.linalg.norm(embedding)), 1e-12)
            x, y, width, height = map(float, face[:4])
            rows.append({
                "id": f"face_{time_value:.3f}_{index}", "start": float(time_value), "end": float(time_value),
                "box": [x, y, x + width, y + height], "confidence": float(face[-1]),
                "frameWidth": int(image.shape[1]), "frameHeight": int(image.shape[0]),
                "coordinateSpace": "recognition_frame",
                "embedding": embedding.tolist(),
            })
        return rows


class AnonymousBodyEngine:
    """OpenCV Zoo YOLOX person detector plus YoutuReID body embedding.

    The detector is deliberately class-filtered before any identity decision;
    embeddings are anonymous and remain local to a single source video.
    """

    def __init__(self, yolox_model: Path, reid_model: Path, *, device: str = "auto") -> None:
        import cv2

        use_cuda = _torch_device(device).startswith("cuda") and hasattr(cv2.dnn, "DNN_TARGET_CUDA")
        backend = cv2.dnn.DNN_BACKEND_CUDA if use_cuda else cv2.dnn.DNN_BACKEND_OPENCV
        target = cv2.dnn.DNN_TARGET_CUDA_FP16 if use_cuda else cv2.dnn.DNN_TARGET_CPU
        self.detector = cv2.dnn.readNet(str(yolox_model))
        self.reid = cv2.dnn.readNet(str(reid_model))
        for model in (self.detector, self.reid):
            model.setPreferableBackend(backend)
            model.setPreferableTarget(target)
        grids, expanded = [], []
        for stride in (8, 16, 32):
            size = 640 // stride
            xv, yv = np.meshgrid(np.arange(size), np.arange(size))
            grid = np.stack((xv, yv), 2).reshape(1, -1, 2)
            grids.append(grid)
            expanded.append(np.full((*grid.shape[:2], 1), stride))
        self.grids = np.concatenate(grids, axis=1)
        self.expanded_strides = np.concatenate(expanded, axis=1)

    def _embedding(self, crop: Any) -> list[float]:
        import cv2

        resized = cv2.resize(crop, (128, 256), interpolation=cv2.INTER_LINEAR)
        rgb = resized[:, :, ::-1].astype(np.float32) / 255.0
        rgb = (rgb - np.asarray((.485, .456, .406), dtype=np.float32)) / np.asarray((.229, .224, .225), dtype=np.float32)
        self.reid.setInput(cv2.dnn.blobFromImage(rgb))
        embedding = self.reid.forward().reshape(-1).astype(np.float32)
        embedding /= max(float(np.linalg.norm(embedding)), 1e-12)
        return embedding.tolist()

    def detect(self, path: Path, *, time_value: float) -> list[dict[str, Any]]:
        import cv2

        image = cv2.imread(str(path))
        if image is None:
            return []
        height, width = image.shape[:2]
        ratio = min(640 / max(1, height), 640 / max(1, width))
        resized = cv2.resize(image, (int(width * ratio), int(height * ratio)), interpolation=cv2.INTER_LINEAR)
        padded = np.full((640, 640, 3), 114, dtype=np.float32)
        padded[:resized.shape[0], :resized.shape[1]] = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        self.detector.setInput(np.transpose(padded, (2, 0, 1))[None])
        output = self.detector.forward(self.detector.getUnconnectedOutLayersNames())[0][0].copy()
        output[:, :2] = (output[:, :2] + self.grids[0]) * self.expanded_strides[0]
        output[:, 2:4] = np.exp(output[:, 2:4]) * self.expanded_strides[0]
        scores = output[:, 4] * output[:, 5]  # COCO class zero is person.
        keep = np.where(scores >= .35)[0]
        if not len(keep):
            return []
        boxes: list[list[float]] = []
        confidences: list[float] = []
        for index in keep:
            center_x, center_y, box_width, box_height = output[index, :4]
            boxes.append([
                float((center_x - box_width / 2) / ratio),
                float((center_y - box_height / 2) / ratio),
                float(box_width / ratio), float(box_height / ratio),
            ])
            confidences.append(float(scores[index]))
        retained = cv2.dnn.NMSBoxes(boxes, confidences, .35, .5)
        rows: list[dict[str, Any]] = []
        for position, raw_index in enumerate(np.asarray(retained).reshape(-1).tolist() if len(retained) else []):
            x, y, box_width, box_height = boxes[int(raw_index)]
            x1, y1 = max(0, int(x)), max(0, int(y))
            x2, y2 = min(width, int(x + box_width)), min(height, int(y + box_height))
            if x2 - x1 < 16 or y2 - y1 < 32:
                continue
            crop = image[y1:y2, x1:x2]
            rows.append({
                "id": f"body_{time_value:.3f}_{position}", "start": float(time_value), "end": float(time_value),
                "box": [float(x1), float(y1), float(x2), float(y2)],
                "confidence": confidences[int(raw_index)], "embedding": self._embedding(crop),
                "frameWidth": int(width), "frameHeight": int(height),
                "coordinateSpace": "recognition_frame", "observationType": "body",
            })
        return rows


class GroundingDinoEngine:
    def __init__(self, model_id: str, *, device: str = "auto", cache_dir: Path | None = None) -> None:
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

        self.device = _torch_device(device)
        key = ("grounding", model_id, self.device)
        with _model_lock:
            loaded = _models.get(key)
            if loaded is None:
                processor = AutoProcessor.from_pretrained(model_id, cache_dir=str(cache_dir) if cache_dir else None)
                model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id, cache_dir=str(cache_dir) if cache_dir else None).eval().to(self.device)
                loaded = (processor, model)
                _models[key] = loaded
        self.processor, self.model = loaded

    def detect(self, path: Path, labels: list[str], *, threshold: float = .3) -> list[dict[str, Any]]:
        import torch

        with Image.open(path) as source:
            image = source.convert("RGB")
        text = ". ".join(value.strip(" .") for value in labels if value.strip()) + "."
        inputs = self.processor(images=image, text=text, return_tensors="pt").to(self.device)
        with torch.inference_mode():
            outputs = self.model(**inputs)
        result = self.processor.post_process_grounded_object_detection(
            outputs, inputs.input_ids, threshold=threshold, text_threshold=threshold,
            target_sizes=[image.size[::-1]],
        )[0]
        return [
            {"label": str(label), "score": float(score), "box": [round(float(value), 2) for value in box.tolist()]}
            for label, score, box in zip(result["labels"], result["scores"], result["boxes"])
        ]
