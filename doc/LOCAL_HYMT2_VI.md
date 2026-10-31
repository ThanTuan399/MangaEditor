# Hy-MT2 Offline trong MangaEditor (nhánh NewMangaEditor)

Bộ dịch `local_hymt2` sử dụng model Tencent Hy-MT2 GGUF chạy qua **llama-server** trên chính máy tính. Đây là bộ dịch văn bản sau OCR, không phải OCR hoặc bộ sửa/xóa chữ. **Không cần API key, không cần Gemini/OpenAI và không tải model vào Python/PyQt.**

## 1. Cập nhật ứng dụng

Nếu đã có thư mục Git của dự án:

```powershell
git fetch origin
git switch NewMangaEditor
git pull --ff-only origin NewMangaEditor
```

Nếu tải mới, trên trang GitHub chọn nhánh **NewMangaEditor** rồi **Code > Download ZIP**. Giải nén và chạy/cài ứng dụng theo các file `Win-Install-or-Update.bat` và `Win-Start.bat` hiện có. **ZIP mã nguồn không phải bản portable đã cài sẵn tất cả Python dependencies và OCR models.**

## 2. Cài server một lần

```powershell
winget install llama.cpp
```

Trên Windows, bấm đúp **Win-Start-HyMT2.bat** ở thư mục gốc dự án. Launcher tự tìm `llama-server.exe` trong PATH **hoặc** WinGet Packages (tránh lỗi 'llama-server is not recognized'). Mặc định chạy:

```powershell
llama-server -hf tencent/Hy-MT2-1.8B-GGUF:Q4_K_M --port 8080
```

Lần đầu cần Internet để tải model từ Hugging Face. Khi file GGUF đã có, model và server có thể hoạt động offline. Hãy đợi log server cho biết đã lắng nghe cổng 8080 và **giữ cửa sổ này mở**.

Nếu server cổng 8080 đã chạy, không mở server lần hai. Nếu cần cổng khác:

```powershell
.\scripts\Start-HyMT2.ps1 -Port 8081
```

Đồng thời thay `hymt_api_base` thành `http://127.0.0.1:8081/v1` trong Settings.

## 3. Chọn bộ dịch trong ứng dụng

1. Mở MangaEditor như thường lệ (`Win-Start.bat`).
2. Vào **Settings > Translation**.
3. **Translator:** chọn **Hy-MT2 1.8B (Offline / llama.cpp)** (`local_hymt2`).
4. **Target Language:** **VIN** (Tiếng Việt). **Hy-MT2 Source Language:** `JPN` (Nhật), `CHS` (Trung giản thể), `CHT` (phồn thể), `ENG` (Anh), hoặc `auto` cho hỗn hợp. Với manga Nhật, để `JPN` thường ổn định hơn nhận diện văn bản ngắn.
5. Mặc định: **API URL** `http://127.0.0.1:8080/v1`; **Model ID** `auto` (lấy từ server); **Timeout** 120 giây/vùng; **Max Output Tokens** 512; **Previous OCR Regions** 0. Có thể đặt Previous OCR Regions thành 2 nếu muốn mang theo 2 vùng gốc trước đó làm ngữ cảnh (không dịch lại vùng trước).
6. Chọn OCR cục bộ phù hợp, thêm **một ảnh** thử, bắt đầu quy trình dịch bình thường.

**Không cần sửa OPENAI_API_BASE, OPENAI_MODEL, .env hay nhập API key.** Các bộ dịch NLLB, Google và OpenAI cũ vẫn giữ nguyên.

## 4. Kiểm tra server

```powershell
Invoke-RestMethod http://127.0.0.1:8080/v1/models
```

Nếu có `data` chứa model id, server đã sẵn sàng nhận request. Mở http://127.0.0.1:8080 để thử trực tiếp. Nếu MangaEditor không kết nối được, kiểm tra cổng khớp với `hymt_api_base`, firewall và server còn chạy không. Nếu model chưa sẵn sàng, đợi download hoàn tất.

## 5. Cơ chế và giới hạn

- Pipeline giữ nguyên: **Detection → OCR → Hy-MT2 → Inpainting → Typesetting → Editor / Export**.
- Backend dịch từng vùng OCR theo thứ tự và trả về đúng số lượng vùng, tránh dán nhầm câu sang ô thoại khác.
- Backend chỉ kết nối tới địa chỉ loopback (`localhost`, `127.0.0.1`, `::1`), không tự gởi nội dung manga tới server từ xa.
- Model do **llama-server** quản lý; 'Unload Models After Translation' trong app không tắt server. Dừng server bằng Ctrl+C.
- Lỗi dịch hoặc kết quả bị cắt sẽ báo lỗi thay vì tự gán nhầm bản dịch. Tăng timeout/tokens nếu cần.
- Chưa có tự khởi động server bên trong app, quản lý GGUF trên giao diện, hoặc dịch nhiều vùng trong một request. Đây là tích hợp giai đoạn đầu; có thể nâng cấp.
- Thử chất lượng Nhật → Việt trên trang truyện thực tế trước khi xử lý hàng loạt; OCR nhận sai thì bản dịch cũng có thể sai.
- Quyền model GGUF: xem giấy phép và điều kiện sử dụng tại https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF . Không commit model GGUF vào repo.

**Lưu ý:** Tích hợp dùng API tương thích OpenAI của llama.cpp, nhưng là engine riêng `local_hymt2`, không gọi API dịch vụ OpenAI.
