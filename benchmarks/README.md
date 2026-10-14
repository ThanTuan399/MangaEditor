# Bộ kiểm thử OCR MangaEditor

Thư mục này chỉ chứa mô tả định dạng. Không đưa ảnh manga có bản quyền vào repository nếu bạn không có quyền chia sẻ.

Một dataset thật có dạng:

```text
my-benchmark/
  manifest.json
  images/
    sample_....png
```

`manifest.json`:

```json
{
  "format_version": 1,
  "description": "Japanese manga OCR benchmark",
  "samples": [
    {
      "id": "sample_001",
      "image": "images/sample_001.png",
      "truth": "本当に？",
      "language": "ja",
      "layout": "vertical",
      "tags": ["clean_balloon", "clear"],
      "notes": ""
    }
  ]
}
```

Nên chia tag theo các nhóm đã nêu trong roadmap:

- ngôn ngữ;
- chữ ngang / chữ dọc;
- bong bóng sạch / nền phức tạp;
- chữ thường / chữ cách điệu;
- ảnh rõ / nhỏ / mờ.

Chạy benchmark:

```powershell
python -m manga_editor.ocr.benchmark D:\OCRBench --engine tesseract --preprocess original
python -m manga_editor.ocr.benchmark D:\OCRBench --engine tesseract --preprocess manga_clean
python -m manga_editor.ocr.benchmark D:\OCRBench --engine mangaocr --preprocess original
```

So sánh bằng CER và thời gian xử lý. Không so confidence giữa các engine như thể chúng dùng cùng một thang đo.
