# V0 Foundation — Quy ước không được phá

## 1. Đơn vị trung tâm là Region

`ContentRegion.id` là danh tính thật. `name` và `order` chỉ để hiển thị. Hai vùng sát nhau hoặc chồng lên nhau vẫn là hai đối tượng khác nhau nếu người dùng tạo chúng riêng.

## 2. Ba phạm vi độc lập

Một Region có ba hình học riêng:

- `ocr_area`: vùng ảnh đủ rộng để OCR đọc chữ sau này.
- `cleanup_area`: phạm vi cho phép xóa/chỉnh điểm ảnh sau này.
- `text_frame`: không gian để dàn chữ Việt sau này.

Không dùng một mask duy nhất cho cả ba nhiệm vụ.

## 3. Tọa độ luôn theo ảnh gốc

Mọi `Rect` dùng pixel của ảnh raw. Zoom/pan là trạng thái giao diện và không được ghi ngược vào dữ liệu.

## 4. Layer và raw tách biệt

Layer có loại rõ ràng:

- `source`: ảnh gốc, khóa.
- `background_patch`: bản vá nền tương lai.
- `vietnamese_text`: lớp chữ Việt tương lai.
- `guide`: lớp hướng dẫn, không xuất.

V0 chỉ tạo layer `source`; các loại còn lại được định nghĩa để mở rộng sau.

## 5. Dữ liệu không phụ thuộc UI

`manga_editor/domain` không import PySide6. Giao diện chỉ gọi `ProjectSession` để thay đổi dữ liệu.

## 6. Mọi sửa đổi đi qua ProjectSession

`ProjectSession.transact()` tạo snapshot trước thay đổi. Undo/redo vì vậy có một đường đi thống nhất thay vì mỗi widget tự quản lý lịch sử riêng.

## 7. Định dạng dự án có phiên bản

`format_version` được lưu trong `project.json`. Loader từ chối phiên bản chưa hỗ trợ thay vì đoán cấu trúc.

## 8. Ảnh gốc được bảo vệ

Raw được nhúng nguyên byte vào `.mep` và kiểm tra SHA-256 khi mở lại. V0 không có API nào ghi đè raw.

## 9. Ranh giới V0

V0 kết thúc khi:

1. tạo được project;
2. nhập được page raw;
3. tạo Region và chỉnh ba phạm vi độc lập;
4. save/load giữ nguyên dữ liệu;
5. zoom/pan không thay đổi tọa độ Region;
6. undo/redo hoạt động cho thao tác dữ liệu chính.
