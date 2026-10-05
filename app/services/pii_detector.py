from dataclasses import asdict, dataclass
from typing import Callable
import ipaddress
import re
import unicodedata


@dataclass(frozen=True)
class Detection:
    kind: str
    start: int
    end: int
    risk: str
    preview: str

    def public(self) -> dict:
        return asdict(self)


# Token do gateway sinh ra, ví dụ [PERSON_01]. Đặt ở đây để detector bỏ qua
# vùng token (không nhận diện chồng lên token) và masker dùng chung định dạng.
TOKEN_PATTERN = re.compile(r"\[(?P<kind>[A-Z_]+)_(?P<number>\d{2,})\]")

# Ký tự vô hình hay bị chèn vào giữa số/chữ để né regex ("0901\u200b234567").
_INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u180e\u200b\u200c\u200d\u2060\ufeff"))


def normalize_text(text: str) -> str:
    """Chuẩn hóa trước khi nhận diện.

    NFKC dựng sẵn dấu tiếng Việt (bộ gõ tổ hợp tạo "Nguyễn" khác mã), đổi chữ số
    full-width "０９０…" và khoảng trắng đặc biệt về dạng thường; sau đó bỏ ký tự
    vô hình. Không chuẩn hóa thì mẫu nhận diện bỏ sót và dữ liệu thật lọt ra ngoài.
    """
    return unicodedata.normalize("NFKC", text).translate(_INVISIBLE)


# Dấu phân cách giữa các chữ số: một khoảng trắng, dấu chấm hoặc gạch, có thể
# kèm khoảng trắng hai bên ("0901 - 234 - 567").
SEP = r"[ \t]?[.\-]?[ \t]?"
# Không dừng giữa một nhóm số: sau giá trị không được là chữ số hoặc ".123"/"-123".
END_OF_NUMBER = r"(?![ \t]?[.\-][ \t]?\d|\d)"
# Số tiền đứng sau từ khóa ("tài khoản 15.000.000 đồng") không phải số tài khoản.
NOT_MONEY = r"(?!\s*(?:(?:đ|đồng|dong|vnd|vnđ|usd|triệu|trieu|tr|nghìn|nghin|ngàn|ngan|k)\b|\$))"
# Phần chữ nằm giữa từ khóa và con số ("CCCD của tôi là 0..."), không vượt qua
# chữ số hoặc dấu kết thúc câu để không bắt nhầm số ở câu sau.
FILLER = r"[^\d\n.!?;]{0,30}?"

SECRET_KEYWORDS = (
    r"(?:password|passwd|pwd|passcode|mật\s*khẩu|mat\s*khau|mã\s*pin|ma\s*pin|pin\s*code|"
    r"mã\s*otp|ma\s*otp|otp|api[_ -]?key|secret(?:[_ -]?key)?|client[_ -]?secret|"
    r"access[_ -]?token|refresh[_ -]?token|auth[_ -]?token|private[_ -]?key)"
)
# Cho phép vài từ chỉ chủ sở hữu/loại tài khoản giữa từ khóa và giá trị.
SECRET_QUALIFIERS = (
    r"(?:\s+(?:của\s+(?:tôi|em|anh|chị|mình|bạn)|wifi|wi-fi|email|gmail|facebook|fb|zalo|"
    r"instagram|ig|tiktok|shopee|momo|icloud|ngân\s*hàng|tài\s*khoản|đăng\s*nhập|admin|root|"
    r"database|db|mới|cũ|hiện\s*tại|nhà(?:\s+(?:tôi|em|mình|anh|chị))?)){0,3}"
)
# Viết tắt hay gặp khi chat ("pass wifi:", "mk fb là ..."). Tách riêng vì "pass"
# cũng là từ tiếng Anh thông dụng: chỉ chặn khi có ":"/"=" hoặc giá trị có số/ký hiệu.
SECRET_SHORT = r"(?:pass|pw|mk|mật\s*mã|mat\s*ma)"
# Tên biến môi trường/cấu hình chứa bí mật: DB_PASSWORD=, AWS_SECRET_ACCESS_KEY=,
# GITHUB_TOKEN=. Dấu "_" là ký tự chữ nên \b của mẫu từ khóa không bắt được.
ENV_SECRET_NAME = (
    r"[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|PRIVATE_?KEY|ACCESS_?KEY|CREDENTIALS?)"
    r"(?:_[A-Z0-9]+)*"
)

ADDRESS_KEYWORDS = (
    r"(?:địa\s*chỉ(?:\s*(?:nhà|thường\s*trú|tạm\s*trú|liên\s*hệ|liên\s*lạc|nhận\s*hàng|"
    r"giao\s*hàng|cư\s*trú))?|dia\s*chi|đ/c|nơi\s*(?:ở|cư\s*trú|thường\s*trú)|"
    r"hộ\s*khẩu(?:\s*thường\s*trú)?|thường\s*trú|tạm\s*trú|nhà\s*(?:tôi\s*|em\s*|mình\s*)?ở|"
    r"sống\s*tại|ở\s*tại)"
)
# Địa chỉ dừng ở cuối câu, hoặc trước thông tin khác/câu lệnh tiếp theo.
ADDRESS_END = (
    r"(?=\s*(?:[;\n]|$)"
    r"|(?<![ ,.][A-Za-zĐđ])(?<![Tt][Pp])\.(?=\s|$)"
    r"|,?\s*(?:và\s+)?(?:số\s*điện\s*thoại|sđt|sdt|điện\s*thoại|di\s*động|email|e-mail|cccd|cmnd|"
    r"căn\s*cước|ngày\s*sinh|stk|số\s*tài\s*khoản|hộ\s*chiếu)\b"
    r"|,\s*(?:hãy|vui\s*lòng|giúp|nhờ|viết|soạn|gửi|tạo|lập|làm|để|cần)\b)"
)
# Chỉ coi là địa chỉ cụ thể khi có số nhà hoặc đơn vị hành chính; "địa chỉ Đà
# Nẵng" (cấp tỉnh) không đủ để định danh nên giữ nguyên.
ADDRESS_DETAIL = re.compile(
    r"(?i)\d|\b(?:quận|huyện|phường|xã|thị\s*xã|thị\s*trấn|tỉnh|thành\s*phố|tp|đường|phố|thôn|"
    r"ấp|xóm|ngõ|ngách|hẻm|kiệt|tổ|khu\s*phố|kp|chung\s*cư|tòa|lầu|tầng|căn\s*hộ|"
    r"quan|huyen|phuong|tinh|duong|thon|hem)\b"
)

EMAIL_AT = r"(?:\s*@\s*|\s*[\[(]\s*(?:at|@|a\s*còng)\s*[\])]\s*|\s+a\s*còng\s+)"
EMAIL_DOT = r"(?:\.|\s*[\[(]\s*(?:dot|chấm)\s*[\])]\s*|\s+(?:dot|chấm)\s+)"


def _luhn_ok(value: str) -> bool:
    digits = [int(c) for c in value if c.isdigit()]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _ipv6_ok(value: str) -> bool:
    # "10:30:45" (giờ) không phải IPv6 hợp lệ nên không bị che nhầm.
    try:
        return isinstance(ipaddress.ip_address(value), ipaddress.IPv6Address)
    except ValueError:
        return False


def _address_ok(value: str) -> bool:
    return bool(ADDRESS_DETAIL.search(value))


def _iban_ok(value: str) -> bool:
    # ISO 13616: chuyển 4 ký tự đầu xuống cuối, đổi chữ thành số, chia dư 97 phải = 1.
    compact = re.sub(r"\s", "", value).upper()
    rearranged = compact[4:] + compact[:4]
    return int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1


# Địa chỉ viết tắt không có từ khóa: "268 Lý Thường Kiệt, P.14, Q.10, TP.HCM".
# Phải có số nhà, tên đường và ít nhất một cấp hành chính (phường/quận/TP...).
ADMIN_UNIT = (
    r"(?:p\.|phường|phuong|x\.|xã|q\.|quận|quan|h\.|huyện|huyen|tx\.|thị\s*xã|tt\.|thị\s*trấn|"
    r"tp\.?|thành\s*phố|tỉnh)"
)
ADDRESS_STOP = r"(?:giúp|giùm|nhé|nha|với|và|hãy|cho|để|trước|lúc|vào|ngay|nhanh|gấp|ạ)"
ADDRESS_WORD = rf"(?!{ADDRESS_STOP}\b)[^\W_]+\.?"
ADMIN_SEGMENT = re.compile(rf"(?i),\s*{ADMIN_UNIT}")
# "15 Phố Huế, ..." : từ chỉ đường ngay sau số nhà, tên đường viết hoa ("3 phố đi
# bộ, ..." không phải địa chỉ).
STREET_HEAD = re.compile(r"(?i)(?:số\s+)?\d[\w/]*\s+(?:đường|phố|ngõ|ngách|hẻm|kiệt)\s+(?P<next>\w)")


def _short_address_ok(value: str) -> bool:
    if ADMIN_SEGMENT.search(value):
        return True
    head = STREET_HEAD.match(value)
    return bool(head and (head.group("next").isupper() or head.group("next").isdigit()))


Validator = Callable[[str], bool] | None

# Thứ tự quan trọng: mẫu đứng trước chiếm chỗ, mẫu sau không được chồng lên.
# Mẫu có từ khóa đứng trước mẫu chỉ dựa vào hình dạng số để gán đúng loại.
PATTERNS: list[tuple[str, str, re.Pattern[str], Validator]] = [
    ("SECRET", "critical", re.compile(rf"(?i)\b{SECRET_KEYWORDS}{SECRET_QUALIFIERS}\s*[:=]\s*\S+"), None),
    # "mật khẩu là Abc@123": chỉ chặn khi giá trị có chữ số hoặc ký hiệu, để câu
    # hỏi như "mật khẩu mạnh là gì?" vẫn được gửi.
    ("SECRET", "critical", re.compile(
        rf"(?i)\b{SECRET_KEYWORDS}{SECRET_QUALIFIERS}\s+(?:là|la|is)\s+[\"'“]?"
        r"(?=\S*?(?:\d|[!@#$%^&*_+=~<>|\\/-]))\S+"
    ), None),
    ("SECRET", "critical", re.compile(rf"(?<![A-Za-z0-9])\b{ENV_SECRET_NAME}\s*[:=]\s*[\"']?[^\s\"']{{4,}}"), None),
    # JSON/YAML: {"password": "..."} — dấu ngoặc kép nằm giữa khóa và dấu ":".
    ("SECRET", "critical", re.compile(
        rf"(?i)[\"']{SECRET_KEYWORDS}[\"']\s*:\s*[\"'][^\"']{{3,}}[\"']"
    ), None),
    ("SECRET", "critical", re.compile(rf"(?i)\b{SECRET_SHORT}{SECRET_QUALIFIERS}\s*[:=]\s*\S{{3,}}"), None),
    ("SECRET", "critical", re.compile(
        rf"(?i)\b{SECRET_SHORT}{SECRET_QUALIFIERS}\s+(?:là|la|is)\s+[\"'“]?"
        r"(?=\S*?(?:\d|[!@#$%^&*_+=~<>|\\/-]))\S+"
    ), None),
    # CVV/CVC không bao giờ được lưu hay gửi đi (PCI DSS), nên chặn như secret.
    ("SECRET", "critical", re.compile(r"(?i)\b(?:cvv2?|cvc2?|cid)\s*(?:là|:|=)?\s*\d{3,4}(?!\d)"), None),
    ("SECRET", "critical", re.compile(r"\bsk-(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{16,}"), None),
    ("SECRET", "critical", re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{10,}"), None),
    ("SECRET", "critical", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"), None),
    ("SECRET", "critical", re.compile(r"\bAQ\.[A-Za-z0-9_-]{20,}"), None),
    ("SECRET", "critical", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), None),
    ("SECRET", "critical", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"), None),
    ("SECRET", "critical", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), None),
    ("SECRET", "critical", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+"), None),
    ("SECRET", "critical", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), None),
    ("SECRET", "critical", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}"), None),
    # Chuỗi kết nối chứa mật khẩu: postgres://user:pass@host
    ("SECRET", "critical", re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s:/@]+:[^\s@/]+@"), None),
    ("EMAIL", "medium", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), None),
    # Email viết né: "an [at] example [dot] com", "an @ example.com".
    ("EMAIL", "medium", re.compile(
        rf"(?i)\b[a-z0-9._%+-]+{EMAIL_AT}[a-z0-9-]+(?:{EMAIL_DOT}[a-z0-9-]+)*"
        rf"{EMAIL_DOT}(?:com|net|org|vn|edu|gov|io|info|biz|co)\b"
    ), None),
    ("ADDRESS", "medium", re.compile(
        rf"(?i)\b{ADDRESS_KEYWORDS}(?!\s*(?:email|e-mail|mail|ip|ipv4|ipv6|web|website|url|ví|mac)\b)"
        r"(?:\s*(?:của\s*(?:tôi|em|anh|chị|mình|bạn|khách(?:\s*hàng)?|công\s*ty)|hiện\s*(?:tại|nay)|mới))?"
        rf"\s*(?:là|tại|ở)?\s*[:\-]?\s*(?P<value>[^\n;]{{3,150}}?){ADDRESS_END}"
    ), _address_ok),
    ("ADDRESS", "medium", re.compile(
        rf"(?i)(?<![\w/.])(?:số\s+)?\d{{1,4}}[a-z]?(?:/\d{{1,4}}[a-z]?)*\s+{ADDRESS_WORD}(?:\s+{ADDRESS_WORD}){{0,5}}"
        rf"(?:,\s*(?:{ADMIN_UNIT}\s*)?{ADDRESS_WORD}(?:\s+{ADDRESS_WORD}){{0,3}}){{2,4}}"
    ), _short_address_ok),
    ("BANK_ACCOUNT", "high", re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}(?:[ ]?[A-Z0-9]{1,3})?\b"), _iban_ok),
    # Số tài khoản không có định dạng riêng nên chỉ nhận khi có từ khóa; chỉ phần
    # số (nhóm "value") bị che.
    ("BANK_ACCOUNT", "high", re.compile(
        r"(?i)\b(?:số\s*tài\s*khoản|so\s*tai\s*khoan|stk|tài\s*khoản(?:\s*số)?|tai\s*khoan|account(?:\s*number)?)"
        rf"{FILLER}[:.]?\s*(?P<value>(?<!\d)\d(?:{SEP}\d){{5,18}}){END_OF_NUMBER}{NOT_MONEY}"
    ), None),
    ("CCCD", "high", re.compile(
        r"(?i)\b(?:cccd|cmnd|cmt|căn\s*cước(?:\s*công\s*dân)?|can\s*cuoc(?:\s*cong\s*dan)?|"
        r"chứng\s*minh\s*(?:nhân\s*dân|thư)|chung\s*minh\s*nhan\s*dan|số\s*định\s*danh(?:\s*cá\s*nhân)?|"
        r"so\s*dinh\s*danh|id\s*card)"
        rf"{FILLER}[:.]?\s*(?P<value>(?<!\d)\d(?:{SEP}\d){{8,11}}){END_OF_NUMBER}"
    ), None),
    ("DRIVER_LICENSE", "high", re.compile(
        r"(?i)\b(?:gplx|giấy\s*phép\s*lái\s*xe|giay\s*phep\s*lai\s*xe|bằng\s*lái(?:\s*xe)?|bang\s*lai(?:\s*xe)?)"
        rf"{FILLER}[:.]?\s*(?P<value>(?<!\d)\d(?:{SEP}\d){{11}}){END_OF_NUMBER}"
    ), None),
    ("TAX_ID", "high", re.compile(
        r"(?i)\b(?:mã\s*số\s*thuế|ma\s*so\s*thue|mst|tax\s*code)"
        rf"{FILLER}[:.]?\s*(?P<value>(?<!\d)\d{{10}}(?:-\d{{3}})?)(?!\d)"
    ), None),
    ("INSURANCE", "high", re.compile(
        r"(?i)\b(?:bhxh|bhyt|bảo\s*hiểm\s*(?:xã\s*hội|y\s*tế)|bao\s*hiem\s*(?:xa\s*hoi|y\s*te))"
        rf"{FILLER}[:.]?\s*(?P<value>(?<![\w])(?:[A-Z]{{2}}\d{{13}}|\d(?:{SEP}\d){{9}})){END_OF_NUMBER}"
    ), None),
    ("INSURANCE", "high", re.compile(r"\b[A-Z]{2}\d{13}\b"), None),
    ("CCCD", "high", re.compile(r"(?<!\d)0\d{11}(?!\d)"), None),
    ("CCCD", "high", re.compile(r"(?<!\d)0\d{2}([ .\-])\d{3}\1\d{3}\1\d{3}(?!\d)"), None),
    ("CCCD", "high", re.compile(r"(?<!\d)0\d{3}([ .\-])\d{4}\1\d{4}(?!\d)"), None),
    # Di động 10 số và cố định 11 số, có/không mã quốc gia, cho phép ngoặc.
    ("PHONE", "medium", re.compile(r"(?<!\d)(?:\(?\+?84\)?|0)(?:[ \t]?[.\-()]?[ \t]?\d){9,10}(?!\d)"), None),
    # Dãy 13–19 số chỉ coi là thẻ khi qua Luhn; mã đơn hàng dài vẫn giữ nguyên.
    ("BANK_CARD", "high", re.compile(r"(?<!\d)\d(?:[ \t]?-?[ \t]?\d){12,18}(?!\d)"), _luhn_ok),
    ("PASSPORT", "high", re.compile(r"(?i)\b[A-Z]\d{7}\b"), None),
    ("LICENSE_PLATE", "medium", re.compile(r"(?<!\w)\d{2}[ \-]?[A-Z]{1,2}\d?[ \-]?\d{3}\.?\d{2}(?!\w)"), None),
    ("DOB", "medium", re.compile(
        r"(?<!\d)(?:0?[1-9]|[12]\d|3[01])[ \t]?([/.\-])[ \t]?(?:0?[1-9]|1[0-2])[ \t]?\1[ \t]?(?:19|20)\d{2}(?!\d)"
    ), None),
    ("DOB", "medium", re.compile(r"(?<!\d)(?:19|20)\d{2}-(?:0?[1-9]|1[0-2])-(?:0?[1-9]|[12]\d|3[01])(?!\d)"), None),
    ("DOB", "medium", re.compile(
        r"(?i)\bngày\s+(?P<value>(?:0?[1-9]|[12]\d|3[01])\s+tháng\s+(?:0?[1-9]|1[0-2])\s+năm\s+(?:19|20)\d{2})\b"
    ), None),
    ("IP_ADDRESS", "medium", re.compile(
        r"(?<!\d)(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?!\d)"
    ), None),
    ("IP_ADDRESS", "medium", re.compile(r"(?i)(?<![\w:.])[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){2,7}(?![\w:])"), _ipv6_ok),
]

SURNAMES = (
    "Nguyễn|Trần|Lê|Phạm|Hoàng|Huỳnh|Phan|Vũ|Võ|Đặng|Bùi|Đỗ|Hồ|Ngô|Dương|Lý"
    "|Đinh|Trịnh|Đoàn|Lâm|Mai|Cao|Lương|Tạ|Châu|Tô|Hà|Quách|Thái|Kiều|Đào|Lưu|Trương"
    "|Hứa|Văn|Tống|Triệu|Khổng|Mạc|Lại|Phùng|Chu|Doãn|Giang|Kim|Nghiêm|Thân|Tôn|Vương"
    "|Diệp|Đàm|Khúc|Thạch|La|Ninh"
    "|Nguyen|Tran|Le|Pham|Hoang|Huynh|Phan|Vu|Vo|Dang|Bui|Do|Ho|Ngo|Duong|Ly"
    "|Dinh|Trinh|Doan|Lam|Mai|Cao|Luong|Chau|Quach|Thai|Kieu|Dao|Luu|Truong|Hua|Trieu"
    "|Phung|Giang|Kim|Nghiem|Vuong|Diep|Ha|Ninh"
)
SURNAME_SET = {name.casefold() for name in SURNAMES.split("|")}
# Bắt họ + tối đa 4 từ phía sau; việc có phải tên hay không được quyết định
# trong _person_span theo cách viết hoa, vì "Lý do", "hồ sơ", "đỗ xe" cũng
# bắt đầu bằng một họ.
NAME_CANDIDATE = re.compile(rf"(?i)\b(?:{SURNAMES})(?:[ \t]+[^\W\d_]+){{1,4}}")
SURNAME_START = re.compile(rf"(?i)\b(?:{SURNAMES})\b")

# Họ trùng với từ thông dụng ("mai" = ngày mai, "hà", "cao", "lưu", "đào"...):
# khi viết thường không coi là tên; khi viết hoa mà ngay sau là một họ khác
# ("Mai Nguyễn Văn An") thì đó là từ đầu câu, tên thật bắt đầu từ họ sau.
AMBIGUOUS_SURNAMES = {
    "mai", "hà", "cao", "lâm", "kim", "giang", "thái", "châu", "văn", "chu", "lại", "tô", "tạ",
    "la", "lý", "hồ", "đỗ", "thân", "tôn", "đào", "lưu", "đoàn", "triệu", "ninh", "khúc", "mạc",
    "hứa", "ha", "lam", "thai", "chau", "ly", "ho", "do", "dao", "luu", "doan", "trieu", "hua",
}

# Tên viết thường chỉ được chấp nhận khi từ thứ hai là tên đệm phổ biến.
COMMON_MIDDLE_NAMES = {
    "văn", "thị", "hữu", "đức", "minh", "ngọc", "quang", "thanh", "xuân", "hoàng",
    "kim", "gia", "bảo", "anh", "thu", "hồng", "phương", "tuấn", "công", "đình",
    "van", "thi", "huu", "duc", "ngoc", "xuan", "hoang", "bao", "hong", "phuong",
    "tuan", "cong", "dinh",
}

# Cụm "họ + từ" là từ ghép thông dụng, kể cả khi viết hoa kiểu tiêu đề. Không
# đưa vào đây những từ cũng hay làm tên ("Nam", "Minh", "Bình"...): thà che
# thừa một cụm từ còn hơn để lọt tên thật.
NON_NAME_SECOND = {
    "do", "sơ", "xe", "hôn", "trụ", "thuật", "nội", "đẳng", "độ", "cấp", "học", "hóa", "hoá",
    "bản", "phòng", "kiện", "sàng", "nghiệp", "loại", "hồ", "màu", "ơn", "thực", "bổng", "mến",
    "tạo", "kết", "thể", "ý", "trữ", "khóa", "điển", "hẹn", "chứng", "giáo", "lục", "á", "âu",
    "tính", "tốc", "mốt", "tĩnh",
}

# Địa danh bắt đầu bằng một họ. Không đưa tên đường trùng tên người (Lê Lợi,
# Nguyễn Huệ...) vào đây vì người thật cũng có thể mang tên đó.
NOT_PERSON = {
    "hồ chí minh", "ho chi minh", "phan thiết", "phan rang", "hoàng sa", "lý sơn", "hồ tây",
    "hồ gươm", "hồ hoàn kiếm", "hà nội", "ha noi", "hà giang", "hà tĩnh", "hà nam", "cao bằng",
    "lâm đồng", "thái bình", "thái nguyên", "ninh bình", "ninh thuận", "bạch mai",
}

# Từ viết hoa đứng sau tên nhưng không thuộc tên ("Nguyễn Văn An Trưởng Phòng").
# Chỉ xét từ vị trí thứ ba trở đi, và chỉ gồm từ không bao giờ là tên riêng
# ("Khoa", "Trường", "Liên", "Công" đều có thể là tên nên không có ở đây).
TITLE_WORDS = {
    "trưởng", "phó", "giám", "đốc", "phòng", "ty", "tổ", "lớp", "quận", "huyện", "phường",
    "xã", "tỉnh", "phố", "tp", "gửi", "chào", "ông", "bà", "chị", "cô", "chú", "bác", "thầy",
    "và", "hoặc", "số", "tại", "ở", "đến", "mã", "ngày", "lúc", "qua", "gọi", "email", "sđt", "sdt",
}

NAME_STOPWORDS = {
    "qua", "với", "số", "email", "tại", "vào", "ngày", "và", "hoặc",
    "để", "cho", "của", "đang", "đã", "sẽ", "gửi", "viết", "soạn", "là", "có", "đi",
    "đến", "ở", "học", "làm", "nói", "gọi", "mang", "nhắn", "xin", "cần", "muốn",
    "được", "bị", "sinh", "lúc", "từ",
}


def _person_span(words: list[str]) -> int:
    """Số từ thuộc họ tên (0 nếu không phải tên)."""
    first, second = words[0], words[1]
    first_cf, second_cf = first.casefold(), second.casefold()
    if second_cf in NON_NAME_SECOND:
        return 0
    if first_cf in AMBIGUOUS_SURNAMES and second_cf in SURNAME_SET - AMBIGUOUS_SURNAMES:
        return 0
    all_caps = first.isupper() and len(first) > 1
    starts_upper = first[0].isupper() or (
        first_cf not in AMBIGUOUS_SURNAMES and len(words) >= 3 and words[2][0].isupper()
    )
    if starts_upper and second[0].isupper():
        count = 2
        while count < len(words):
            word = words[count]
            if not word[0].isupper() or word.casefold() in TITLE_WORDS:
                break
            if not all_caps and word.isupper() and len(word) > 1:
                break  # chữ viết tắt như "SĐT", "CCCD" đứng ngay sau tên
            count += 1
        return count
    if (
        all(word.islower() for word in words)
        and first_cf not in AMBIGUOUS_SURNAMES
        and second_cf in COMMON_MIDDLE_NAMES
        and len(words) >= 3
    ):
        count = min(len(words), 4)
        while count > 2 and words[count - 1] in NAME_STOPWORDS:
            count -= 1
        if count < 3:
            return 0
        return count
    return 0


def _is_place(value: str) -> bool:
    folded = " ".join(value.casefold().split())
    return any(folded == place or folded.startswith(place + " ") for place in NOT_PERSON)


def _preview(value: str) -> str:
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + "***" + value[-2:]


def detect(text: str) -> list[Detection]:
    found: list[Detection] = []
    occupied: set[int] = set()
    # Token gateway đã sinh ([PERSON_01]) không phải PII mới.
    for match in TOKEN_PATTERN.finditer(text):
        occupied |= set(range(*match.span()))
    for kind, risk, pattern, validator in PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span("value") if "value" in pattern.groupindex else match.span()
            value = text[start:end]
            if not value.strip():
                continue
            indexes = set(range(start, end))
            if occupied & indexes:
                continue
            if validator and not validator(value):
                continue
            occupied |= indexes
            found.append(Detection(kind, start, end, risk, _preview(value)))
    # Xét từng vị trí có họ một cách độc lập: nếu "Lý do Nguyễn Văn An" bị
    # finditer nuốt thành một ứng viên thì tên thật phía sau sẽ bị bỏ sót.
    for start in SURNAME_START.finditer(text):
        match = NAME_CANDIDATE.match(text, start.start())
        if not match or start.start() in occupied:
            continue
        words = match.group().split()
        count = _person_span(words)
        if not count:
            continue
        # Giữ đúng khoảng trắng gốc giữa các từ khi tính vị trí kết thúc.
        end = match.start() + len(re.match(rf"\S+(?:[ \t]+\S+){{{count - 1}}}", match.group()).group())
        value = text[match.start():end]
        if _is_place(value):
            continue
        indexes = set(range(match.start(), end))
        if not occupied & indexes:
            occupied |= indexes
            found.append(Detection("PERSON", match.start(), end, "medium", _preview(value)))
    return sorted(found, key=lambda item: item.start)
