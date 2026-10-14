from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile

from .base import OcrEngineError, OcrRequest, OcrResult


class MangaOcrEngine:
    name = "mangaocr"

    def __init__(self):
        self._model = None

    def is_available(self) -> bool:
        return importlib.util.find_spec("manga_ocr") is not None

    def recognize(self, request: OcrRequest) -> OcrResult:
        if request.language != "ja":
            raise OcrEngineError("Manga OCR ở v0.4 chỉ dùng cho tiếng Nhật.")
        if not self.is_available():
            raise OcrEngineError(
                "Chưa cài manga-ocr. Có thể cài bằng: pip install manga-ocr"
            )

        try:
            from manga_ocr import MangaOcr
        except Exception as exc:
            raise OcrEngineError(f"Không import được manga-ocr: {exc}") from exc

        try:
            if self._model is None:
                self._model = MangaOcr()
            with tempfile.TemporaryDirectory(prefix="mangaeditor-mocr-") as directory:
                path = Path(directory) / "crop.png"
                path.write_bytes(request.image_bytes)
                text = str(self._model(str(path))).strip()
        except Exception as exc:
            raise OcrEngineError(f"Manga OCR thất bại: {exc}") from exc

        warning = ""
        if not text:
            warning = "Manga OCR không nhận diện được chữ trong vùng."
        return OcrResult(
            text=text,
            engine=self.name,
            language=request.language,
            layout=request.layout,
            warning=warning,
            confidence=None,
            metadata={"model": "manga-ocr"},
        )
