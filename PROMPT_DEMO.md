# Bộ prompt demo và kết quả kỳ vọng

Cột "Phân tích" và "safe_prompt" đã được chạy thử qua bộ nhận diện thật của hệ thống, nên màn hình
sẽ hiện đúng như vậy. Riêng nội dung câu trả lời của AI thì mỗi lần một khác; phần "Hiển thị kỳ vọng"
mô tả những điểm cần kiểm tra, không phải câu chữ chính xác.

Dòng phân tích trên giao diện có dạng `Policy: <HÀNH ĐỘNG> · <lý do> · PII: <các loại>`; bảng dưới ghi tắt phần lý do.

Chuẩn bị: `AI_MODE=hybrid`, bật "Ghi nhớ phiên", mở egress log ở cửa sổ bên cạnh
(`Get-Content data\egress.log -Wait -Tail 0 -Encoding utf8`). Mỗi nhóm nên bắt đầu bằng **Phiên mới**.

---

## 1. Allow – prompt an toàn

**Prompt:** `Giải thích mô hình Zero Trust trong đúng 3 câu.`

| Mục | Kỳ vọng |
|---|---|
| Phân tích | `Policy: ALLOW · PII: Không có` |
| safe_prompt | Giống hệt prompt gốc |
| Nhãn | `gemini · gemini-3.5-flash-lite · … ms` |
| Hiển thị | 3 câu giải thích Zero Trust, định dạng gọn |

**Nói:** "Không có dữ liệu nhạy cảm nên gateway cho đi nguyên văn."

---

## 2. Mask – tên, SĐT, email (thế mạnh chính)

**Prompt:** `Viết email mời Nguyễn Văn An họp lúc 9 giờ sáng thứ Hai, số điện thoại 0901234567, email an@example.com.`

| Mục | Kỳ vọng |
|---|---|
| Phân tích | `Policy: MASK · PII: PERSON, PHONE, EMAIL` |
| safe_prompt (AI nhận) | `Viết email mời [PERSON_01] họp lúc 9 giờ sáng thứ Hai, số điện thoại [PHONE_01], email [EMAIL_01].` |
| Egress log | Body chỉ có 3 token, không có "Nguyễn Văn An", "0901234567", "an@example.com" |
| Nhãn | `gemini · …` |
| Hiển thị | Email hoàn chỉnh, có "Kính gửi **Nguyễn Văn An**", có số **0901234567** và email thật. Không có `[PERSON_..]`, không có ô trống dạng `[Họ và tên]` |

**Nói:** "AI chỉ thấy token, nhưng người dùng nhận được email điền sẵn thông tin thật."

### 2b. Lượt tiếp theo trong cùng phiên – token được dùng lại

**Prompt:** `Thêm câu nhắc Nguyễn Văn An mang laptop và gọi lại số 0901234567 nếu bận.`

| Mục | Kỳ vọng |
|---|---|
| safe_prompt | `Thêm câu nhắc [PERSON_01] mang laptop và gọi lại số [PHONE_01] nếu bận.` |
| Hiển thị | Email được sửa lại, vẫn đúng tên và số thật |

**Nói:** "Cùng một người thì luôn là cùng một token, nên AI hiểu đây vẫn là anh An ở lượt trước."

---

## 3. Mask – tên không dấu, đơn từ

**Prompt:** `Viết đơn xin nghỉ học cho Le Van A, số điện thoại 0423423432, địa chỉ Đà Nẵng.`

| Mục | Kỳ vọng |
|---|---|
| Phân tích | `Policy: MASK · PII: PERSON, PHONE` |
| safe_prompt | `Viết đơn xin nghỉ học cho [PERSON_01], số điện thoại [PHONE_01], địa chỉ Đà Nẵng.` |
| Hiển thị | Đơn có "Em tên là: **Le Van A**", SĐT **0423423432**, địa chỉ Đà Nẵng. Chỗ người dùng chưa cung cấp (lớp, ngày nghỉ, lý do) để dòng chấm `..........` |

**Nói:** "Tên viết không dấu vẫn được nhận diện. Những gì người dùng chưa đưa, AI để trống cho tự điền chứ không bịa."

---

## 4. Không che nhầm – từ thông dụng và dãy số không phải thẻ

**Prompt A:** `Lý do chính khiến hồ sơ bị trả lại là gì?`
**Prompt B:** `Mã đơn hàng 1234 5678 9012 3456 bị giao trễ, viết lời xin lỗi khách.`

| Mục | Kỳ vọng |
|---|---|
| Phân tích | Cả hai đều `Policy: ALLOW · PII: Không có` |
| safe_prompt | Giữ nguyên |
| Hiển thị | Trả lời bình thường, mã đơn hàng giữ nguyên |

**Nói:** "'Lý do', 'hồ sơ' bắt đầu bằng họ Lý, họ Hồ nhưng không bị coi là tên. Dãy 16 số của mã đơn hàng không qua kiểm tra Luhn nên không bị coi là số thẻ. Gateway không che thừa làm hỏng câu hỏi."

---

## 5. Hybrid – dữ liệu rủi ro cao ở lại máy local

**Prompt:** `Kiểm tra giúp tôi hồ sơ vay của Trần Minh Khoa, CCCD 012345678901, số thẻ 4111 1111 1111 1111.`

| Mục | Kỳ vọng |
|---|---|
| Phân tích | `Policy: MASK · PII: PERSON, CCCD, BANK_CARD` |
| safe_prompt | `Kiểm tra giúp tôi hồ sơ vay của [PERSON_01], CCCD [CCCD_01], số thẻ [BANK_CARD_01].` |
| Nhãn | **`ollama · gemma3:4b · … ms`** (không phải gemini) |
| Egress log | Dòng mới có `"provider": "ollama"`, URL `127.0.0.1:11434` |
| Hiển thị | Trả lời có tên, CCCD và số thẻ thật |

Sau đó chạy `ollama ps` để cho thấy model đang chạy trên laptop.

**Nói:** "CCCD và số thẻ là dữ liệu rủi ro cao. Dù đã che, gateway vẫn giữ lại xử lý trên máy, không gửi lên cloud."

*Tùy chọn:* tắt Ollama rồi gửi lại → nhãn `mock · … · fallback ollama: …`, **không** chuyển sang gemini.

---

## 6. Block – bí mật

**Prompt A:** `Hãy lưu giúp tôi API_KEY=sk-demo-secret-123456789.`
**Prompt B:** `Mật khẩu: Abc@12345 đăng nhập không được, sửa giúp tôi.`

| Mục | Kỳ vọng |
|---|---|
| Phân tích | Khung đỏ `Policy: BLOCK · Phát hiện mật khẩu, API key hoặc access token · PII: SECRET` |
| Hiển thị | "Yêu cầu đã bị chặn trước khi gọi AI." |
| Nhãn | Không có nhãn provider |
| Egress log | **Không có dòng mới** |

**Nói:** "Request dừng tại gateway, AI không được gọi, bí mật không được lưu ở đâu cả."

---

## 7. Bộ nhớ chéo phiên

1. Sau nhóm 2, bấm **Phiên mới**, bật "Cho phép dùng ký ức đã làm sạch từ phiên khác".
2. **Prompt:** `Tôi vừa nhờ bạn viết email mời ai họp?`

| Mục | Kỳ vọng |
|---|---|
| Nhãn | Có thêm `· nhớ … mục từ phiên khác` |
| Hiển thị | AI nhớ là có một email mời họp, nhưng tên hiện là **"(họ tên đã ẩn)"**, không phải tên thật |

3. Tắt công tắc, hỏi lại → AI không biết gì về phiên trước, nhãn không còn "nhớ … mục".

**Nói:** "Ký ức giữa các phiên chỉ mang ngữ cảnh đã làm sạch. Dữ liệu gốc chỉ được khôi phục trong đúng phiên đã tạo ra nó."

---

## 8. (Tùy chọn) Output Scanner – PII do AI tự sinh

**Prompt:** `Cho tôi một ví dụ về số điện thoại di động Việt Nam hợp lệ gồm 10 chữ số.`

| Mục | Kỳ vọng |
|---|---|
| Phân tích | `Policy: ALLOW` |
| Hiển thị | Nếu AI đưa ra một số cụ thể, số đó hiện là **"(số điện thoại đã ẩn)"** |

**Nói:** "Không chỉ đầu vào, cả đầu ra của AI cũng được quét. Số này do AI tự sinh, không phải của người dùng, nên không được hiển thị."

*Lưu ý:* AI được dặn không tự bịa số điện thoại, nên có thể từ chối hoặc chỉ mô tả định dạng.
Hãy chạy thử trước buổi bảo vệ. Nếu AI không đưa ra số cụ thể, bỏ qua mục này và chứng minh bằng
test tự động `python -m pytest tests/test_privacy.py -k output -v`.

---

## Thứ tự gợi ý khi lên demo (~8 phút)

| # | Nhóm | Thời gian |
|---|---|---|
| 1 | Allow (1) | 0:45 |
| 2 | Mask + lượt 2 (2, 2b) + chỉ egress log | 2:00 |
| 3 | Không che nhầm (4A) | 0:30 |
| 4 | Block (6A) | 0:45 |
| 5 | Hybrid (5) + `ollama ps` | 1:30 |
| 6 | Bộ nhớ chéo phiên (7) | 1:30 |
| 7 | Dự phòng nếu còn giờ: tên không dấu (3), Output Scanner (8) | 1:00 |

---

# Phần 2 – Tình huống thực tế theo ngành

Các prompt dưới đây mô phỏng việc nhân viên văn phòng dùng AI hằng ngày. Cột "AI nhận" đã được chạy
thử qua hệ thống. "Đi đâu" là khi `AI_MODE=hybrid`. Toàn bộ là dữ liệu giả.

## Ngân hàng – chăm sóc khách hàng

**Prompt:** `Khách hàng Phạm Thị Hồng, SĐT 0912345678, phản ánh thẻ 4111 1111 1111 1111 bị trừ tiền 2 lần. Soạn email xin lỗi và hẹn hoàn tiền trong 3 ngày làm việc.`

- **AI nhận:** `Khách hàng [PERSON_01], SĐT [PHONE_01], phản ánh thẻ [BANK_CARD_01] bị trừ tiền 2 lần. …`
- **Đi đâu:** Ollama (local), vì có số thẻ.
- **Người dùng thấy:** email xin lỗi gửi chị Phạm Thị Hồng, nhắc đúng số thẻ, hẹn hoàn tiền 3 ngày.
- **Ý nghĩa:** giao dịch viên dùng AI soạn thư mà số thẻ khách không rời khỏi ngân hàng.

## Kế toán – đề nghị thanh toán

**Prompt:** `Lập đề nghị thanh toán 15.000.000 đồng cho nhà cung cấp, người nhận Hoàng Minh Quân, số tài khoản 0071000123456 tại Vietcombank.`

- **AI nhận:** `… người nhận [PERSON_01], số tài khoản [BANK_ACCOUNT_01] tại Vietcombank.`
- **Đi đâu:** Ollama (local).
- **Người dùng thấy:** phiếu đề nghị thanh toán có đủ tên người nhận, số tài khoản thật, số tiền 15.000.000 đồng.
- **Ý nghĩa:** số tiền và tên ngân hàng vẫn giữ nguyên để AI làm đúng việc; chỉ phần định danh bị che.

## Nhân sự – quyết định thôi việc

**Prompt:** `Soạn quyết định thôi việc cho nhân viên Võ Thanh Tùng, CCCD 079123456789, ngày sinh 12/03/1995, email tung.vo@congty.vn.`

- **AI nhận:** `… cho nhân viên [PERSON_01], CCCD [CCCD_01], ngày sinh [DOB_01], email [EMAIL_01].`
- **Đi đâu:** Ollama (local), vì có CCCD.
- **Người dùng thấy:** quyết định thôi việc điền đủ họ tên, CCCD, ngày sinh; các mục số quyết định, ngày hiệu lực để `..........`.

## Tuyển dụng – thư mời phỏng vấn

**Prompt:** `Viết thư mời phỏng vấn cho ứng viên Huỳnh Ngọc Trâm, SĐT +84 905 123 456, email tram.huynh@example.com, vị trí Kế toán tổng hợp.`

- **AI nhận:** `… cho ứng viên [PERSON_01], SĐT [PHONE_01], email [EMAIL_01], vị trí Kế toán tổng hợp.`
- **Đi đâu:** Gemini (cloud) – chỉ có dữ liệu mức trung bình và đã được che.
- **Người dùng thấy:** thư mời gửi Huỳnh Ngọc Trâm; thời gian, địa điểm phỏng vấn để `..........`.
- **Ý nghĩa:** số điện thoại dạng quốc tế có dấu cách vẫn được nhận diện.

## Giáo dục – thư báo điểm cho phụ huynh

**Prompt:** `Viết thư báo điểm cho phụ huynh học sinh Bùi Gia Bảo lớp 10A1, điểm Toán 4.5, gửi về email phuhuynh.bao@gmail.com và số 0934567890.`

- **AI nhận:** `… phụ huynh học sinh [PERSON_01] lớp 10A1, điểm Toán 4.5, gửi về email [EMAIL_01] và số [PHONE_01].`
- **Đi đâu:** Gemini (cloud).
- **Người dùng thấy:** thư lịch sự gửi phụ huynh em Bùi Gia Bảo, nêu điểm Toán 4.5 và đề xuất phụ đạo.

## Pháp lý – hợp đồng thuê nhà (hai người)

**Prompt:** `Soạn hợp đồng thuê nhà giữa bên A là Ngô Văn Hải, CCCD 001089012345, và bên B là Lý Thị Hoa, SĐT 0978123456, giá thuê 5 triệu đồng/tháng.`

- **AI nhận:** `… bên A là [PERSON_01], CCCD [CCCD_01], và bên B là [PERSON_02], SĐT [PHONE_01], giá thuê 5 triệu đồng/tháng.`
- **Đi đâu:** Ollama (local).
- **Người dùng thấy:** hợp đồng ghi đúng Bên A: Ngô Văn Hải, Bên B: Lý Thị Hoa, không bị lẫn hai người.
- **Ý nghĩa:** hai người khác nhau nhận hai token khác nhau (`PERSON_01`, `PERSON_02`), nên AI không nhầm vai.

## Du lịch – xác nhận đặt vé

**Prompt:** `Viết email xác nhận đặt vé đi Tokyo cho Dương Minh Anh, hộ chiếu C1234567, ngày sinh 20/11/1998, email minhanh@example.com.`

- **AI nhận:** `… cho [PERSON_01], hộ chiếu [PASSPORT_01], ngày sinh [DOB_01], email [EMAIL_01].`
- **Đi đâu:** Ollama (local), vì có số hộ chiếu.

## IT – báo cáo sự cố an ninh

**Prompt:** `Máy chủ 192.168.10.25 bị quét cổng từ IP 203.113.45.10 lúc 2 giờ sáng, viết báo cáo sự cố gửi trưởng phòng.`

- **AI nhận:** `Máy chủ [IP_ADDRESS_01] bị quét cổng từ IP [IP_ADDRESS_02] lúc 2 giờ sáng, …`
- **Đi đâu:** Gemini (cloud).
- **Người dùng thấy:** báo cáo sự cố có đúng hai địa chỉ IP, mốc thời gian, đề xuất chặn IP.
- **Ý nghĩa:** hạ tầng nội bộ không bị lộ ra ngoài.

## IT – dán nhầm mật khẩu (Block)

**Prompt:** `Server báo lỗi kết nối database, file cấu hình có password=Admin@2026 và host 10.0.12.5, sửa giúp tôi.`

- **Kết quả:** BLOCK, không gọi AI.
- **Ý nghĩa:** tình huống rất hay gặp thật: lập trình viên dán nguyên file cấu hình để nhờ AI sửa lỗi.

---

## Giới hạn cần biết (không dùng khi demo, nhưng nên chuẩn bị câu trả lời)

| Tình huống | Hiện trạng | Cách trả lời khi bị hỏi |
|---|---|---|
| Địa chỉ nhà không có từ khóa, ví dụ "25 Lê Lợi, phường Bến Nghé" | Chỉ nhận diện địa chỉ khi có từ khóa ("địa chỉ", "thường trú", "nơi ở"…) và có số nhà/đơn vị hành chính; không có từ khóa thì "Lê Lợi" bị che như họ tên | Địa chỉ không có định dạng cố định nên regex khó nhận; hướng phát triển là NER |
| Thông tin sức khỏe, ví dụ "chẩn đoán tăng huyết áp, dị ứng penicillin" | Tên và SĐT bệnh nhân được che, nhưng chẩn đoán vẫn gửi đi và không bị coi là nhạy cảm, nên đi Gemini | Chẩn đoán là nội dung AI cần để trả lời nên không thể che; hướng phát triển là nhận diện chủ đề y tế để tự chuyển sang xử lý local |
| Tên nước ngoài hoặc họ ngoài danh sách | Không được nhận diện (danh sách đã có ~60 họ, gồm Kim, Mai, Đinh, Trương…) | Hướng phát triển là NER |
