from __future__ import annotations

import csv
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .base import OcrEngineError, OcrRequest, OcrResult


LANGUAGE_MODELS = {
    "ja": ("jpn", "jpn_vert"),
    "en": ("eng", "eng"),
    "zh-Hans": ("chi_sim", "chi_sim"),
    "zh-Hant": ("chi_tra", "chi_tra"),
    "ko": ("kor", "kor"),
    "vi": ("vie", "vie"),
}


class TesseractEngine:
    name = "tesseract"

    def __init__(self, executable: str | None = None, timeout: int = 120):
        self.executable = self._resolve_executable(executable)
        self.timeout = timeout

    @staticmethod
    def _resolve_executable(explicit: str | None) -> str:
        if explicit:
            return explicit
        candidates = [
            os.environ.get("TESSERACT_CMD"),
            shutil.which("tesseract"),
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        for candidate in candidates:
            if not candidate:
                continue
            if shutil.which(candidate) or Path(candidate).exists():
                return str(candidate)
        return explicit or os.environ.get("TESSERACT_CMD") or "tesseract"

    def is_available(self) -> bool:
        return bool(
            shutil.which(self.executable)
            or Path(self.executable).exists()
        )

    def available_languages(self) -> set[str]:
        if not self.is_available():
            return set()
        try:
            proc = subprocess.run(
                [self.executable, "--list-langs"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except OSError:
            return set()
        lines = [line.strip() for line in proc.stdout.splitlines()]
        return {
            line
            for line in lines
            if line and not line.lower().startswith("list of available")
        }

    def recognize(self, request: OcrRequest) -> OcrResult:
        if not self.is_available():
            raise OcrEngineError(
                "Không tìm thấy Tesseract OCR. Hãy cài Tesseract và thêm thư mục "
                "có tesseract.exe vào PATH."
            )

        if request.language not in LANGUAGE_MODELS:
            raise OcrEngineError(
                f"Ngôn ngữ OCR chưa được hỗ trợ ở v0.3: {request.language}"
            )

        horizontal_model, vertical_model = LANGUAGE_MODELS[request.language]
        model = vertical_model if request.layout == "vertical" else horizontal_model
        available = self.available_languages()
        if model not in available:
            raise OcrEngineError(
                f"Tesseract chưa có gói ngôn ngữ '{model}'. "
                "Hãy cài language data tương ứng rồi quét lại."
            )

        psm = {
            "auto": "6",
            "horizontal": "6",
            "vertical": "5",
        }.get(request.layout, "6")

        with tempfile.TemporaryDirectory(prefix="mangaeditor-ocr-") as directory:
            root = Path(directory)
            source = root / "crop.png"
            output_base = root / "ocr"
            source.write_bytes(request.image_bytes)

            command = [
                self.executable,
                str(source),
                str(output_base),
                "-l",
                model,
                "--psm",
                psm,
                "txt",
                "tsv",
            ]
            try:
                proc = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise OcrEngineError(
                    f"OCR vượt quá {self.timeout} giây."
                ) from exc
            except OSError as exc:
                raise OcrEngineError(
                    f"Không chạy được Tesseract: {exc}"
                ) from exc

            if proc.returncode != 0:
                message = (proc.stderr or proc.stdout or "").strip()
                raise OcrEngineError(
                    message or f"Tesseract kết thúc với mã {proc.returncode}."
                )

            text_path = output_base.with_suffix(".txt")
            tsv_path = output_base.with_suffix(".tsv")
            text = (
                text_path.read_text(encoding="utf-8", errors="replace").strip()
                if text_path.exists()
                else ""
            )
            confidence = self._confidence_from_tsv(tsv_path)

            warning_parts = []
            stderr = proc.stderr.strip()
            if stderr:
                warning_parts.append(stderr)
            if not text:
                warning_parts.append("Không nhận diện được chữ trong vùng đã chọn.")

            return OcrResult(
                text=text,
                engine=self.name,
                language=request.language,
                layout=request.layout,
                warning=" ".join(warning_parts),
                confidence=confidence,
                metadata={
                    "model": model,
                    "psm": psm,
                },
            )

    @staticmethod
    def _confidence_from_tsv(path: Path) -> float | None:
        if not path.exists():
            return None
        try:
            rows = csv.DictReader(
                io.StringIO(
                    path.read_text(encoding="utf-8", errors="replace")
                ),
                delimiter="\t",
            )
            values = []
            for row in rows:
                text = (row.get("text") or "").strip()
                if not text:
                    continue
                try:
                    confidence = float(row.get("conf", "-1"))
                except ValueError:
                    continue
                if confidence >= 0:
                    values.append(confidence / 100.0)
            if not values:
                return None
            return sum(values) / len(values)
        except Exception:
            return None
