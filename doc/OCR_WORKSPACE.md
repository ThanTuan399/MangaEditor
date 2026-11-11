# OCR Workspace

OCR Workspace is a separate manual-translation workflow optimized for speed.

## Scan pipeline

```
Raw manga
-> Detection
-> OCR
-> Text-line merge
-> Project JSON
```

The scan deliberately skips translation, colorization, upscaling, mask refinement,
inpainting, typesetting, and final image rendering.

**Existing project JSON is never overwritten by OCR-only scan.** If OCR
results already exist for a page, the page is left untouched so translations
and manual edits are safe. To genuinely re-scan a page, move or rename that
page's existing `manga_translator_work/json/*_translations.json` file first
(keep it as a backup).

## Quản lý nhiều dự án theo thư mục

**Mỗi thư mục = một dự án riêng.** OCR Workspace không trộn tất cả ảnh
được thêm vào trang chính thành một lượt scan/render nữa.

1. Bấm **Thêm thư mục dự án**, chọn thư mục chứa ảnh RAW.
2. Lặp lại để thêm nhiều dự án, kể cả các thư mục có tên tiếng Việt. Hoặc bấm
   **Thêm thư mục con** và chọn thư mục mẹ: mỗi thư mục con trực tiếp sẽ
   được đăng ký thành một dự án riêng, không gộp ảnh giữa các thư mục.
3. Chọn dự án trong ô **Dự án** rồi bấm **Scan OCR Only**.
4. Chọn một trang, dùng **Copy All OCR** để lấy text có marker [001], [002].
   Dán vào Google Dịch, sửa bản dịch nếu cần rồi dùng **Paste Batch**.
5. Nhấp đúp cột Translation để chỉnh nội dung và bấm **Save JSON**.
6. **Render trang đã đổi**: chỉ xử lý các trang chưa có ảnh xuất, hoặc có
   ảnh RAW/JSON/font/inpaint/layout đã thay đổi.
7. **Render trang đang chọn**: ép xuất một trang để xem thử ngay,
   không phải chạy lại toàn bộ dự án.
8. Bấm **Mở ảnh đã render** để xem thư mục kết quả của dự án đó.

Dự án có thể chuyển đổi qua lại trong một phiên làm việc nhưng mỗi lúc
chỉ chạy một tác vụ Scan/Render, tránh trộn dữ liệu và chiếm RAM.
Bấm **Bỏ khỏi danh sách** chỉ gỡ dự án khỏi giao diện, **không xóa dữ liệu**.

Ảnh RAW và OCR JSON vẫn ở thư mục nguồn. Kết quả xuất của từng dự án nằm tại:
`<folder>/manga_translator_work/ocr_workspace_output/<tên thư mục>/...`.

Danh sách dự án được ghi tại `config/ocr_workspace_projects.json` của app.
Nếu một thư mục dự án con cũng được đăng ký riêng, quét dự án mẹ
sẽ bỏ qua thư mục con này. Các thư mục kết quả và cache nội bộ không được
quét ngược lại như ảnh RAW.

Khi một vùng không có nội dung trong cột **Translation**, chế độ OCR Workspace
sẽ không xóa chữ gốc tại vùng đó. Nó chỉ tạo mask và vẽ lại những vùng có
bản dịch cụ thể. Điều này không áp dụng cho chế độ Normal Translation.

### Tối ưu render

Cache các lượt render **thành công** lưu tại:
`<folder>/manga_translator_work/ocr_workspace_render_cache.json`.

Khi Render trang đã đổi, chương trình so nội dung JSON, metadata ảnh RAW,
thiết lập font/layout/inpainting và sự tồn tại của file ảnh xuất. Trang không
đổi sẽ được bỏ qua. Nếu xóa file ảnh xuất hoặc sửa một câu đã dịch, trang đó
sẽ được xuất lại. Lần đầu vẫn chạy đủ inpainting; tốc độ phụ thuộc ảnh/model.
Chọn **Render trang đang chọn** để bắt buộc render lại khi muốn thử thủ công.

### Hy-MT2 đã được loại bỏ

App không tự chạy llama-server, không còn lựa chọn Hy-MT2 trong bộ dịch.
Cấu hình cũ chọn local_hymt2 sẽ được đổi sang none, tránh tự gọi dịch vụ.
Bạn vẫn copy OCR → Google Dịch bên ngoài → Paste Batch → Render.
Không cần gỡ llama.cpp hay xóa GGUF trên máy để tiếp tục dùng app.


## Two-pane workflow

- Left: region number, editable OCR text, editable translation.
- Right: original raw page.
- Selecting a row highlights its saved region on the raw image.


## External translation

**Copy All OCR** copies the current page with stable markers:

```text
[001] 起きてきたの？体、大丈夫？
[002] マッサージして…
```

Translate the block in an external tool while preserving the markers, copy the
translated block, then press **Paste Batch**. Marker IDs map translations back to
the original MangaEditor regions.

If the external tool removes markers, Paste Batch also accepts one non-empty
translation per line and maps those lines in region order, **but only if the
line count matches the number of regions exactly**. Invalid region markers
are rejected to prevent dialogue from being assigned to the wrong bubble.

## Saving

**Save JSON** updates the existing MangaEditor project JSON. A
`.ocr_workspace.bak` backup is written before replacement. The workspace writes
translation text only and removes stale rich-text data for a region when its
plain translation changes.

## Batch export

- **Export Batch TXT** exports OCR + current translations for all pages in the
  workspace.
- **Render trang đã đổi** chỉ render trang có bản dịch hoặc thiết lập đã thay đổi,
  không chạy OCR hoặc dịch lại, và bỏ qua các trang đã xuất thành công.
- **Render trang đang chọn** ép xuất duy nhất trang hiện tại.
- TXT cũ không được phép ghi đè lại bản dịch đã lưu trong JSON.

## Speed recommendations

For a fast local scan, choose a local OCR backend such as `mocr`, `48px`, or
PaddleOCR in **Settings → OCR**. OCR Workspace blocks OpenAI/Gemini OCR (including
hybrid secondary OCR) to prevent unwanted API calls. Detection/OCR settings
continue to come from the normal Settings page so OCR Workspace does not
maintain a second incompatible configuration.

## Update source checkout

```powershell
cd D:\\app\\MangaEditorV1
git fetch https://github.com/ThanTuan399/MangaEditor.git NewMangaEditor
git switch NewMangaEditor
git merge --ff-only FETCH_HEAD
.\\Win-Start.bat
```

If this checkout is on another branch and has uncommitted changes, back
them up before switching. Do not use a force reset.
