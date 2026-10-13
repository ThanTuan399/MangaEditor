from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class OcrEngineError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OcrRequest:
    image_bytes: bytes
    language: str
    layout: str = "auto"
    options: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OcrResult:
    text: str
    engine: str
    language: str
    layout: str
    warning: str = ""
    confidence: float | None = None
    metadata: dict = field(default_factory=dict)


class OcrEngine(Protocol):
    name: str

    def is_available(self) -> bool: ...

    def recognize(self, request: OcrRequest) -> OcrResult: ...
