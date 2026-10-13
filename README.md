# MangaEditor — V0 Foundation

MangaEditor V0 là bản dựng lại từ đầu theo nguyên tắc **vùng nội dung là đơn vị trung tâm**. Mục tiêu của V0 không phải OCR hay Việt hóa hoàn chỉnh, mà là tạo nền dữ liệu và kiến trúc đủ chắc để các phiên bản sau mở rộng mà không phải thay mô hình cốt lõi.

## V0 làm được gì

- Tạo dự án mới.
- Nhập ảnh raw làm trang truyện.
- Mỗi trang có ID cố định, ảnh gốc được giữ nguyên trong dự án.
- Tạo nhiều vùng nội dung; mỗi vùng có ID cố định không phụ thuộc tên, màu hay thứ tự.
- Mỗi vùng giữ riêng ba phạm vi:
  - vùng đọc OCR;
  - vùng/mặt nạ xóa chữ;
  - khung đặt chữ Việt.
- Phóng to, thu nhỏ và di chuyển ảnh mà dữ liệu vùng vẫn lưu theo tọa độ ảnh gốc.
- Lưu/mở dự án `.mep` mà không mất ID, phạm vi hay ảnh raw.
- Hoàn tác/làm lại các thay đổi dữ liệu chính.
- Phân tách rõ domain, application, infrastructure và presentation.

## V0 cố ý chưa làm

- OCR.
- Dịch tự động.
- Nhận diện bong bóng tự động.
- Xóa chữ/phục hồi nền thật sự.
- Render chữ Việt lên ảnh.
- Xuất ảnh hoàn chỉnh.
- Xử lý hàng loạt nhiều trang.

Các chức năng đó sẽ được thêm ở các mốc sau nhưng dùng lại cùng Project/Page/Region đã có.

## Chạy ứng dụng

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

## Kiểm tra phần lõi

```powershell
python -m unittest discover -s tests -v
```

Các test lõi không cần khởi động giao diện.

## Định dạng dự án

`.mep` là một tệp ZIP có phiên bản, gồm:

```text
project.json
assets/
  pages/
    <page-id>/original.<ext>
```

Ảnh raw được lưu như tài sản bất biến. Giao diện chỉ đọc ảnh raw để hiển thị; V0 không ghi đè lên ảnh này.

## Cấu trúc mã nguồn

```text
main.py
manga_editor/
  domain/          # dữ liệu và quy tắc thuần Python
  application/     # điều phối thao tác + undo/redo
  infrastructure/  # đọc ảnh, lưu/mở dự án
  presentation/    # PySide6 UI, canvas
```

Chi tiết thiết kế nằm trong `docs/V0_FOUNDATION.md`.
