# MangaEditor — v0.4

MangaEditor được dựng lại theo hướng **Region là đơn vị trung tâm, raw không bị phá, OCR/patch/chữ đều gắn bằng ID**.

## Đã hoàn thành

### V0 Foundation
- Project / Page / Region có ID cố định.
- Ba phạm vi độc lập: OCR, xóa chữ, khung chữ Việt.
- Tọa độ ảnh gốc.
- Save/load có version + checksum raw.
- Undo/redo qua ProjectSession.

### v0.1 — Một trang đơn giản
- Patch nền trắng/màu trên layer riêng.
- Chữ Việt chỉnh được.
- Ẩn/hiện layer.
- Xuất ảnh đúng kích thước raw.

### v0.2 — Region độc lập
- Hai Region sát/chạm nhau không tự gộp.
- Một Region có nhiều mảng xóa.
- Chọn ảnh ↔ nội dung hai chiều.
- Tách/gộp chủ động.
- Trạng thái Nền/Chữ riêng.
- Migration project v1 → v2.

### v0.3 — OCR theo Region
- Chọn Region + `ocr_area` trước khi OCR.
- Crop OCR luôn lấy từ raw.
- Tesseract adapter.
- OCR chạy QThread.
- Kết quả máy và bản người dùng sửa lưu riêng.
- `page_id + region_id + ocr_input_revision` chống ghi nhầm/stale.
- Project format v3.

### v0.4 — OCR manga có đo lường
- `OcrPipeline` tách UI khỏi engine/preprocess.
- Engine:
  - Tesseract;
  - Manga OCR tùy chọn cho tiếng Nhật;
  - Auto fallback.
- Profile chuẩn bị ảnh:
  - original;
  - upscale2x;
  - contrast;
  - manga_clean.
- Hiển thị song song crop RAW và ảnh sau preprocess.
- Tesseract tiếng Nhật dọc có thử tách cột và xử lý phải → trái.
- Cảnh báo kết quả đáng nghi nhưng không tự sửa câu.
- Region lưu engine preference, preprocess, warning/suspicion và metadata.
- Có nút đưa Region đã duyệt vào dataset benchmark.
- Benchmark CLI đo:
  - CER;
  - compact CER;
  - số phép sửa ký tự;
  - bỏ sót dòng;
  - thứ tự đọc;
  - thời gian xử lý;
  - nhóm language/layout/tag.
- Project format v4; migration tuần tự v1 → v4.

## Cài đặt cơ bản

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

## Tesseract trên Windows

App tự tìm:

```text
PATH
C:\Program Files\Tesseract-OCR\tesseract.exe
C:\Program Files (x86)\Tesseract-OCR\tesseract.exe
```

Hoặc:

```powershell
$env:TESSERACT_CMD="C:\Program Files\Tesseract-OCR\tesseract.exe"
```

OCR tiếng Nhật dọc bằng Tesseract cần language data `jpn_vert`.

## Manga OCR tùy chọn

Không nằm trong `requirements.txt` mặc định.

```powershell
python -m pip install manga-ocr
```

hoặc:

```powershell
python -m pip install -e ".[mangaocr]"
```

Trong app chọn:

```text
Engine → Manga OCR
```

hoặc:

```text
Engine → Tự động fallback
```

## Benchmark OCR

Từ app, chọn Region đã có bản OCR sửa/xác nhận rồi bấm:

```text
Thêm Region vào bộ test OCR
```

Sau khi có dataset:

```powershell
python -m manga_editor.ocr.benchmark D:\OCRBench --engine tesseract --preprocess original
python -m manga_editor.ocr.benchmark D:\OCRBench --engine tesseract --preprocess manga_clean
python -m manga_editor.ocr.benchmark D:\OCRBench --engine mangaocr --preprocess original
```

Xem schema tại `benchmarks/README.md`.

Không so confidence giữa các engine như thể chúng dùng cùng một thang đo. Dùng ground truth, CER, bỏ sót, thứ tự đọc và công sửa để đánh giá.

## Test

```powershell
python -m unittest discover -s tests -v
```

GitHub Actions chạy compile, unit test, renderer, OCR task, benchmark logic và UI smoke test.

## Tài liệu
- `docs/V0_FOUNDATION.md`
- `docs/V0_1.md`
- `docs/V0_2.md`
- `docs/V0_3.md`
- `docs/V0_4.md`
