from __future__ import annotations

from dataclasses import replace
import time

from .base import OcrEngineError, OcrRequest, OcrResult
from .layout import segment_vertical_columns
from .preprocess import prepare_image
from .quality import analyze_suspicions
from .registry import OcrEngineRegistry


class OcrPipeline:
    name = "pipeline"

    def __init__(self, registry: OcrEngineRegistry | None = None):
        self.registry = registry or OcrEngineRegistry()

    def is_available(self) -> bool:
        return any(self.registry.availability().values())

    def recognize(self, request: OcrRequest) -> OcrResult:
        preference = str(request.options.get("engine", "auto"))
        profile = str(request.options.get("preprocess", "original"))
        prepared = prepare_image(request.image_bytes, profile)

        engine_keys = self._engine_order(preference, request.language)
        errors: list[str] = []

        for index, key in enumerate(engine_keys):
            engine = self.registry.get(key)
            if not engine.is_available():
                errors.append(f"{key}: chưa sẵn sàng")
                continue

            try:
                started = time.perf_counter()
                result = self._recognize_with_engine(
                    key,
                    engine,
                    replace(request, image_bytes=prepared.png_bytes),
                )
                duration_ms = int((time.perf_counter() - started) * 1000)
            except Exception as exc:
                errors.append(f"{key}: {exc}")
                continue

            suspicions = analyze_suspicions(
                result,
                language=request.language,
                layout=request.layout,
            )
            metadata = dict(result.metadata)
            metadata.update(prepared.metadata)
            metadata.update({
                "engine_preference": preference,
                "engine_attempt": index + 1,
                "duration_ms": duration_ms,
                "suspicions": list(suspicions),
            })

            warning_parts = [part for part in [result.warning] if part]
            if suspicions:
                warning_parts.append(" ".join(suspicions))
            if errors:
                warning_parts.append(
                    "Fallback đã được dùng sau lỗi: " + " | ".join(errors)
                )

            final = replace(
                result,
                warning=" ".join(warning_parts).strip(),
                metadata=metadata,
            )

            # Auto chỉ fallback khi engine không chạy hoặc trả rỗng.
            # Không so confidence giữa các engine khác nhau.
            if preference == "auto" and not final.text.strip():
                errors.append(f"{key}: kết quả rỗng")
                continue
            return final

        raise OcrEngineError(
            "Không engine OCR nào hoàn thành được tác vụ. "
            + (" | ".join(errors) if errors else "")
        )

    def _recognize_with_engine(self, key: str, engine, request: OcrRequest) -> OcrResult:
        if (
            key == "tesseract"
            and request.language == "ja"
            and request.layout == "vertical"
        ):
            segments = segment_vertical_columns(request.image_bytes)
            if len(segments) > 1:
                texts = []
                confidences = []
                warnings = []
                for segment in segments:
                    result = engine.recognize(
                        replace(request, image_bytes=segment.png_bytes)
                    )
                    if result.text.strip():
                        texts.append(result.text.strip())
                    if result.confidence is not None:
                        confidences.append(result.confidence)
                    if result.warning:
                        warnings.append(result.warning)
                return OcrResult(
                    text="\n".join(texts),
                    engine=engine.name,
                    language=request.language,
                    layout=request.layout,
                    warning=" ".join(warnings),
                    confidence=(
                        sum(confidences) / len(confidences)
                        if confidences else None
                    ),
                    metadata={
                        "column_count": len(segments),
                        "column_order": "right_to_left",
                    },
                )
        return engine.recognize(request)

    @staticmethod
    def _engine_order(preference: str, language: str) -> list[str]:
        if preference == "tesseract":
            return ["tesseract"]
        if preference == "mangaocr":
            return ["mangaocr"]
        if preference != "auto":
            raise OcrEngineError(f"Engine preference không hợp lệ: {preference}")
        if language == "ja":
            return ["tesseract", "mangaocr"]
        return ["tesseract"]
