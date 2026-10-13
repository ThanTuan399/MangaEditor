# MangaEditor — v0.3

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
- Người dùng chọn Region và `ocr_area` trước.
- Ảnh cắt OCR lấy từ raw, không từ preview đã chỉnh.
- Engine ban đầu: Tesseract adapter.
- Ngôn ngữ: Nhật, Anh, Trung giản/phồn thể, Hàn, Việt.
- Bố cục: tự động/khối, ngang, dọc.
- OCR chạy bằng QThread, UI không bị khóa.
- Kết quả máy và bản đã sửa lưu riêng.
- Có ảnh preview vùng OCR.
- Có nút lưu bản sửa, đánh dấu đã duyệt, dùng lại kết quả máy và sao chép chữ gốc.
- Kết quả task gắn `page_id + region_id + ocr_input_revision`; kết quả stale bị từ chối.
- Quét lại không tự ghi đè văn bản người dùng đã sửa.
- Project format v3, tự migration v1/v2 → v3.

## Tesseract trên Windows

App tự tìm:

```text
PATH
C:\Program Files\Tesseract-OCR\tesseract.exe
C:\Program Files (x86)\Tesseract-OCR\tesseract.exe
```

Hoặc đặt:

```powershell
$env:TESSERACT_CMD="C:\Program Files\Tesseract-OCR\tesseract.exe"
```

Cần cài language data tương ứng; ví dụ OCR tiếng Nhật dọc cần `jpn_vert`.

## Chạy

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

## Test

```powershell
python -m unittest discover -s tests -v
```

GitHub Actions chạy compile, unit test, renderer, OCR task và UI smoke test.

## Tài liệu
- `docs/V0_FOUNDATION.md`
- `docs/V0_1.md`
- `docs/V0_2.md`
- `docs/V0_3.md`
