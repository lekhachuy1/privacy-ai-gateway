# Lời thoại thuyết trình – Privacy AI Gateway v0.5.0

_Tổng thời lượng khoảng 17 phút (7 phút slide + 10 phút demo), sau đó là phần hỏi đáp_

### Cách đọc tài liệu này

- Chữ thường là **lời nói**, đọc tự nhiên, không cần thuộc từng chữ.
- `[Trong ngoặc vuông]` là **hành động trên máy**, không đọc ra.
- Thời gian ghi cạnh tiêu đề là mức nên giữ.
- Kịch bản kỹ thuật chi tiết (cấu hình, checklist, xử lý sự cố) nằm trong file `KICH_BAN_DEMO.md`.

---

## PHẦN 1 – SLIDE (~7 phút)

### Slide 1 – Bìa (0:30)

Kính chào thầy cô và các bạn. Nhóm em xin trình bày đồ án CDIO4 với đề tài **Privacy AI Gateway**, phiên bản 0.5.0.

Hiện nay nhiều người dùng chatbot AI hằng ngày trong công việc. Câu hỏi nhóm em đặt ra là: làm sao vẫn dùng được AI mà dữ liệu cá nhân không bị gửi ra ngoài?

Phần trình bày gồm bốn phần: vấn đề, kiến trúc giải pháp, demo trực tiếp, và cuối cùng là giới hạn cùng hướng phát triển.

### Slide 2 – Vấn đề (0:45)

Thực tế khi dùng chatbot, người dùng thường dán nguyên văn thông tin vào prompt. Ví dụ: “Viết email cho anh Nguyễn Văn An, số điện thoại này, email này”. Có người còn dán cả mật khẩu hoặc API key để nhờ AI sửa lỗi cấu hình.

Việc này tạo ra ba rủi ro.

- **Thứ nhất**, bản thân prompt đã chứa dữ liệu cá nhân.
- **Thứ hai**, prompt đó được gửi thẳng lên máy chủ của nhà cung cấp AI bên ngoài. Từ lúc đó tổ chức không còn kiểm soát được dữ liệu.
- **Thứ ba**, dữ liệu còn nằm lại trong lịch sử hội thoại và log, nên rủi ro rò rỉ kéo dài về sau.

### Slide 3 – Giải pháp (0:45)

Giải pháp của nhóm em là một **Privacy Gateway**, tức là một lớp trung gian đứng giữa người dùng và mô hình AI. Mọi prompt đều phải đi qua gateway, và gateway đưa ra một trong ba quyết định:

- **Allow**: không phát hiện dữ liệu nhạy cảm, prompt được gửi nguyên văn.
- **Mask**: có dữ liệu cá nhân, gateway thay dữ liệu đó bằng token như `[PERSON_01]` rồi mới gọi AI.
- **Block**: có mật khẩu, API key hoặc access token, request dừng ngay tại gateway và AI không được gọi.

Nguyên tắc quan trọng nhất: quyết định bảo mật được đưa ra **trước** khi gọi AI, và do gateway quyết định chứ không giao cho AI.

### Slide 4 – Kiến trúc 8 bước (1:00)

Đây là luồng xử lý khi người dùng gửi một câu hỏi.

1. **PII Detector** chuẩn hóa Unicode để chống các cách viết né, rồi dùng biểu thức chính quy tìm họ tên, email, số điện thoại, CCCD, số thẻ, số tài khoản, địa chỉ và các loại secret.
2. **Policy Engine** quyết định Allow, Mask hay Block, đồng thời đánh dấu prompt có thuộc mức rủi ro cao hay không.
3. **Masker** thay dữ liệu bằng token. Cùng một giá trị trong một phiên luôn nhận cùng một token.
4. Ánh xạ từ token về giá trị gốc được **mã hóa** rồi lưu vào **Token Vault**, gắn với đúng người dùng và đúng phiên.
5. **AI Router** chọn nhà cung cấp: Mock, Gemini trên cloud, Ollama chạy local, hoặc kết hợp ở chế độ Hybrid.
6. Mô hình AI chỉ nhận được `safe_prompt`. Hai ô màu tối trên slide là phần duy nhất chạm tới AI.
7. **Output Scanner** quét lại phản hồi. Nếu AI tự sinh ra dữ liệu cá nhân mới thì dữ liệu đó cũng bị che.
8. Chỉ những token thuộc đúng phiên của người dùng mới được khôi phục để hiển thị.

Toàn bộ hệ thống chạy bằng FastAPI và SQLite trên một laptop Windows.

### Slide 5 – Các loại dữ liệu (0:45)

Bảng này tóm tắt các loại dữ liệu hệ thống nhận diện, cùng mức rủi ro và hành động tương ứng.

- **Secret**: mật khẩu, mã OTP, API key, token truy cập, private key, chuỗi kết nối database. Mức Critical, bị **Block**.
- **CCCD/CMND, hộ chiếu, số thẻ, số tài khoản, giấy phép lái xe, mã số thuế, số BHXH/BHYT**: mức High. Bị Mask, và ở chế độ Hybrid được xử lý bằng mô hình local.
- **Họ tên, số điện thoại, email, ngày tháng, địa chỉ IP, địa chỉ nhà cụ thể, biển số xe**: mức Medium, bị Mask.

Với số thẻ, hệ thống kiểm tra bằng thuật toán Luhn để không nhận nhầm các dãy số dài như mã đơn hàng. Toàn bộ ví dụ trên slide là dữ liệu giả.

### Slide 6 – Token Vault (1:00)

Đây là điểm mới của phiên bản 0.5: **khôi phục dữ liệu có kiểm soát**.

Dòng thứ nhất là prompt gốc người dùng nhập. Nó chỉ tồn tại trên trình duyệt và trong bộ nhớ của backend.

Dòng thứ hai là `safe_prompt`: tên, số điện thoại và email đều đã thành token. Đây là thứ duy nhất được gửi cho AI và cũng là thứ duy nhất được lưu vào cơ sở dữ liệu.

Ánh xạ từ token về giá trị gốc được mã hóa bằng Fernet và lưu riêng trong bảng `token_vault`, gắn với đúng người dùng và đúng phiên.

Dòng thứ ba: khi AI trả lời có chứa `[PERSON_01]`, Output Scanner quét trước, sau đó backend mới đổi token thành tên thật để hiển thị cho người dùng.

- Token không có trong vault, hoặc thuộc người dùng khác, sẽ không bao giờ được khôi phục.
- Một token đã gán thì không bao giờ đổi giá trị, nên tin nhắn cũ luôn hiển thị đúng.
- Ánh xạ hết hạn sau 7 ngày và bị xóa hẳn khỏi ổ đĩa.
- Secret không bao giờ vào vault, vì đã bị Block từ đầu.

### Slide 7 – Định tuyến Hybrid (0:45)

AI Router có bốn chế độ. Nhóm em tập trung vào chế độ **Hybrid**:

- Prompt an toàn và prompt chứa dữ liệu cá nhân cơ bản đã mask ưu tiên Gemini. Nếu Gemini lỗi thì hệ thống thử Ollama, rồi đến Mock.
- Prompt chứa dữ liệu rủi ro cao như CCCD, hộ chiếu hay số thẻ, dù đã mask, vẫn được giữ lại xử lý bằng Ollama trên máy local. Nếu Ollama lỗi thì hệ thống chuyển sang Mock, **tuyệt đối không đẩy lên cloud**.

Lý do là token chỉ che giá trị, còn ngữ cảnh, tức metadata, vẫn cho AI biết đây là hồ sơ có CCCD hay số thẻ. Với dữ liệu rủi ro cao, nhóm em không để cả metadata rời khỏi máy.

Router còn được cứng hóa thêm: kể cả khi cấu hình đặt nhầm provider nhạy cảm hoặc provider dự phòng là Gemini, dữ liệu rủi ro cao vẫn không lên cloud. Chỉ khi người quản trị chủ động chọn chế độ Gemini cho mọi prompt thì mới đi cloud.

### Slide 8 – Bảo mật ứng dụng (0:40)

Một gateway bảo vệ dữ liệu thì bản thân nó cũng phải an toàn.

- Mật khẩu được băm bằng PBKDF2-SHA256 với 210 nghìn vòng lặp. Thời gian phản hồi đăng nhập như nhau dù tài khoản có tồn tại hay không, nên không dò được tên đăng nhập.
- Session dùng cookie SameSite Strict, và mọi thao tác ghi đều phải có CSRF token.
- Đăng nhập sai quá 5 lần trong 60 giây thì hệ thống tạm chặn.
- Mọi truy vấn đến phiên và đến Token Vault đều kiểm tra đúng chủ sở hữu, để chống lỗi IDOR.
- Có header bảo mật chống nhúng trang và chèn script; phản hồi API không được trình duyệt lưu cache.
- Cơ sở dữ liệu chỉ lưu nội dung đã làm sạch; audit log chỉ ghi metadata, không ghi nội dung prompt.

### Slide 9 – Chuyển sang demo (0:15)

Bây giờ nhóm em xin demo trực tiếp, khoảng 10 phút. Màn hình bên trái là thứ người dùng thấy. Màn hình bên phải là cửa sổ giám sát, hiển thị **đúng nội dung thật sự rời khỏi máy** để gửi tới AI.

`[Chuyển sang trình duyệt đã đăng nhập sẵn. Cửa sổ PowerShell chạy watch_egress.py ở bên phải. Ô “ký ức chéo phiên” đang bỏ tích.]`

---

## PHẦN 2 – DEMO (~10 phút)

### Màn 1 – Allow (0:45)

`[Gõ: Giải thích mô hình Zero Trust trong đúng 3 câu.]`

Đầu tiên là một câu hỏi bình thường, không có dữ liệu cá nhân.

`[Chỉ vào thanh phân tích: Policy: ALLOW.]`

PII Detector không phát hiện gì, nên Policy Engine chọn Allow.

`[Chỉ sang cửa sổ giám sát: GEMINI (CLOUD), nội dung giống hệt prompt.]`

Bên phải là nội dung gửi lên Gemini, giống hệt câu em vừa gõ.

`[Chỉ vào nhãn dưới câu trả lời.]`

Nhãn này cho biết câu trả lời đến từ Gemini, tên model và thời gian xử lý. Dù là prompt an toàn, phản hồi vẫn được Output Scanner quét trước khi hiển thị.

### Màn 2 – Mask và khôi phục (2:00) ★ quan trọng nhất

`[Bấm “+ Phiên mới”. Gõ: Viết email mời Nguyễn Văn An họp lúc 9 giờ sáng thứ Hai, số điện thoại 0901234567, email an@example.com.]`

Bây giờ em gửi một prompt có họ tên, số điện thoại và email.

`[Chỉ vào thanh phân tích màu vàng: MASK · PII: PERSON, PHONE, EMAIL.]`

Hệ thống phát hiện ba loại dữ liệu: họ tên, số điện thoại và email.

`[Chỉ sang cửa sổ giám sát, đọc từng dòng.]`

Đây là đúng body HTTP sắp gửi tới Google. Tên đã thành `[PERSON_01]`, số điện thoại thành `[PHONE_01]`, email thành `[EMAIL_01]`. Ba dòng xanh bên dưới là phép dò nguyên văn ba giá trị gốc trên toàn bộ request: không tìm thấy.

`[Chỉ vào câu trả lời trên trình duyệt.]`

Nhưng trên màn hình, email lại hiện đúng tên Nguyễn Văn An, đúng số và email thật. Lý do là em là chủ phiên này, nên backend dùng Token Vault đổi token về giá trị thật, và việc đổi này chỉ diễn ra sau khi AI đã trả lời và Output Scanner đã quét xong.

Tóm lại: **AI chưa bao giờ nhìn thấy tên thật, nhưng người dùng vẫn nhận được câu trả lời dùng được ngay.**

Để thầy cô không phải tin lời nhóm em: thầy cô có thể đọc một cái tên và một số điện thoại bất kỳ, em sẽ dò đúng các giá trị đó.

`[Ctrl+C cửa sổ giám sát, chạy lại với --tim "<tên>" <số> do hội đồng đọc, rồi gửi một prompt chứa đúng các giá trị đó.]`

Phép dò này không dùng bộ nhận diện của hệ thống. Nó vẫn báo “THẤY” nếu giá trị lọt ra dưới bất kỳ dạng nào: mất dấu, viết hoa, hay viết số có dấu cách.

### Màn 3 – Lượt tiếp theo: cùng người, cùng token (0:45)

`[Trong cùng phiên, gõ: Thêm câu nhắc Nguyễn Văn An mang laptop và gọi lại số 090 123 4567 nếu bận.]`

Em hỏi tiếp trong cùng phiên, và cố ý viết số điện thoại có dấu cách.

`[Chỉ sang cửa sổ giám sát: [PERSON_01], [PHONE_01]; phần lịch sử gửi kèm cũng chỉ có token.]`

Cùng một người luôn là cùng một token, kể cả khi số được viết theo cách khác, nên AI hiểu đây vẫn là anh An ở lượt trước. Lịch sử hội thoại gửi kèm cũng đã được làm sạch.

### Màn 4 – Không che nhầm (0:30)

`[Gõ: Mã đơn hàng 1234 5678 9012 3456 bị giao trễ, viết lời xin lỗi khách. (Nếu còn giờ: Lý do chính khiến hồ sơ bị trả lại là gì?)]`

Che thừa cũng là lỗi, vì AI mất thông tin cần để trả lời. Dãy 16 số này không qua kiểm tra Luhn nên không phải số thẻ, và được gửi nguyên văn. Tương tự, “Lý do”, “hồ sơ” bắt đầu bằng họ Lý, họ Hồ nhưng không bị coi là tên người.

### Màn 5 – Block (0:45)

`[Gõ: Server báo lỗi kết nối database, file cấu hình có password=Admin@2026 và host 10.0.12.5, sửa giúp tôi.]`

Tiếp theo là tình huống rất hay gặp: lập trình viên dán nguyên file cấu hình để nhờ AI sửa lỗi.

`[Chỉ vào thanh phân tích màu đỏ: BLOCK.]`

Request bị dừng ngay tại gateway. Không có phản hồi AI, không có nhãn provider.

`[Chỉ sang cửa sổ giám sát: không có dòng mới.]`

Cửa sổ giám sát không có dòng mới nào, nghĩa là không có gì được gửi ra ngoài. Mật khẩu không thể che rồi gửi như họ tên, vì chỉ cần lộ một lần là đủ nguy hiểm. Secret cũng không được lưu, audit chỉ ghi lại một lần Block.

### Màn 6 – Hybrid: dữ liệu rủi ro cao ở lại máy (1:30)

`[Bấm “+ Phiên mới”. Gõ: Kiểm tra giúp tôi hồ sơ vay của Trần Minh Khoa, CCCD 012345678901, số thẻ 4111 1111 1111 1111.]`

Prompt này có số CCCD và số thẻ, thuộc mức rủi ro cao.

`[Chỉ vào nhãn: ollama · gemma3:4b. Chỉ sang cửa sổ giám sát: OLLAMA (LOCAL), địa chỉ 127.0.0.1.]`

Dữ liệu đã được che, nhưng hệ thống vẫn chọn mô hình Gemma chạy ngay trên laptop này. Cửa sổ giám sát cho thấy request đi tới địa chỉ 127.0.0.1, tức chính máy này, không phải Google.

`[Sang terminal, chạy: ollama ps]`

Lệnh này cho thấy model đang chạy trên chính laptop. Dữ liệu rủi ro cao không rời khỏi máy, kể cả dưới dạng token.

`[Tùy chọn: thoát Ollama ở khay hệ thống rồi gửi lại prompt trên. Nhớ bật lại Ollama sau đó.]`

Nếu Ollama gặp sự cố, hệ thống trả lời bằng Mock chứ không đẩy prompt lên Gemini. Nhãn “fallback” cho biết lý do, và cửa sổ giám sát không có request nào tới cloud.

### Màn 7 – Bộ nhớ chéo phiên (1:30)

`[Bấm “+ Phiên mới”, tích ô “Cho phép dùng ký ức đã làm sạch từ phiên khác”. Gõ: Tôi vừa nhờ bạn viết email mời ai họp?]`

Hệ thống có thể nhớ việc ở phiên trước, nhưng chỉ nhớ bản đã làm sạch.

`[Chỉ vào nhãn “nhớ … mục từ phiên khác” và chữ “(họ tên đã ẩn)” trong câu trả lời.]`

AI nhớ được là có một email mời họp, nhưng không biết tên, và màn hình hiện “họ tên đã ẩn” chứ không hiện tên thật. Đây là thiết kế có chủ đích: ký ức chéo phiên chỉ mang ngữ cảnh, còn dữ liệu gốc chỉ khôi phục được trong đúng phiên đã tạo ra nó.

`[Bỏ tích ô đó, bấm “+ Phiên mới”, hỏi lại đúng câu đó.]`

Khi tắt công tắc, phiên mới hoàn toàn tách biệt, AI không còn biết gì về phiên cũ. Người dùng tự kiểm soát việc này.

`[Bấm × để xóa phiên Mask ở thanh bên.]`

Người dùng có quyền xóa phiên. Khi xóa, tin nhắn và ánh xạ trong Token Vault của phiên đó cũng bị xóa theo. Dữ liệu quá hạn 7 ngày cũng tự bị xóa khỏi ổ đĩa.

### Màn 8 – Thử né bộ lọc (0:45, nếu còn giờ)

`[Bấm “+ Phiên mới”. Gõ: Gửi hồ sơ cho chị Đinh Thu Trang, CCCD của tôi là 001 203 012 345, SĐT 0901-234-567, email trang [at] example [dot] com, địa chỉ: 12 Lê Lợi, Quận 1, TP.HCM.]`

Cuối cùng em thử các cách viết né: CCCD có dấu cách, số điện thoại có gạch nối, email viết bằng [at] [dot], họ Đinh ít gặp và một địa chỉ cụ thể.

`[Chỉ sang cửa sổ giám sát: tất cả đã thành token; nhãn ollama vì có CCCD.]`

Tất cả đều được che. Hệ thống còn chuẩn hóa Unicode, nên chữ số full-width hay ký tự vô hình chèn giữa các số cũng không qua được.

### Màn 9 – Chạy test (chỉ khi được hỏi về độ tin cậy)

`[Ở terminal: .\.venv\Scripts\python.exe -m pytest -q  →  138 passed]`

Toàn bộ 138 test tự động đều đạt. Em xin chỉ một test quan trọng: test này cố tình tắt bộ che dữ liệu, và công cụ giám sát phải báo “THẤY” cả tên, số điện thoại, email và CCCD. Công cụ kiểm chứng chỉ đáng tin nếu nó bắt được rò rỉ khi rò rỉ thật sự xảy ra, và test này chứng minh nó không phải lúc nào cũng báo xanh.

---

## PHẦN 3 – KẾT THÚC (~2 phút)

`[Từ màn hình demo, quay lại slide 12.]`

### Slide 12 – Cải tiến sau rà soát (0:50)

Sau khi rà soát toàn bộ mã nguồn, nhóm em đã cứng hóa hệ thống ở ba nhóm.

- **Nhận diện**: chuẩn hóa Unicode để chống viết né; nhận được CCCD có dấu cách, CMND 9 số, số cố định, email viết bằng [at] [dot]; bổ sung địa chỉ, giấy phép lái xe, mã số thuế, BHXH, biển số xe và khoảng 60 họ phổ biến; đồng thời giảm che nhầm với số tiền và từ thông dụng.
- **Logic token và định tuyến**: token không bao giờ bị cấp trùng, kể cả khi AI tự sinh dữ liệu hay hai request đến cùng lúc; dữ liệu quá hạn bị xóa ngay trong lúc chạy; dữ liệu rủi ro cao không lên cloud kể cả khi cấu hình sai.
- **Bảo mật ứng dụng và kiểm chứng**: chống dò tên đăng nhập, thêm header bảo mật; công cụ giám sát bắt được rò rỉ ở mọi định dạng.

Bộ test tăng từ 25 lên **138 test**, trong đó có test chặn ngay tại lời gọi mạng và test đối chứng chứng minh công cụ giám sát thật sự bắt được rò rỉ.

### Slide 13 – Giới hạn và hướng phát triển (0:40)

Nhóm em cũng nhìn nhận rõ giới hạn. Đây là một prototype học thuật, chưa phải một hệ thống ngăn rò rỉ dữ liệu hoàn chỉnh.

- Nhận diện bằng biểu thức chính quy có thể sót: tên có họ ngoài danh sách, địa chỉ không có từ khóa, số viết bằng chữ.
- Thông tin sức khỏe như chẩn đoán bệnh chưa được coi là nhạy cảm.
- Giới hạn đăng nhập lưu trong RAM, nên chỉ phù hợp khi chạy một tiến trình.

Nhóm em chọn thiết kế **thà che thừa còn hơn bỏ sót**, và có công cụ giám sát để phát hiện khi có lọt. Hướng phát triển gồm:

- dùng mô hình nhận dạng thực thể (NER) cho tiếng Việt;
- nhận diện chủ đề nhạy cảm như y tế để tự chuyển sang xử lý local;
- dùng Redis và PostgreSQL khi mở rộng ra nhiều máy chủ;
- thêm phân quyền quản trị, dashboard audit, triển khai HTTPS với quản lý khóa tập trung.

### Slide 14 – Kết luận (0:20)

Tóm lại, mô hình của nhóm em không giao quyết định bảo mật cho AI. Privacy Gateway áp dụng chính sách trước, AI chỉ nhận nội dung đã được phép hoặc đã che giấu, phản hồi được quét lần thứ hai trước khi hiển thị, và mọi điều đó được kiểm chứng bằng nội dung thật sự gửi đi chứ không chỉ bằng lời hệ thống tự báo cáo.

Nhóm em xin cảm ơn thầy cô và các bạn đã lắng nghe, và rất mong nhận được câu hỏi cũng như góp ý.

---

## PHẦN 4 – CÂU HỎI THẦY CÔ CÓ THỂ HỎI

_Mẹo trả lời: trả lời thẳng trong 1–2 câu trước, rồi mới giải thích. Nếu đó là giới hạn thật thì thừa nhận, sau đó nói hướng khắc phục._

### A. Về ý tưởng và phạm vi

**1. Tại sao không để chính AI tự che dữ liệu cá nhân?**
Vì khi đó dữ liệu gốc đã được gửi tới AI rồi, và mục tiêu của đề tài là dữ liệu không rời khỏi hệ thống. Ngoài ra, hành vi của mô hình ngôn ngữ không xác định được trước, nên không thể dùng nó làm lớp kiểm soát bảo mật.

**2. Đề tài khác gì so với các giải pháp DLP có sẵn?**
Các giải pháp DLP doanh nghiệp thường chặn ở tầng mạng hoặc tầng email. Đề tài của nhóm tập trung vào luồng prompt gửi tới AI, và có thêm cơ chế khôi phục dữ liệu cho đúng người dùng, để AI vẫn hữu ích. Về độ phủ nhận diện, sản phẩm thương mại mạnh hơn nhiều; đây là prototype học thuật.

**3. Đề tài liên quan gì tới quy định pháp luật về dữ liệu cá nhân?**
Đề tài hướng tới các nguyên tắc tối thiểu hóa dữ liệu, giới hạn thời gian lưu trữ và quyền xóa dữ liệu, theo tinh thần Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân. Danh mục dữ liệu nhận diện (CCCD, hộ chiếu, giấy phép lái xe, biển số xe, mã số thuế, số bảo hiểm, tài khoản ngân hàng…) bám theo nhóm dữ liệu cá nhân cơ bản trong nghị định. (Kiểm tra lại văn bản pháp luật hiện hành trước khi trích dẫn.)

### B. Về nhận diện dữ liệu

**4. Tại sao dùng regex mà không dùng AI/NER để nhận diện?**
Regex nhẹ, chạy tức thì, cho kết quả xác định và dễ giải thích, phù hợp với laptop 16 GB đang phải chạy thêm Ollama. Bộ nhận diện xử lý prompt 4.000 ký tự trong khoảng 10 mili giây, kể cả với input cố tình gây chậm. Nhược điểm là dễ sót, nên hướng phát triển là NER tiếng Việt. PII Detector là module riêng, thay thế được mà không đổi luồng xử lý.

**5. Nếu nhận diện sót, ví dụ một cái tên có họ không nằm trong danh sách, thì sao?**
Khi đó tên đó sẽ bị gửi đi. Đây là giới hạn thật của đề tài. Có ba cách giảm rủi ro: danh sách đã mở rộng lên khoảng 60 họ phổ biến; công cụ giám sát egress giúp phát hiện khi có lọt; và chế độ Hybrid giữ dữ liệu rủi ro cao ở local. Hướng lâu dài là NER.

**6. Nếu nhận diện nhầm, ví dụ một mã đơn hàng bị coi là số thẻ, thì sao?**
Nhận nhầm theo hướng an toàn: dữ liệu bị che thừa, câu trả lời có thể kém chính xác hơn một chút, nhưng không bị lộ. Nhóm đã giảm che nhầm bằng kiểm tra Luhn cho số thẻ, phân biệt số tiền với số tài khoản, và phân biệt các từ như “Lý do”, “hồ sơ”, “Hà Nội” với họ tên.

**7. Người dùng cố tình viết né thì sao: tên không dấu, số có dấu cách, chữ số full-width?**
Hệ thống chuẩn hóa Unicode NFKC và loại ký tự vô hình trước khi nhận diện. Tên không dấu như “Le Van A” được nhận diện; số điện thoại có dấu cách, gạch nối, mã +84; CCCD có dấu cách; email viết bằng [at] [dot] đều được che. Có bộ test riêng cho các cách né này. Còn số viết bằng chữ như “không chín không một” thì chưa xử lý được.

### C. Về Token Vault và khôi phục

**8. Token Vault mã hóa như thế nào? Khóa để ở đâu?**
Hệ thống dùng Fernet trong thư viện cryptography, kết hợp mã hóa AES-128-CBC với HMAC-SHA256, nên dữ liệu vừa được mã hóa vừa chống sửa đổi. Khóa được sinh từ biến `TOKEN_VAULT_KEY` trong `.env`, không nằm trong cơ sở dữ liệu. Test đã đọc file SQLite theo từng byte và xác nhận không có tên hay số điện thoại dạng rõ.

**9. Nếu lộ hoặc mất TOKEN_VAULT_KEY, hoặc ai đó sửa database thì sao?**
- Mất khóa hoặc bản ghi bị sửa: không giải mã được, giao diện hiện “(… đã ẩn)”, không lộ và không hiển thị sai dữ liệu.
- Lộ cả khóa lẫn file cơ sở dữ liệu: dữ liệu trong vault có thể bị đọc, nên khóa phải được bảo vệ, môi trường thật nên dùng dịch vụ quản lý khóa.
- Điểm có thể cải tiến: khóa đang được dẫn xuất bằng SHA-256; nên thay bằng hàm dẫn xuất khóa chuẩn như HKDF.

**10. AI tự bịa ra một token, ví dụ [PERSON_99], thì có bị khôi phục nhầm không?**
Không. Hệ thống chỉ khôi phục những token có trong vault của đúng người dùng và đúng phiên. Token lạ hiển thị thành nhãn “(họ tên đã ẩn)”.

**11. AI tự sinh ra một số điện thoại mới trong câu trả lời thì sao?**
Output Scanner phát hiện số đó và thay bằng một token mới. Token này không có trong vault nên không bao giờ được đổi lại thành số thật. Token đó còn được giữ chỗ, nên ở lượt sau một số khác của người dùng không bị cấp trùng token và không bị hiển thị nhầm.

**12. Hai request gửi cùng lúc trong một phiên có bị lẫn token không?**
Không. Mỗi phiên xử lý tuần tự từng lượt, và một token đã gán thì không bao giờ bị ghi đè. Có test gửi hai request song song để kiểm chứng.

**13. Người dùng khác đoán được mã phiên thì có xem được dữ liệu không?**
Không. Mọi truy vấn đều kiểm tra cả mã phiên lẫn user_id; sai chủ sở hữu thì trả về 404, kể cả khi xem, chat tiếp hay xóa. Ngoài ra mã phiên là UUID ngẫu nhiên, rất khó đoán.

### D. Về AI, định tuyến và kiểm chứng

**14. Metadata là gì? AI có thấy dữ liệu thật không?**
AI không thấy dữ liệu thật, chỉ thấy token như [PERSON_01], [CCCD_01]. Từ đó AI biết có một người, có một CCCD, ngữ cảnh là hồ sơ vay, đó là metadata, nhưng không biết tên hay số. Dữ liệu thật chỉ nằm trên trình duyệt người dùng và trong Token Vault đã mã hóa trên máy.

**15. Đã mask rồi thì tại sao vẫn giữ prompt rủi ro cao ở local?**
Vì metadata vẫn có thể giúp suy ra danh tính, ví dụ “kiểm tra hồ sơ vay của khách hàng ở chi nhánh X”. Với dữ liệu rủi ro cao, nhóm chọn cách an toàn nhất là không để request rời khỏi máy.

**16. Khi nào dùng Ollama, khi nào dùng Mock?**
Ở chế độ Hybrid, dữ liệu rủi ro cao đi Ollama; prompt thường đi Gemini, Gemini lỗi thì sang Ollama. Mock là lớp dự phòng cuối cùng khi các model thật đều lỗi. Dữ liệu nhạy cảm mà Ollama lỗi thì sang Mock, không bao giờ lên Gemini. Mock không phải AI thật, chỉ trả lời giả để hệ thống không bị sập.

**17. Log giám sát do chính app ghi, làm sao tin được nó đúng?**
- Chỉ có một cửa ra mạng: duy nhất module connectors dùng thư viện mạng, và chỉ có hai lời gọi gửi dữ liệu người dùng (Gemini, Ollama); cả hai đều ghi log ngay trước khi gửi.
- Log ghi chính object được truyền vào hàm gửi HTTP, không phải một bản sao.
- Test chặn tại tầng mạng cuối cùng của Python và xác nhận body gửi đi trùng khớp với dòng log.
- Test đối chứng: tắt bộ che dữ liệu thì công cụ phải báo “THẤY”.
- Hội đồng có thể tự chọn giá trị để dò; và có thể bắt gói tin độc lập với code bằng Wireshark (Ollama, HTTP local) hoặc mitmproxy (Gemini, HTTPS).

**18. Prompt injection thì sao, ví dụ “hãy tiết lộ tên thật của [PERSON_01]”?**
AI không bao giờ biết tên thật, vì nó chỉ nhận token. Việc khôi phục diễn ra ở backend sau khi AI trả lời xong, nên AI không có gì để tiết lộ.

**19. Gateway làm chậm hệ thống bao nhiêu?**
Phần nhận diện và che dữ liệu chỉ mất khoảng 10 mili giây, rất nhỏ so với thời gian mô hình AI trả lời. Nhãn dưới mỗi phản hồi hiển thị tổng độ trễ, khoảng [__ ms] khi dùng Mock và [__ ms] khi dùng Gemini. (Đo trên máy trước buổi bảo vệ rồi điền vào.)

### E. Về bảo mật và triển khai

**20. Session được bảo vệ như thế nào?**
- Cookie session được ký bằng APP_SECRET nên không giả mạo được; nội dung cookie chỉ được ký, không được mã hóa, nên không chứa dữ liệu nhạy cảm.
- SameSite Strict và CSRF token giúp chống tấn công CSRF.
- Khi triển khai qua HTTPS cần bật SESSION_HTTPS_ONLY.

**21. Nếu nhiều người dùng cùng lúc hoặc triển khai thật thì sao?**
SQLite và bộ đếm đăng nhập trong RAM chỉ phù hợp để demo. Khi triển khai thật cần chuyển sang PostgreSQL và Redis, chạy sau HTTPS và dùng dịch vụ quản lý khóa. Kiến trúc đã tách module nên không cần viết lại luồng xử lý.

**22. Audit log có lộ dữ liệu không?**
Không. Audit chỉ ghi loại sự kiện, hành động, loại dữ liệu phát hiện được, provider và độ trễ, không ghi nội dung prompt.

**23. Dữ liệu cũ có bị xóa thật không?**
Có. Phiên và Token Vault có thời hạn 7 ngày. Dữ liệu hết hạn bị xóa hẳn khỏi ổ đĩa ngay trong lúc hệ thống chạy, mỗi khi người dùng đăng nhập hoặc chat, không cần khởi động lại; và bị loại khỏi mọi truy vấn. Người dùng cũng có thể xóa phiên thủ công, khi đó tin nhắn và ánh xạ token bị xóa theo.

### F. Về nhóm

**24. Phân công công việc trong nhóm như thế nào?**
[Điền: ai làm backend, ai làm nhận diện/policy, ai làm frontend, ai làm kiểm thử và báo cáo.]

**25. Khó khăn lớn nhất khi làm đề tài là gì?**
[Gợi ý: cân bằng giữa che dữ liệu và độ hữu ích của câu trả lời; giữ token nhất quán qua nhiều lượt hội thoại mà không cấp trùng; chứng minh được dữ liệu không rời khỏi máy; chạy Ollama trên laptop có RAM hạn chế.]
