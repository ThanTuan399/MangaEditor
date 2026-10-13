# MangaEditor — v0.2

MangaEditor đang được dựng lại theo hướng **Region là đơn vị trung tâm, raw không bị phá và mọi chỉnh sửa nằm trên layer độc lập**.

## Trạng thái hiện tại

### V0 Foundation

- Project / Page / Region có ID cố định.
- Ba phạm vi độc lập: OCR, xóa chữ, khung chữ Việt.
- Tọa độ theo ảnh gốc.
- Lưu/mở `.mep` có `format_version`.
- Undo/redo qua `ProjectSession`.
- Raw được nhúng nguyên byte và kiểm tra SHA-256.

### v0.1 — Một trang đơn giản

- Patch nền trắng/màu trên layer riêng.
- Chữ Việt chỉnh được và lưu lại được.
- Ẩn/hiện patch và chữ.
- Xuất PNG/JPEG đúng kích thước raw.

### v0.2 — Region độc lập

- Danh sách Region có tên, thứ tự và trạng thái riêng.
- Bấm Region trên ảnh ↔ chọn đúng nội dung.
- Bấm nội dung ↔ làm nổi bật đúng Region.
- Hai vùng sát/chạm nhau không tự gộp.
- Một Region có nhiều `cleanup_parts` rời nhau.
- “Tạo Region mới” và “Thêm mảng vào Region đang chọn” là hai thao tác riêng.
- Đổi thứ tự không đổi ID.
- Xóa, tách mảng và gộp Region theo thao tác chủ động.
- Khi Region chồng nhau, app hỏi Region muốn chọn.
- Trạng thái Nền và Chữ độc lập: Chưa làm / Đang làm / Đã duyệt.
- Editor cảnh báo chữ chưa áp dụng trước khi chuyển Region.
- Project format v2; tự migration project v1 khi mở.

## Chưa có ở v0.2

- OCR thật.
- Dịch tự động.
- Nhận diện bong bóng tự động.
- Inpainting/phục hồi nền phức tạp.
- Xử lý cả chương.

OCR bắt đầu ở v0.3.

## Chạy ứng dụng

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

GitHub Actions chạy compile + unit tests + renderer + UI smoke test trên mỗi push.

## Tài liệu

- `docs/V0_FOUNDATION.md`
- `docs/V0_1.md`
- `docs/V0_2.md`
