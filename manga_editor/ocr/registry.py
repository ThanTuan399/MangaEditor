from __future__ import annotations

from .mangaocr import MangaOcrEngine
from .tesseract import TesseractEngine


class OcrEngineRegistry:
    def __init__(self):
        self._engines = {
            "tesseract": TesseractEngine(),
            "mangaocr": MangaOcrEngine(),
        }

    def get(self, key: str):
        if key not in self._engines:
            raise KeyError(key)
        return self._engines[key]

    def availability(self) -> dict[str, bool]:
        return {
            key: engine.is_available()
            for key, engine in self._engines.items()
        }
