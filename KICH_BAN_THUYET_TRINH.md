# Kịch bản thuyết trình và demo – Privacy AI Gateway v0.5.0

Tổng thời lượng: khoảng 15 phút (7 phút slide + 8 phút demo) và phần hỏi đáp.
Lời thoại chi tiết cho từng slide nằm trong phần speaker notes của bộ slide.
Kịch bản demo chi tiết (từng màn, lời nói, giải thích kỹ thuật, hỏi đáp) nằm trong `KICH_BAN_DEMO.md`.

## 1. Chuẩn bị trước buổi bảo vệ (làm trước 30 phút)

- [ ] `.env` đã đặt `APP_SECRET` và `TOKEN_VAULT_KEY` riêng (không còn cảnh báo khi khởi động).
- [ ] Chạy `python -m pytest -q`: 138 test đạt.
- [ ] `ollama list` có `gemma3:4b`; chạy thử 1 prompt để model nạp sẵn vào RAM.
- [ ] Gemini: health check trên giao diện báo "API key và model hợp lệ".
- [ ] Khởi động với `AI_MODE=hybrid` (chế độ `gemini` không bao giờ gọi Ollama; `mock` nếu mất mạng) bằng `./run_demo.ps1`.
- [ ] Đặt `OLLAMA_KEEP_ALIVE=30m` để model không tự nhả RAM giữa buổi demo.
- [ ] Mở sẵn `http://127.0.0.1:8000`, đăng nhập `demo / demo123`, xóa các phiên cũ.
- [ ] Mở sẵn một terminal PowerShell để đổi `.env` và chạy `ollama ps`.
- [ ] Tắt thông báo hệ điều hành, phóng to font trình duyệt (Ctrl + +) cho dễ nhìn.
- [ ] Chỉ dùng dữ liệu giả trong slide và demo.

## 2. Phần slide (~7 phút)

| Slide | Nội dung | Thời gian |
|---|---|---|
| 1 | Mở đầu, giới thiệu đề tài | 0:30 |
| 2 | Vấn đề: PII trong prompt, đi lên cloud, nằm trong lịch sử | 0:45 |
| 3 | Giải pháp: Allow / Mask / Block | 0:45 |
| 4 | Kiến trúc 8 bước | 1:00 |
| 5 | Các loại PII và hành động | 0:45 |
| 6 | Token Vault – điểm mới v0.5 | 1:00 |
| 7 | Định tuyến Hybrid | 0:45 |
| 8 | Bảo mật ứng dụng | 0:40 |
| 9 | Chuyển sang demo | 0:15 |

## 3. Phần demo (~8 phút)

### Kịch bản 1 – Allow (1 phút)

Prompt: `Giải thích mô hình Zero Trust trong đúng 3 câu.`

Chỉ ra: badge **Allow**, safe_prompt giống hệt prompt gốc, nhãn provider/model/độ trễ.

> "Không phát hiện dữ liệu nhạy cảm, nên Policy Engine cho phép gửi nguyên văn. Phản hồi vẫn được Output Scanner quét trước khi hiển thị."

### Kịch bản 2 – Mask và khôi phục (2 phút)

Bật **Ghi nhớ phiên**. Prompt:
`Viết email cho Nguyễn Văn An, số điện thoại 0901234567, email an@example.com.`

Chỉ ra:
1. safe_prompt chỉ còn `[PERSON_01]`, `[PHONE_01]`, `[EMAIL_01]`, đây là thứ duy nhất AI nhận.
2. Phản hồi trên màn hình hiện lại tên và số thật vì mình là chủ phiên.
3. (Tùy chọn) Mở Swagger `/docs` hoặc DevTools để so sánh `response_sanitized` (còn token) với `response` (đã khôi phục).

> "AI chưa bao giờ thấy tên thật. Ánh xạ token được mã hóa Fernet, gắn với đúng user và phiên, nên chỉ chủ phiên mới thấy lại dữ liệu gốc."

### Kịch bản 3 – Block (1 phút)

Prompt: `Hãy lưu giúp tôi API_KEY=sk-demo-secret-123456789.`

Chỉ ra: badge **Block**, không có phản hồi AI, không có nhãn provider.

> "Request dừng tại gateway. AI Router không được gọi, secret không vào Token Vault, audit chỉ ghi hành động Block."

### Kịch bản 4 – Bộ nhớ phiên (2 phút)

1. Mở phiên Mask ở thanh bên: lịch sử lưu chỉ gồm token.
2. Hỏi tiếp: `Viết lại ngắn gọn hơn.` → AI vẫn có ngữ cảnh đã làm sạch.
3. Bấm **Phiên mới**, bật công tắc ký ức chéo phiên, hỏi: `Nhắc lại người tôi cần gửi email lúc nãy.`
   Lưu ý: tên ở phiên cũ hiện thành "(họ tên đã ẩn)", **không** được khôi phục thành tên thật, vì
   Token Vault chỉ khôi phục trong đúng phiên đã tạo token. Hãy nói rõ đây là hành vi có chủ đích:
   ký ức chéo phiên chỉ mang ngữ cảnh đã làm sạch, không mang dữ liệu gốc.
4. Tắt công tắc, hỏi lại → AI không còn ngữ cảnh.
5. Xóa phiên → minh họa quyền xóa dữ liệu.

### Kịch bản 5 – Ollama / Hybrid (2 phút)

1. (Đã để sẵn `AI_MODE=hybrid` từ đầu.)
2. Prompt thường (Zero Trust) → nhãn `gemini · ...`.
3. Prompt: `Kiểm tra hồ sơ có CCCD 012345678901 giúp tôi.` → Mask, nhãn `ollama · gemma3:4b`.
4. Chạy `ollama ps` để cho thấy model đang chạy local (CPU/GPU).
5. (Tùy chọn) Tắt Ollama rồi gửi lại prompt CCCD → chuyển sang Mock, **không** lên Gemini.

> "Dữ liệu rủi ro cao được xử lý ngay trên máy. Kể cả khi Ollama lỗi hoặc cấu hình fallback sai, router vẫn không đẩy prompt nhạy cảm lên cloud."

### Chứng minh dữ liệu gốc không đi tới Gemini (chèn vào kịch bản 2)

**Mức 1 – Egress log (nhanh, nên dùng khi demo).** Đặt `EGRESS_LOG_ENABLED=true` trong `.env`,
khởi động lại backend, mở một cửa sổ PowerShell thứ hai:

```powershell
python scripts\watch_egress.py
```

Gửi prompt Mask → cửa sổ này in ngay nội dung mà connector sắp gửi tới Gemini (đánh dấu CLOUD hay
LOCAL), token tô vàng, kèm dòng xanh "✓ Bộ nhận diện không thấy dữ liệu cá nhân trong request gửi đi".
Chạy kèm `--tim "Nguyễn Văn An" 0901234567` để dò nguyên văn các giá trị (bắt cả khi lọt ở dạng khác).
Nếu request nào lọt dữ liệu thật, script in cảnh báo đỏ. File thô vẫn xem được bằng
`Get-Content data\egress.log -Wait -Tail 0 -Encoding utf8`. Log không ghi header nên không lộ API key. Sau đó tìm
dữ liệu gốc trong toàn bộ log (kết quả rỗng là đạt):

```powershell
Select-String -Path data\egress.log -Pattern "Nguyễn Văn An","0901234567","an@example.com" -Encoding utf8
```

**Mức 2 – Test tự động.** `python -m pytest tests/test_egress.py -v`: test chặn ngay lời gọi
`httpx` (lớp cuối cùng trước khi ra mạng), kiểm tra cả prompt và lịch sử gửi kèm không chứa PII gốc.

**Mức 3 – Bắt gói tin HTTPS thật bằng mitmproxy (độc lập với code của nhóm).**

```powershell
python -m pip install mitmproxy
mitmweb            # giao diện tại http://127.0.0.1:8081, proxy ở cổng 8080
```

Mở PowerShell khác trong thư mục project:

```powershell
$env:HTTPS_PROXY = "http://127.0.0.1:8080"
$env:SSL_CERT_FILE = "$env:USERPROFILE\.mitmproxy\mitmproxy-ca-cert.pem"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Gửi prompt Mask, trong mitmweb chọn request `generativelanguage.googleapis.com` → tab Request:
body chỉ chứa token. **Cảnh báo:** mitmweb hiện header `x-goog-api-key`, đừng chiếu phần header
lên màn hình; nên tạo key riêng cho buổi demo và xóa key đó sau buổi bảo vệ.

## 4. Kết thúc (~2 phút)

Quay lại slide 12 (cải tiến), 13 (giới hạn) và 14 (kết luận), rồi mời hội đồng đặt câu hỏi.

## 5. Phương án dự phòng

| Sự cố | Xử lý |
|---|---|
| Mất mạng / Gemini lỗi 429 | Đổi `AI_MODE=mock` hoặc `ollama`; chỉ vào `fallback_reason` như một tính năng |
| Ollama chậm lần đầu | Đã nạp sẵn model; nếu timeout, giải thích fallback sang Mock là hành vi đúng |
| Backend không khởi động | Kiểm tra `AI_MODE` hợp lệ (ứng dụng sẽ báo lỗi rõ) |
| Bị khóa đăng nhập (429) | Chờ 60 giây, hoặc khởi động lại backend |
| Máy hỏng hoàn toàn | Dùng video demo quay sẵn [đường dẫn video] |

## 6. Câu hỏi hội đồng có thể hỏi

- **Regex bỏ sót thì sao?** Đúng, đây là giới hạn; hướng phát triển là NER tiếng Việt. Thiết kế tách PII Detector thành module riêng nên thay thế được mà không đổi luồng.
- **Vì sao không để AI tự che dữ liệu?** Vì khi đó dữ liệu gốc đã đến AI rồi. Nguyên tắc là quyết định trước khi gọi AI.
- **Mất `TOKEN_VAULT_KEY` thì sao?** Không giải mã được ánh xạ; giao diện chỉ hiện token, không lộ dữ liệu. Khóa phải được quản lý ngoài Git.
- **Token do AI tự bịa, ví dụ `[PERSON_99]`, có bị khôi phục nhầm không?** Không, chỉ token có trong vault của đúng user và phiên mới được khôi phục.
- **Người dùng khác đoán `conversation_id` được không?** Mọi truy vấn đều kiểm tra `user_id`; sai chủ sở hữu trả 404 (chống IDOR).
- **Vì sao Hybrid vẫn gửi PII cơ bản đã mask lên Gemini?** Vì sau khi mask, AI chỉ nhận token; còn dữ liệu rủi ro cao được giữ local để giảm thêm rủi ro suy luận từ ngữ cảnh.
