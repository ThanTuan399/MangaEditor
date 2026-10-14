from __future__ import annotations

import re

from .base import OcrResult


_JAPANESE_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]"
)


def analyze_suspicions(
    result: OcrResult,
    *,
    language: str,
    layout: str,
) -> list[str]:
    text = result.text.strip()
    issues: list[str] = []

    if not text:
        issues.append("Không nhận diện được ký tự nào.")
        return issues

    if "\ufffd" in text:
        issues.append("Kết quả có ký tự thay thế Unicode, có thể bị lỗi giải mã.")

    if len(text) <= 1:
        issues.append("Kết quả quá ngắn; có thể OCR đã bỏ sót.")

    if language == "ja" and not _JAPANESE_RE.search(text):
        issues.append("Đang quét tiếng Nhật nhưng kết quả không có ký tự Nhật.")

    if result.engine == "tesseract" and result.confidence is not None:
        if result.confidence < 0.45:
            issues.append(
                "Confidence Tesseract thấp; nên kiểm tra ảnh cắt hoặc thử profile khác."
            )

    repeated = re.search(r"(.)\1{5,}", text)
    if repeated:
        issues.append("Có chuỗi ký tự lặp bất thường; nên kiểm tra kết quả.")

    column_count = int(result.metadata.get("column_count", 1) or 1)
    if layout == "vertical" and column_count > 1:
        nonempty_lines = [line for line in text.splitlines() if line.strip()]
        if len(nonempty_lines) < column_count:
            issues.append(
                "Có nhiều cột dọc nhưng một số cột không trả về văn bản."
            )

    return issues
