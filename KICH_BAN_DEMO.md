# Kịch bản demo Privacy AI Gateway v0.5.0 (~10 phút)

Mọi prompt và kết quả "Màn hình sẽ thấy" dưới đây đã được chạy thử qua hệ thống thật. Riêng câu
trả lời của AI mỗi lần một khác; phần đó ghi những điểm cần kiểm tra, không phải câu chữ chính xác.

Mỗi màn gồm: **Mục tiêu** (chứng minh điều gì), **Thao tác**, **Màn hình sẽ thấy**, **Bên trong
hệ thống** (để giải thích khi được hỏi), **Lời nói** (đọc gần như nguyên văn), **Nếu thầy hỏi**.

> Ý chính của cả buổi demo: **quyết định bảo mật được đưa ra trước khi gọi AI, không giao cho AI.**
> AI chỉ nhận nội dung đã được phép hoặc đã che; phản hồi được quét lần hai trước khi hiển thị.

---

## 0. Chuẩn bị (làm trước 30 phút)

**Cấu hình `.env`** (sửa xong thì khởi động lại server):

```ini
AI_MODE=hybrid                 # bắt buộc: chế độ gemini sẽ không bao giờ gọi Ollama
EGRESS_LOG_ENABLED=true        # để cửa sổ giám sát thấy request gửi đi
OLLAMA_KEEP_ALIVE=30m          # mặc định 2m: model tự nhả RAM, đến màn Hybrid sẽ nạp lại rất chậm
APP_SECRET=<chuỗi ngẫu nhiên dài>
TOKEN_VAULT_KEY=<chuỗi ngẫu nhiên dài khác>
GEMINI_API_KEY=<key mới tạo riêng cho buổi demo>
```

Tạo chuỗi ngẫu nhiên: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

**Checklist:**

- [ ] `.\.venv\Scripts\python.exe -m pytest -q` → **138 passed**.
- [ ] `ollama list` có `gemma3:4b`; chạy `ollama run gemma3:4b "xin chào"` để nạp sẵn model vào RAM.
- [ ] Xóa dữ liệu cũ cho màn hình sạch: dừng server, xóa `data\privacy_gateway.db` và `data\egress.log`
      (hệ thống tự tạo lại khi khởi động).
- [ ] Khởi động: `.\run_demo.ps1`, mở `http://127.0.0.1:8000`, đăng nhập `demo / demo123`.
      `run_demo.ps1` luôn chạy `pip install` nên cần mạng; nếu mất mạng, chạy thẳng
      `.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.
- [ ] Góc trên phải giao diện phải hiện **`Mode hybrid · mock:on · gemini:on · ollama:on`**
      (rê chuột vào để xem chi tiết từng provider).
- [ ] **Bỏ tích** ô "Cho phép dùng ký ức đã làm sạch từ phiên khác" (chỉ bật lại ở màn 7).
      Để nguyên ô "Lưu phiên hiện tại…" được tích.
- [ ] Phóng to trình duyệt (Ctrl + +), tắt thông báo hệ điều hành, chỉ dùng dữ liệu giả.

**Bố trí 3 cửa sổ** (chia đôi màn hình):

| Vị trí | Cửa sổ | Vai trò |
|---|---|---|
| Trái | Trình duyệt | Thứ người dùng thấy |
| Phải trên | PowerShell chạy `watch_egress.py` | **Thứ AI thật sự nhận được** |
| Phải dưới | PowerShell trống | Chạy `ollama ps`, pytest khi cần |

Lệnh cho cửa sổ phải trên:

```powershell
.\.venv\Scripts\python.exe scripts\watch_egress.py --tim "Nguyễn Văn An" 0901234567 an@example.com
```

> **Vì sao cần cửa sổ này:** giao diện web hiển thị prompt gốc của người dùng, không hiển thị
> bản đã che. Cửa sổ giám sát là nơi duy nhất cho hội đồng thấy **đúng nội dung rời khỏi máy**.

---

## Mở đầu (30 giây)

**Lời nói:**
"Khi nhân viên dán thông tin khách hàng vào ChatGPT hay Gemini, dữ liệu đó rời khỏi tổ chức ngay
lập tức. Privacy AI Gateway đứng giữa người dùng và AI: quét prompt, che hoặc chặn dữ liệu cá nhân
trước khi gửi, rồi khôi phục lại cho đúng người dùng khi hiển thị. Màn hình bên trái là thứ người
dùng thấy, bên phải là thứ AI thật sự nhận được."

---

## Màn 1 – Allow: prompt an toàn đi nguyên văn (45 giây)

**Mục tiêu:** gateway không làm hỏng câu hỏi bình thường.

**Thao tác:** gửi `Giải thích mô hình Zero Trust trong đúng 3 câu.`

**Màn hình sẽ thấy:**
- Thanh phân tích: `Policy: ALLOW · Không phát hiện dữ liệu thuộc phạm vi demo · PII: Không có`
- Nhãn dưới câu trả lời: `gemini · gemini-3.5-flash-lite · … ms`
- Cửa sổ giám sát: `GEMINI (CLOUD)`, nội dung giống hệt prompt, dòng xanh ✓.

**Bên trong:** PII Detector → không có phát hiện → Policy Engine chọn `allow` → AI Router (hybrid,
không nhạy cảm) chọn Gemini → Output Scanner quét phản hồi → hiển thị.

**Lời nói:** "Không có dữ liệu cá nhân nên gateway cho đi nguyên văn, đi Gemini vì nhanh và mạnh.
Dù vậy phản hồi vẫn được quét trước khi hiển thị."

---

## Màn 2 – Mask: AI chỉ thấy token, người dùng thấy dữ liệu thật (2 phút) ★ quan trọng nhất

**Mục tiêu:** dữ liệu cá nhân không rời khỏi máy, nhưng người dùng vẫn nhận kết quả dùng được ngay.

**Thao tác:** bấm **+ Phiên mới**, gửi:
`Viết email mời Nguyễn Văn An họp lúc 9 giờ sáng thứ Hai, số điện thoại 0901234567, email an@example.com.`

**Màn hình sẽ thấy:**
- Thanh phân tích (vàng): `Policy: MASK · Dữ liệu cá nhân phải được che giấu trước khi gọi AI · PII: PERSON, PHONE, EMAIL`
- **Cửa sổ giám sát** – chỉ vào từng dòng:
  ```
  ── GEMINI (CLOUD) ──
        user: Viết email mời [PERSON_01] họp lúc 9 giờ sáng thứ Hai, số điện thoại [PHONE_01], email [EMAIL_01].
    ✓ Bộ nhận diện không thấy dữ liệu cá nhân trong request gửi đi
    ✓ Không thấy "Nguyễn Văn An" trong request
    ✓ Không thấy "0901234567" trong request
    ✓ Không thấy "an@example.com" trong request
  ```
- Trình duyệt: email hoàn chỉnh "Kính gửi **Nguyễn Văn An**", có đúng số và email thật,
  không còn `[PERSON_01]`.

**Bên trong:**
1. Detector tìm 3 vùng PII; Masker thay bằng `[PERSON_01]`, `[PHONE_01]`, `[EMAIL_01]`.
2. Ánh xạ token → giá trị thật được **mã hóa Fernet** và lưu vào Token Vault, gắn với đúng
   user + phiên; không bao giờ gửi đi.
3. Gemini trả lời bằng token. Output Scanner quét phản hồi (bắt PII do AI tự bịa).
4. Chỉ token có trong vault của đúng user/phiên mới được khôi phục để hiển thị. SQLite chỉ lưu
   bản còn token.

**Lời nói:** "Bên phải là đúng body HTTP sắp gửi tới Google: chỉ còn token. Bên trái, người dùng
vẫn nhận email điền sẵn tên và số thật, vì hệ thống khôi phục ở phía mình, sau khi AI trả lời.
Ánh xạ token được mã hóa và chỉ chủ phiên mới giải mã được."

**Mời hội đồng tự kiểm chứng (rất nên làm):**
"Thầy/cô có thể đọc một cái tên và số điện thoại bất kỳ, em sẽ dò đúng các giá trị đó." Dừng cửa
sổ giám sát (Ctrl+C), chạy lại với giá trị hội đồng đọc:
```powershell
.\.venv\Scripts\python.exe scripts\watch_egress.py --tim "<tên hội đồng đọc>" <số hội đồng đọc>
```
rồi gửi prompt chứa đúng các giá trị đó. Phép dò này không dùng bộ nhận diện của hệ thống, và vẫn
báo THẤY nếu giá trị lọt ra dưới dạng khác (mất dấu, viết hoa, `090 123 4567`, `+84 …`).

**Nếu thầy hỏi "log do app tự ghi, sao tin được?"** → xem mục Hỏi đáp, câu 1.

---

## Màn 3 – Lượt tiếp theo: cùng người thì cùng token (45 giây)

**Mục tiêu:** hệ thống giữ được ngữ cảnh hội thoại mà vẫn không lộ dữ liệu.

**Thao tác:** trong **cùng phiên**, gửi:
`Thêm câu nhắc Nguyễn Văn An mang laptop và gọi lại số 090 123 4567 nếu bận.`
(cố ý viết số có dấu cách)

**Màn hình sẽ thấy:**
- Cửa sổ giám sát: `Thêm câu nhắc [PERSON_01] mang laptop và gọi lại số [PHONE_01] nếu bận.`
  Lịch sử gửi kèm (lượt trước) cũng chỉ có token.
- Trình duyệt: email được sửa, vẫn đúng tên và số thật.

**Bên trong:** Masker đọc vault của phiên, thấy giá trị đã có thì dùng lại token cũ. So sánh sau khi
chuẩn hóa nên `090 123 4567` và `0901234567` là cùng một số → cùng `[PHONE_01]`.

**Lời nói:** "Cùng một người luôn là cùng một token, kể cả khi viết số theo cách khác, nên AI hiểu
đây vẫn là anh An ở lượt trước."

---

## Màn 4 – Không che nhầm (30 giây, chọn 1–2 prompt)

**Mục tiêu:** gateway không phá hỏng câu hỏi bằng cách che thừa.

| Prompt | Kết quả | Vì sao |
|---|---|---|
| `Lý do chính khiến hồ sơ bị trả lại là gì?` | ALLOW | "Lý do", "hồ sơ" bắt đầu bằng họ Lý, Hồ nhưng là từ thường |
| `Mã đơn hàng 1234 5678 9012 3456 bị giao trễ, viết lời xin lỗi khách.` | ALLOW | 16 số nhưng không qua kiểm tra Luhn nên không phải số thẻ |
| `Thanh toán 150.000.000 đồng vào tài khoản công ty trước ngày 15.` | ALLOW | Số tiền đứng sau "tài khoản" không bị nhầm là số tài khoản |

**Lời nói:** "Che thừa cũng là lỗi, vì AI mất thông tin cần để trả lời. Hệ thống phân biệt từ thông
dụng với họ tên, mã đơn hàng với số thẻ, số tiền với số tài khoản."

---

## Màn 5 – Block: bí mật không bao giờ rời gateway (45 giây)

**Mục tiêu:** có loại dữ liệu không được gửi đi dưới bất kỳ hình thức nào.

**Thao tác:** gửi
`Server báo lỗi kết nối database, file cấu hình có password=Admin@2026 và host 10.0.12.5, sửa giúp tôi.`

**Màn hình sẽ thấy:**
- Thanh phân tích **đỏ**: `Policy: BLOCK · Phát hiện mật khẩu, API key hoặc access token · PII: SECRET, IP_ADDRESS`
- Trình duyệt: "Yêu cầu đã bị chặn trước khi gọi AI."
- Cửa sổ giám sát: **không có dòng mới**. Đây là bằng chứng AI không được gọi.

**Bên trong:** Policy Engine thấy `SECRET` → `block` ngay, AI Router không chạy, không lưu phiên,
không vào Token Vault; audit chỉ ghi loại sự kiện.

**Lời nói:** "Đây là tình huống rất hay gặp: lập trình viên dán nguyên file cấu hình nhờ AI sửa lỗi.
Mật khẩu không thể che rồi gửi như họ tên, vì chỉ cần lộ một lần. Request dừng ngay tại gateway."

*Thêm nếu còn giờ:* gửi `Mật khẩu mạnh là gì?` → ALLOW. Câu hỏi về mật khẩu vẫn đi được; chỉ khi có
giá trị mật khẩu thật mới bị chặn.

---

## Màn 6 – Hybrid: dữ liệu rủi ro cao ở lại máy local (1 phút 30)

**Mục tiêu:** dữ liệu rủi ro cao không lên cloud, kể cả khi đã che.

**Thao tác:** bấm **+ Phiên mới**, gửi:
`Kiểm tra giúp tôi hồ sơ vay của Trần Minh Khoa, CCCD 012345678901, số thẻ 4111 1111 1111 1111.`
Sau đó ở cửa sổ phải dưới chạy `ollama ps`.

**Màn hình sẽ thấy:**
- `Policy: MASK · … · PII: PERSON, CCCD, BANK_CARD`
- Nhãn: **`ollama · gemma3:4b · … ms`** (không phải gemini)
- Cửa sổ giám sát: **`OLLAMA (LOCAL)`**, URL `http://127.0.0.1:11434/api/chat`
- `ollama ps`: model `gemma3:4b` đang chạy trên laptop.

**Bên trong:** CCCD và số thẻ có mức rủi ro `high` → quyết định `sensitive=True` → ở chế độ hybrid,
router chọn Ollama. Tên, SĐT, email chỉ ở mức `medium` nên màn 2 vẫn đi Gemini.

**Lời nói:** "Token đã che giá trị, nhưng AI vẫn biết đây là hồ sơ vay có CCCD và số thẻ, đó là
metadata. Với dữ liệu rủi ro cao, hệ thống không để cả metadata rời khỏi máy."

**Tùy chọn – fallback an toàn:** tắt Ollama (thoát Ollama ở khay hệ thống) rồi gửi lại prompt trên.
- Nhãn: `mock · deterministic-demo · … · fallback ollama: Không kết nối được Ollama…`
- Cửa sổ giám sát: không có request nào tới Gemini.

"Ollama hỏng thì hệ thống trả lời bằng Mock, chứ không đẩy dữ liệu nhạy cảm lên cloud. Kể cả khi
cấu hình fallback bị đặt nhầm thành Gemini, router vẫn chặn." Nhớ bật lại Ollama sau đó.

---

## Màn 7 – Bộ nhớ chéo phiên chỉ mang ngữ cảnh đã làm sạch (1 phút 30)

**Mục tiêu:** AI nhớ được việc cũ, nhưng không mang dữ liệu thật sang phiên khác.

**Thao tác:**
1. Bấm **+ Phiên mới**, **tích** ô "Cho phép dùng ký ức đã làm sạch từ phiên khác".
2. Gửi `Tôi vừa nhờ bạn viết email mời ai họp?`
3. Bỏ tích ô đó, bấm **+ Phiên mới**, gửi lại đúng câu hỏi.

**Màn hình sẽ thấy:**
- Lần 1: nhãn có thêm `· nhớ … mục từ phiên khác`; AI nhớ là có email mời họp, nhưng tên hiện là
  **"(họ tên đã ẩn)"**, không phải "Nguyễn Văn An".
- Lần 2: không còn "nhớ … mục", AI không biết gì về phiên trước.

**Bên trong:** chỉ prompt đã che của **đúng tài khoản** được nạp. Token phiên cũ bị đổi thành nhãn
trước khi gửi AI, vì `[PERSON_01]` ở hai phiên là hai người khác nhau; dữ liệu gốc chỉ khôi phục
được trong đúng phiên đã tạo ra nó.

**Lời nói:** "Ký ức chéo phiên chỉ mang ngữ cảnh. Người dùng có công tắc để tắt, và có nút × để
xóa hẳn một phiên; dữ liệu quá hạn 7 ngày cũng tự bị xóa khỏi ổ đĩa."

---

## Màn 8 (nâng cao, nếu còn giờ) – Thử né bộ lọc (45 giây)

**Mục tiêu:** cho thấy bộ nhận diện không dễ qua mặt.

**Thao tác:** bấm **+ Phiên mới**, gửi:
`Gửi hồ sơ cho chị Đinh Thu Trang, CCCD của tôi là 001 203 012 345, SĐT 0901-234-567, email trang [at] example [dot] com, địa chỉ: 12 Lê Lợi, Quận 1, TP.HCM.`

**Màn hình sẽ thấy:**
- `PII: PERSON, CCCD, PHONE, EMAIL, ADDRESS`, nhãn `ollama` (vì có CCCD)
- Cửa sổ giám sát: `Gửi hồ sơ cho chị [PERSON_01], CCCD của tôi là [CCCD_01], SĐT [PHONE_01], email [EMAIL_01], địa chỉ: [ADDRESS_01].`

**Lời nói:** "CCCD có dấu cách, số điện thoại có gạch nối, email viết né bằng [at] [dot], họ Đinh ít
gặp, địa chỉ cụ thể: tất cả đều được che. Hệ thống còn chuẩn hóa Unicode, nên chữ số full-width
hay ký tự vô hình chèn giữa các số cũng không qua được."

---

## Màn 9 (khi bị hỏi về độ tin cậy) – Chạy test

Ở cửa sổ phải dưới:

```powershell
.\.venv\Scripts\python.exe -m pytest -q                                  # 138 passed
.\.venv\Scripts\python.exe -m pytest tests\test_watch_egress.py -v       # công cụ giám sát
```

Chỉ vào test **`test_watcher_catches_leak_when_masking_is_disabled`**: test cố tình tắt bộ che dữ
liệu, và công cụ giám sát phải báo THẤY cả tên, SĐT, email, CCCD.

"Công cụ kiểm chứng chỉ đáng tin nếu nó bắt được rò rỉ khi rò rỉ thật sự xảy ra. Test này chứng
minh nó không phải lúc nào cũng báo xanh."

---

## Kết (30 giây)

"Tóm lại: dữ liệu thường đi nguyên văn, dữ liệu cá nhân được che trước khi gửi và khôi phục cho
đúng chủ sở hữu, dữ liệu rủi ro cao ở lại máy, bí mật bị chặn hẳn. Mọi điều đó được kiểm chứng
bằng nội dung thật sự gửi đi chứ không chỉ bằng lời hệ thống tự báo cáo."

---

## Thứ tự và thời lượng

| # | Màn | Thời gian | Bắt buộc? |
|---|---|---|---|
| – | Mở đầu | 0:30 | ✓ |
| 1 | Allow | 0:45 | ✓ |
| 2 | Mask + giám sát + mời hội đồng dò | 2:00 | ✓ |
| 3 | Lượt 2, token dùng lại | 0:45 | ✓ |
| 4 | Không che nhầm | 0:30 | nên có |
| 5 | Block | 0:45 | ✓ |
| 6 | Hybrid + `ollama ps` | 1:30 | ✓ |
| 7 | Bộ nhớ chéo phiên | 1:30 | nên có |
| 8 | Né bộ lọc | 0:45 | nếu còn giờ |
| 9 | Chạy test | 1:00 | khi bị hỏi |
| – | Kết | 0:30 | ✓ |

---

## Sự cố và cách xử lý

| Sự cố | Xử lý | Câu nói |
|---|---|---|
| Gemini lỗi 429 / mất mạng | Prompt thường tự chuyển sang Ollama; nhãn hiện `fallback gemini: HTTP 429…` | "Đây là cơ chế dự phòng, một tính năng." |
| Ollama chậm hoặc timeout | Kiểm tra `ollama ps`; nếu model chưa nạp thì chạy `ollama run gemma3:4b "hi"` | "Lần nạp đầu tốn thời gian; hệ thống chuyển Mock chứ không lên cloud." |
| Thấy nhãn `mock` khi không mong đợi | Rê chuột vào góc health để xem provider nào `off` và lý do | — |
| Cửa sổ giám sát trống | Script có báo đỏ "EGRESS_LOG_ENABLED đang tắt" không? Bật trong `.env`, khởi động lại server | — |
| Bị khóa đăng nhập (429) | Chờ 60 giây hoặc khởi động lại server | "Giới hạn 5 lần sai mỗi phút để chống dò mật khẩu." |
| Server không chạy | Đọc lỗi: `AI_MODE`/provider sai thì ứng dụng báo rõ tên biến | — |
| Hỏng hoàn toàn | Chạy `AI_MODE=mock`: không cần mạng, không cần Ollama; mọi luồng che/chặn vẫn đúng | — |

---

## Hỏi đáp – câu trả lời chuẩn bị sẵn

**1. "Log do app của em ghi, sao tin được nó đúng?"**
- Chỉ có một cửa ra mạng: duy nhất `app/services/connectors.py` dùng thư viện mạng, và chỉ có 2 lời
  gọi POST mang dữ liệu người dùng (Gemini, Ollama); cả hai đều ghi log ngay trước khi gửi.
- Log ghi **chính object `payload`** được truyền vào `httpx.post(json=payload)`, không phải một bản sao.
- Test chặn ngay tại `httpx.AsyncClient.post` (tầng cuối trước khi ra mạng) và xác nhận body bắt được
  **trùng khớp với dòng log**.
- Có test đối chứng: tắt bộ che dữ liệu thì công cụ phải báo THẤY.
- Độc lập hoàn toàn với code: bắt gói tin. Ollama là HTTP trên localhost nên xem được bằng Wireshark
  (Npcap Loopback, lọc `tcp.port == 11434`); Gemini là HTTPS, xem bằng mitmproxy (đặt `HTTPS_PROXY`
  và `SSL_CERT_FILE` trỏ tới chứng chỉ CA của mitmproxy). Không chiếu phần header, vì header có API key.

**2. "Metadata là gì? AI có thấy dữ liệu thật không?"**
AI thấy `[PERSON_01]`, `[CCCD_01]`: biết **có** một người, **có** CCCD, ngữ cảnh là hồ sơ vay, nhưng
không biết tên hay số. Dữ liệu thật chỉ nằm trên trình duyệt người dùng và trong Token Vault đã mã
hóa trên máy. Vì metadata vẫn lộ ngữ cảnh, dữ liệu rủi ro cao được giữ ở Ollama.

**3. "Khi nào dùng Ollama, khi nào dùng Mock?"**
Ở chế độ hybrid: rủi ro cao → Ollama; thường → Gemini, Gemini lỗi thì sang Ollama. Mock là lớp dự
phòng cuối cùng, khi các model thật đều lỗi. Dữ liệu nhạy cảm mà Ollama lỗi → Mock, không bao giờ
lên Gemini, trừ khi chủ động chọn `AI_MODE=gemini`.

**4. "Regex bỏ sót thì sao?"**
Đúng, đây là giới hạn (xem bảng dưới). Thiết kế theo hướng che thừa hơn bỏ sót, và có egress log
cùng `--tim` để phát hiện khi lọt. PII Detector là module riêng, có thể thay bằng NER tiếng Việt mà
không đổi luồng xử lý.

**5. "Vì sao không để AI tự che dữ liệu?"**
Vì khi AI tự che thì dữ liệu gốc đã đến AI rồi. Nguyên tắc là quyết định trước khi gọi AI.

**6. "AI tự bịa token, hoặc tự bịa số điện thoại thì sao?"**
Output Scanner quét phản hồi. PII do AI tự sinh nhận token mới **không có trong vault**, nên hiển thị
thành "(số điện thoại đã ẩn)". Token mới đó còn được giữ chỗ, nên lượt sau không cấp trùng cho một
giá trị khác.

**7. "Hai request gửi cùng lúc trong một phiên có bị lẫn token không?"**
Không. Mỗi phiên xử lý tuần tự từng lượt (khóa theo phiên), ánh xạ đã lưu không bao giờ bị ghi đè;
có test gửi song song để kiểm chứng.

**8. "Người khác đoán được `conversation_id` thì sao?"**
Mọi truy vấn đều lọc theo `user_id`; sai chủ sở hữu trả 404, kể cả xem, chat tiếp hay xóa (chống IDOR).

**9. "Mất `TOKEN_VAULT_KEY` hoặc ai đó sửa database?"**
Không giải mã được → giao diện hiện "(… đã ẩn)", không lộ và không hiển thị sai dữ liệu. Test đã đọc
file `.db` theo từng byte: không có tên hay số điện thoại dạng rõ.

**10. "Bảo mật ứng dụng web thì sao?"**
Session cookie ký bằng `APP_SECRET`, SameSite=Strict; CSRF token cho mọi request ghi; giới hạn 5 lần
đăng nhập sai mỗi phút; không đoán được username tồn tại qua thời gian phản hồi; header CSP,
X-Frame-Options; API trả `Cache-Control: no-store`; giao diện chỉ dùng `textContent`, không có XSS.

---

## Giới hạn đã biết (chủ động nói nếu được hỏi)

| Tình huống | Hiện trạng | Hướng phát triển |
|---|---|---|
| Họ không có trong danh sách (~60 họ phổ biến), tên nước ngoài | Không nhận diện được | NER tiếng Việt |
| Địa chỉ không có từ khóa ("địa chỉ", "thường trú", "nơi ở"…) | Không nhận diện được | NER |
| Số viết bằng chữ ("không chín không một…") | Không nhận diện được | Chuẩn hóa chữ → số |
| Tên đường trùng tên người ("đường Lê Lợi") | Bị che như họ tên (che thừa, an toàn) | NER phân biệt địa danh |
| Thông tin sức khỏe ("chẩn đoán tăng huyết áp") | Không coi là nhạy cảm, nên đi Gemini | Nhận diện chủ đề y tế để chuyển sang local |
| Dãy 13–19 số không qua Luhn | Coi là mã thường (đúng ý đồ ở màn 4) | — |
