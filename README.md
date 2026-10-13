# MangaEditor — v0.1

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

- Nhập ảnh raw.
- Tạo Region.
- Vẽ phạm vi xóa chữ và khung chữ Việt.
- Tạo bản vá nền trắng hoặc màu phẳng trên layer riêng.
- Nhập chữ Việt và chỉnh:
  - phông;
  - cỡ chữ;
  - căn trái/giữa/phải;
  - màu chữ;
  - vị trí/kích thước bằng `text_frame`.
- Ẩn/hiện patch và text layer.
- Chữ vẫn chỉnh được sau khi lưu/mở lại.
- Xuất PNG/JPEG từ raw + layer, giữ kích thước ảnh gốc.
- Hoàn tác/làm lại các thao tác dữ liệu chính.

## Chưa có ở v0.1

- OCR.
- Dịch tự động.
- Tự nhận diện bong bóng.
- Cọ mask tự do.
- Inpainting/phục hồi tranh phức tạp.
- Chữ hiệu ứng.
- Xử lý hàng loạt.

Các phần này sẽ được thêm theo từng mốc mà không thay lại Project/Page/Region.

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

Repo cũng có GitHub Actions để chạy `compileall` và unit test trên mỗi push.

## Cấu trúc

```text
main.py
manga_editor/
  domain/          # dữ liệu và quy tắc
  application/     # điều phối + undo/redo
  infrastructure/  # ảnh, lưu/mở, renderer
  presentation/    # PySide6 UI/canvas
tests/
docs/
```

- Nền kiến trúc: `docs/V0_FOUNDATION.md`
- Quy trình v0.1: `docs/V0_1.md`
