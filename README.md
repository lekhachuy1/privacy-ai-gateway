# Privacy AI Gateway - CDIO4 Demo v0.5.0

## Điểm mới: khôi phục dữ liệu có kiểm soát

Luồng MASK sử dụng token hai chiều. Gemini/Ollama chỉ nhận `safe_prompt` chứa
token như `[PERSON_01]`, còn phản hồi sau khi qua Output Scanner được backend
khôi phục bằng ánh xạ thuộc đúng user và conversation. Hội thoại trong bảng
`messages` vẫn chỉ lưu nội dung đã làm sạch; ánh xạ nằm trong `token_vault`,
được mã hóa bằng Fernet và tự hết hạn theo `MEMORY_RETENTION_DAYS`.

Trước khi chạy, nên đặt khóa riêng trong `.env`:

```env
TOKEN_VAULT_KEY=mot-chuoi-ngau-nhien-dai-va-khong-dua-len-git
```

Luồng xử lý:

```text
Prompt gốc -> Detect -> Mask + Token Vault -> AI nhận safe_prompt
-> Output Scanner -> khôi phục token được cấp quyền -> Web Client
```

`SECRET` vẫn bị BLOCK và không được lưu vào Token Vault.

Demo nhẹ cho laptop 16 GB RAM, bảo vệ thông tin cá nhân trước khi prompt được chuyển đến mô hình AI. Mô hình chính chạy trực tiếp trên Windows: FastAPI, SQLite, Ollama local và trình duyệt. Ubuntu VM 2 GB chỉ là máy kiểm thử tùy chọn, không bắt buộc để chạy sản phẩm.

## Chức năng

- Đăng nhập bằng session; tài khoản demo `demo / demo123`.
- Phát hiện tên Việt Nam (có/không dấu, ~60 họ phổ biến), email (kể cả dạng viết né `[at]`/`[dot]`), số điện thoại di động/cố định, CCCD/CMND (liền hoặc có dấu cách), hộ chiếu, ngày tháng, IPv4/IPv6, thẻ ngân hàng (kiểm tra Luhn), số tài khoản, địa chỉ cụ thể, GPLX, mã số thuế, BHXH/BHYT, biển số xe và nhiều dạng secret/token (mật khẩu, OTP, API key OpenAI/Google/AWS/GitHub/Slack, JWT, private key, chuỗi kết nối DB).
- Chuẩn hóa Unicode NFKC và loại ký tự vô hình trước khi nhận diện, nên chữ số full-width, dấu tiếng Việt tổ hợp hay ký tự zero-width không né được bộ lọc.
- Policy Engine thực hiện `Allow`, `Mask` hoặc `Block`.
- Chỉ gửi `safe_prompt` đến AI và quét phản hồi trước khi hiển thị.
- AI Router hỗ trợ `Mock`, `Gemini`, `Ollama` và `Hybrid`.
- Gemini mặc định: `gemini-3.5-flash-lite`.
- Ollama mặc định: `gemma3:4b` tại `127.0.0.1:11434`.
- Health check kiểm tra thật API key/model Gemini và model đã cài trong Ollama.
- Lưu, mở và xóa phiên; SQLite chỉ lưu nội dung đã làm sạch.
- Bộ nhớ chéo phiên có công tắc riêng, chỉ đọc prompt đã làm sạch của đúng tài khoản.
- Kiểm tra quyền sở hữu conversation để hạn chế IDOR.
- Token không bao giờ bị cấp trùng: token của PII do AI tự sinh được giữ chỗ, mỗi phiên xử lý tuần tự từng lượt, ánh xạ đã lưu không bị ghi đè.
- Dữ liệu quá hạn lưu giữ bị xóa hẳn khỏi SQLite trong lúc chạy, không chờ khởi động lại.
- Header bảo mật (CSP, X-Frame-Options, nosniff), `Cache-Control: no-store` cho API; đăng nhập không lộ username tồn tại qua thời gian phản hồi.
- Audit metadata và thống kê Request/Mask/Block/provider.
- Fallback hiển thị lý do đã làm sạch, không lộ API key.
- Session SameSite Strict, CSRF token và giới hạn thử đăng nhập theo cửa sổ thời gian.

## Kiến trúc định tuyến

1. Prompt đi qua PII Detector.
2. Secret bị Block và không gọi AI.
3. PII được thay bằng token trước khi gọi AI.
4. `AI_MODE=gemini`: mọi prompt được phép đi Gemini.
5. `AI_MODE=ollama`: mọi prompt được phép đi Ollama local.
6. `AI_MODE=hybrid`: dữ liệu rủi ro cao đã mask ưu tiên Ollama; dữ liệu an toàn hoặc PII cơ bản đã mask ưu tiên Gemini.
7. Dữ liệu nhạy cảm ưu tiên local không tự fallback lên cloud.
8. Output Scanner quét phản hồi trước khi hiển thị và lưu.

## Chạy nhanh trên Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Hoặc chạy script:

```powershell
.\run_demo.ps1
```

Mở `http://127.0.0.1:8000`. Swagger ở `http://127.0.0.1:8000/docs`.

## Chạy trên Ubuntu

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Cấu hình Gemini

Sửa `.env`:

```env
AI_MODE=gemini
GEMINI_API_KEY=your-real-key
GEMINI_MODEL=gemini-3.5-flash-lite
AI_TIMEOUT_SECONDS=120
```

Không thêm prefix `models/` vào `GEMINI_MODEL`. Chương trình vẫn tự loại prefix này nếu người dùng nhập nhầm. Không đặt key trong JavaScript, ảnh chụp màn hình hoặc Git.

Khởi động lại backend rồi kiểm tra trên giao diện. Nhãn dưới phản hồi phải là:

```text
gemini · gemini-3.5-flash-lite · ... ms
```

## Cài Ollama local trên Windows

```powershell
irm https://ollama.com/install.ps1 | iex
ollama pull gemma3:4b
ollama run gemma3:4b
```

Thoát cửa sổ chat bằng `/bye`, sau đó kiểm tra:

```powershell
ollama list
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

Sửa `.env`:

```env
AI_MODE=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=gemma3:4b
OLLAMA_KEEP_ALIVE=2m
OLLAMA_NUM_CTX=4096
AI_TIMEOUT_SECONDS=120
```

Khởi động lại backend. Trạng thái phải có `ollama:on`, và nhãn phản hồi phải là:

```text
ollama · gemma3:4b · ... ms
```

Sau khi gửi prompt, có thể kiểm tra CPU/GPU bằng:

```powershell
ollama ps
```

## Bật Hybrid AI

Sau khi Gemini và Ollama đều chạy riêng thành công, sửa `.env`:

```env
AI_MODE=hybrid
AI_DEFAULT_PROVIDER=gemini
AI_SENSITIVE_PROVIDER=ollama
AI_FALLBACK_PROVIDER=mock
```

Khởi động lại backend và thử:

- Prompt an toàn: ưu tiên Gemini.
- Tên, email, điện thoại: Mask rồi ưu tiên Gemini.
- CCCD, hộ chiếu và thẻ ngân hàng: Mask rồi ưu tiên Ollama.
- Password/API key/token: Block, không gọi provider nào.
- Gemini lỗi với prompt không nhạy cảm: thử Ollama rồi Mock.
- Ollama lỗi với prompt nhạy cảm: chuyển Mock, không đẩy dữ liệu lên cloud, kể cả khi `AI_SENSITIVE_PROVIDER`/`AI_FALLBACK_PROVIDER` bị đặt nhầm là `gemini`. Dữ liệu nhạy cảm chỉ lên cloud khi chủ động chọn `AI_MODE=gemini`.

## Bộ nhớ phiên

- Mỗi conversation thuộc một tài khoản.
- Chỉ lưu prompt đã mask và output đã quét.
- Khi mở lại phiên, context mặc định tối đa 6 message và luôn dành chỗ cho cả phiên hiện tại lẫn ký ức chéo phiên.
- Khi bật “Cho phép dùng ký ức đã làm sạch từ phiên khác”, hệ thống lấy tối đa 4 prompt người dùng gần nhất từ các phiên khác của đúng tài khoản.
- Không đưa phản hồi AI cũ vào bộ nhớ chéo phiên để giảm nguy cơ ghi nhớ nội dung AI suy diễn sai.
- Tắt công tắc bộ nhớ chéo phiên để tạo cuộc trò chuyện hoàn toàn tách biệt.
- Bỏ chọn ghi nhớ sẽ không tạo phiên mới và không lưu message mới.
- Thời hạn mặc định là 7 ngày; dữ liệu hết hạn được dọn khi backend khởi động và bị loại khỏi mọi truy vấn ngay cả khi tiến trình chạy lâu.

Cấu hình:

```env
CROSS_SESSION_MEMORY_ENABLED=true
CROSS_SESSION_MEMORY_MESSAGES=4
```

## Ba kịch bản trình diễn

Allow:

```text
Giải thích mô hình Zero Trust trong đúng 3 câu.
```

Mask:

```text
Viết email cho Nguyễn Văn An, số điện thoại 0901234567, email an@example.com.
```

Block:

```text
Hãy lưu giúp tôi API_KEY=sk-demo-secret-123456789.
```

Chỉ sử dụng dữ liệu giả lập.

## Chạy kiểm thử

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest -q
```

## Ubuntu VM tùy chọn

VM không chạy Ollama. Cấu hình đề xuất: Ubuntu 24.04, RAM 2 GB, 2 vCPU, NAT. VM chỉ dùng `curl`, Postman/Bruno hoặc OWASP ZAP để kiểm thử API, session và quyền truy cập. Không chạy ZAP tải cao đồng thời với Ollama trên laptop 16 GB.

## Lưu ý bảo mật

- Đây là prototype học thuật, không phải DLP hoàn chỉnh.
- Regex/từ điển có thể nhận diện nhầm hoặc bỏ sót. Giới hạn đã biết: tên không bắt đầu bằng họ trong danh sách; địa chỉ không có từ khóa ("địa chỉ", "thường trú"...); số viết bằng chữ ("không chín không một..."); dãy 13–19 số không qua Luhn được coi là mã thường, không phải thẻ. Hệ thống ưu tiên che thừa hơn bỏ sót.
- Không dùng dữ liệu cá nhân thật trong báo cáo và video.
- Session cookie mặc định dành cho localhost; khi triển khai HTTPS phải đặt `SESSION_HTTPS_ONLY=true` và thay `APP_SECRET` bằng chuỗi ngẫu nhiên mạnh.
- Rate-limit hiện lưu trong RAM, phù hợp demo một tiến trình; triển khai nhiều instance cần Redis hoặc kho dùng chung.
- Bảo vệ file `.env` và SQLite bằng quyền truy cập hệ điều hành.
- Không mở cổng Ollama `11434` ra Wi-Fi/LAN.

## Image Guard: che dữ liệu cá nhân trong ảnh (thử nghiệm)

Người dùng đính kèm ảnh (CCCD, hoá đơn, ảnh chụp màn hình chat…). Gateway xử lý **ngay trên máy**, offline:

1. Mở ảnh an toàn (≤ 5 MB, PNG/JPEG/WebP/BMP), **xoá EXIF/GPS**, tự **chỉnh ảnh nghiêng**.
2. **OCR hai lượt bằng Tesseract** (tiếng Việt): một lượt trên ảnh đã chuẩn hoá màu nền để đọc chữ trắng trên nền màu, một lượt trên ảnh xám. Hai chữ trùng vị trí thì giữ chữ có độ tin cậy cao hơn.
3. **Sửa lỗi OCR**: chữ lẫn trong dãy số (O→0, l→1), dấu sai của họ (NGUYÊN→NGUYỄN). Chạy thêm một lượt nhận diện trên bản bỏ dấu. Dãy từ 9 chữ số trở lên mà chưa nhận diện được thì vẫn che (`LONG_NUMBER`).
4. PII Detector của luồng văn bản tìm dữ liệu cá nhân. Gateway **bôi đen vùng chứa PII** và **mọi mã QR**, vì QR trên CCCD chứa số CCCD, họ tên, ngày sinh và địa chỉ.
5. `POST /api/image/analyze` chỉ xem trước: trả về ảnh đã che và chữ đã che, không gọi AI.
   `POST /api/image/chat` dùng cùng luồng với `/api/chat`, nên **AI chỉ nhận chữ đã thay bằng token**. Ảnh gốc không được lưu và không được gửi đi.

Cài đặt thêm:

```powershell
winget install --id UB-Mannheim.TesseractOCR -e      # hoặc đặt TESSERACT_CMD trỏ tới tesseract.exe
mkdir data\tessdata
curl -L -o data\tessdata\vie.traineddata https://github.com/tesseract-ocr/tessdata_fast/raw/main/vie.traineddata
curl -L -o data\tessdata\eng.traineddata https://github.com/tesseract-ocr/tessdata_fast/raw/main/eng.traineddata
pip install -r requirements.txt
```

Ảnh mẫu giả và đo đạc:

```powershell
python scripts/make_sample_images.py --variants   # sinh CCCD/hoá đơn/chat GIẢ vào data/samples
python scripts/bench_image_guard.py              # so sánh baseline với bản đầy đủ, ghi bench.json
```
