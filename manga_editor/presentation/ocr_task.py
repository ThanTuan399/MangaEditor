from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

from manga_editor.ocr.base import OcrRequest, OcrResult


@dataclass(frozen=True, slots=True)
class OcrTarget:
    page_id: str
    region_id: str
    input_revision: int


class OcrTask(QThread):
    progress = Signal(str)
    completed = Signal(object, object)
    failed = Signal(object, str)

    def __init__(self, engine, request: OcrRequest, target: OcrTarget):
        super().__init__()
        self.engine = engine
        self.request = request
        self.target = target

    def run(self) -> None:
        try:
            self.progress.emit("Đang chạy OCR…")
            result: OcrResult = self.engine.recognize(self.request)
            self.completed.emit(self.target, result)
        except Exception as exc:
            self.failed.emit(self.target, str(exc))
