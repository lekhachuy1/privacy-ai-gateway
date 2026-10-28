"""Image Guard: đọc chữ trong ảnh (OCR), che vùng chứa dữ liệu cá nhân, che mã QR
và xoá metadata EXIF trước khi bất kỳ phần nào của ảnh rời khỏi gateway.

OCR dùng Tesseract chạy cục bộ (CPU, offline), không gửi ảnh ra ngoài. Chữ đọc
được đi qua đúng PII Detector của luồng văn bản, nên quy tắc nhận diện chỉ có một.
"""
from dataclasses import dataclass, field
from io import BytesIO
import csv
import os
import re
import shutil
import statistics
import subprocess
import time
import unicodedata

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from ..config import ROOT
from .pii_detector import SURNAMES, Detection, detect, normalize_text

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "BMP"}
# Ảnh nhỏ (ảnh chụp màn hình thu nhỏ) OCR kém; phóng to trước khi đọc.
_MIN_OCR_WIDTH = 1600
_PAD = 4

# Dấu hiệu giấy tờ tuỳ thân: ảnh loại này thường không nên gửi đi dưới mọi hình thức.
_ID_DOCUMENT = re.compile(
    r"c[aă]n\s*c[uư][oớơ]c|citizen\s+identity|identity\s+card|ch[uứ]ng\s+minh\s+nh[aâ]n\s+d[aâ]n"
    r"|gi[aấ]y\s+ph[eé]p\s+l[aá]i\s+xe|driver'?s?\s+licen[cs]e|h[oộ]\s+chi[eế]u|passport",
    re.IGNORECASE,
)
# Lỗi OCR hay gặp trong dãy số: chữ O đọc nhầm số 0, chữ l/I đọc nhầm số 1...
# Giữ nguyên độ dài để vị trí ký tự vẫn khớp với ô chữ trên ảnh.
_OCR_DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "|": "1",
                                 "i": "1", "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2", "g": "9"})
# Dãy số dài trong ảnh: OCR đọc sai một chữ số hay dính thêm chữ ("số" -> "50")
# là trình kiểm tra (Luhn, đầu số 0...) trượt. Với ảnh, dãy từ 9 chữ số trở lên
# chưa được nhận diện vẫn bị che (thà che thừa mã đơn hàng còn hơn lọt số CCCD).
_LONG_NUMBER = re.compile(r"(?<![\w])\d(?:[ .\-]?\d){8,}(?![\w])")
_DIGITISH = re.compile(r"[0-9OoDQIl|iSsBZzg]+(?:[ .\-][0-9OoDQIl|iSsBZzg]+)*")


class OCRUnavailable(RuntimeError):
    pass


@dataclass
class Word:
    text: str
    box: tuple[int, int, int, int]  # left, top, right, bottom trên ảnh gốc
    line: tuple[int, int, int, int]  # khoá dòng: từ cùng khoá được ghép thành một dòng
    conf: float


@dataclass
class ImageReport:
    ocr_text: str
    detections: list[Detection]
    redacted_png: bytes
    boxes: list[dict]
    qr_codes: list[dict]
    id_document: bool
    exif_removed: bool
    gps_removed: bool
    ocr_fixes: int
    skew_degrees: float
    width: int
    height: int
    timings_ms: dict = field(default_factory=dict)


def tesseract_cmd() -> str | None:
    configured = os.getenv("TESSERACT_CMD", "").strip()
    if configured:
        return configured if os.path.exists(configured) else None
    found = shutil.which("tesseract")
    if found:
        return found
    default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    return default if os.path.exists(default) else None


def tessdata_dir() -> str | None:
    configured = os.getenv("TESSDATA_DIR", "").strip()
    local = ROOT / "data" / "tessdata"
    if configured:
        return configured
    return str(local) if (local / "vie.traineddata").exists() else None


def ocr_available() -> bool:
    return tesseract_cmd() is not None


def load_image(data: bytes) -> tuple[Image.Image, bool, bool]:
    """Mở ảnh an toàn. Trả về (ảnh RGB đã xoay đúng chiều, có EXIF, có GPS)."""
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"Ảnh lớn quá {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        image = Image.open(BytesIO(data))
        if image.format not in ALLOWED_FORMATS:
            raise ValueError("Chỉ nhận ảnh PNG, JPEG, WebP hoặc BMP")
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ValueError("Ảnh có độ phân giải quá lớn")
        exif = image.getexif()
        has_exif = bool(exif) or "exif" in image.info
        has_gps = bool(exif.get_ifd(0x8825)) if exif else False
        image = ImageOps.exif_transpose(image)
        image.load()
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("File không phải ảnh hợp lệ") from exc
    return image.convert("RGB"), has_exif, has_gps


def _tesseract_words(cmd: str, image: Image.Image, scale: float, lang: str, pass_no: int) -> list[Word]:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    args = [cmd, "stdin", "stdout", "-l", lang, "--psm", "11", "-c", "tessedit_create_tsv=1"]
    data_dir = tessdata_dir()
    if data_dir:
        args[3:3] = ["--tessdata-dir", data_dir]
    try:
        # Một luồng: kết quả lặp lại được giữa các lần chạy, ảnh nhỏ cũng không chậm hơn.
        env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
        result = subprocess.run(args, input=buffer.getvalue(), capture_output=True, timeout=60, check=True, env=env)
    except (subprocess.SubprocessError, OSError) as exc:
        raise OCRUnavailable(f"Tesseract lỗi: {exc}") from exc
    rows = csv.DictReader(result.stdout.decode("utf-8", "replace").splitlines(), delimiter="	", quoting=csv.QUOTE_NONE)
    words = []
    for row in rows:
        text = (row.get("text") or "").strip()
        if row.get("level") != "5" or not text:
            continue
        left, top = int(row["left"]) / scale, int(row["top"]) / scale
        width, height = int(row["width"]) / scale, int(row["height"]) / scale
        words.append(Word(
            text=normalize_text(text),
            box=(int(left), int(top), int(left + width + 0.999), int(top + height + 0.999)),
            line=(pass_no, int(row["block_num"]), int(row["par_num"]), int(row["line_num"])),
            conf=float(row.get("conf") or 0),
        ))
    return words


def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return False
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1
    return width * height / smaller > 0.3


def _polarity_normalized(gray: Image.Image) -> Image.Image | None:
    """Đưa mọi chữ về dạng đen trên nền trắng, bất kể màu nền tại chỗ.

    Ước lượng nền cục bộ bằng lọc trung vị cửa sổ lớn; điểm ảnh lệch xa nền là
    nét chữ. Nhờ vậy chữ trắng trong bong bóng chat xanh và chữ đen trên nền
    trắng được đọc trong cùng một lượt (Tesseract dùng ngưỡng toàn ảnh nên bỏ sót).
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    array = np.array(gray)
    background = cv2.medianBlur(array, 41)
    return Image.fromarray(np.where(cv2.absdiff(array, background) > 50, 0, 255).astype(np.uint8))


def _group_lines(words: list[Word]) -> list[Word]:
    """Xếp lại từ thành dòng theo vị trí trên ảnh (từ hai lượt OCR trộn lẫn).

    Hai từ cùng dòng khi chồng nhau theo chiều dọc quá nửa chiều cao; trong một
    dòng, khoảng trống quá lớn (cột khác của bảng) tách thành đoạn riêng để từ
    khoá ở cột này không bị ghép với con số ở cột kia.
    """
    rows: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (w.box[1] + w.box[3]) / 2):
        top, bottom = word.box[1], word.box[3]
        for row in rows:
            r_top = min(w.box[1] for w in row)
            r_bottom = max(w.box[3] for w in row)
            overlap = min(bottom, r_bottom) - max(top, r_top)
            if overlap > 0.5 * min(bottom - top, r_bottom - r_top):
                row.append(word)
                break
        else:
            rows.append([word])
    ordered: list[Word] = []
    for row_no, row in enumerate(rows):
        row.sort(key=lambda w: w.box[0])
        height = max(1, statistics.median(w.box[3] - w.box[1] for w in row))
        segment = 0
        for index, word in enumerate(row):
            if index and word.box[0] - row[index - 1].box[2] > 3 * height:
                segment += 1
            word.line = (row_no, segment, 0, 0)
            ordered.append(word)
    return ordered


def run_ocr(image: Image.Image, lang: str = "vie+eng") -> list[Word]:
    """OCR hai lượt: ảnh đã chuẩn hoá màu nền và ảnh xám gốc.

    Lượt chuẩn hoá đọc được chữ sáng trên nền tối; lượt xám gốc đọc tốt hơn khi
    ảnh mờ (nét chữ nhạt bị bước chuẩn hoá cắt mất). Từ trùng vị trí giữa hai
    lượt thì giữ từ có độ tin cậy OCR cao hơn.
    """
    cmd = tesseract_cmd()
    if not cmd:
        raise OCRUnavailable("Chưa cài Tesseract OCR trên máy chạy gateway")
    scale = max(1.0, _MIN_OCR_WIDTH / image.width)
    work = image if scale == 1.0 else image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    # Lọc trung vị 3x3 xoá nhiễu hạt tiêu (ảnh chụp tối, nén kém) mà không làm mất nét chữ đã phóng to.
    gray = ImageOps.autocontrast(work.convert("L").filter(ImageFilter.MedianFilter(3)))
    passes = [img for img in (_polarity_normalized(gray), gray) if img is not None]
    words: list[Word] = []
    for pass_no, img in enumerate(passes):
        for word in _tesseract_words(cmd, img, scale, lang, pass_no):
            clashing = [kept for kept in words if _overlaps(word.box, kept.box)]
            if not clashing:
                words.append(word)
            elif word.conf > max(kept.conf for kept in clashing):
                words = [kept for kept in words if kept not in clashing] + [word]
    return _group_lines(words)


def deskew(image: Image.Image, max_angle: float = 6.0, step: float = 0.5) -> tuple[Image.Image, float]:
    """Xoay thẳng ảnh chụp hơi nghiêng (dòng chữ chéo làm Tesseract đọc sai).

    Thử các góc trong ±max_angle trên ảnh thu nhỏ; góc đúng là góc mà tổng điểm
    đen theo từng hàng dao động mạnh nhất (dòng chữ và khoảng trắng tách bạch).
    """
    small = ImageOps.autocontrast(image.convert("L"))
    small.thumbnail((700, 700))
    binary = _polarity_normalized(small) or small.point(lambda v: 0 if v < 128 else 255)
    inverted = ImageOps.invert(binary)
    best_angle, best_score = 0.0, -1.0
    angle = -max_angle
    while angle <= max_angle + 1e-9:
        rotated = inverted.rotate(angle, resample=Image.NEAREST, expand=True)
        width, height = rotated.size
        data = rotated.tobytes()
        sums = [sum(data[row * width:(row + 1) * width]) for row in range(height)]
        mean = sum(sums) / height
        score = sum((v - mean) ** 2 for v in sums) / height
        if score > best_score:
            best_angle, best_score = angle, score
        angle += step
    if abs(best_angle) < step:
        return image, 0.0
    return image.rotate(best_angle, resample=Image.BICUBIC, expand=True, fillcolor="white"), best_angle


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", text.casefold()).replace("đ", "d")
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


# Bỏ dấu -> họ có dấu. Họ không dấu ("Nguyen") không phải dạng chuẩn; hai họ có
# dấu trùng nhau khi bỏ dấu thì không đoán được, bỏ qua (giá trị None).
_SURNAME_BY_FOLD: dict[str, str | None] = {}
for _name in SURNAMES.split("|"):
    _key = _fold(_name)
    if _key == _name.casefold():
        continue
    _SURNAME_BY_FOLD[_key] = None if _SURNAME_BY_FOLD.get(_key, _name) != _name else _name


def fix_ocr_surnames(words: list[Word]) -> int:
    """OCR hay đọc sai dấu của họ ("NGUYÊN" thay vì "NGUYỄN"), khiến detector
    không nhận ra đầu tên và chỉ che được "VĂN AN". Từ nào bỏ dấu trùng với một
    họ có dấu thì trả về đúng dấu của họ đó (giữ kiểu viết hoa, cùng độ dài)."""
    fixes = 0
    for word in words:
        canonical = _SURNAME_BY_FOLD.get(_fold(word.text))
        if not canonical or len(canonical) != len(word.text) or word.text.casefold() == canonical.casefold():
            continue
        if not word.text[0].isupper():
            continue
        word.text = canonical.upper() if word.text.isupper() else canonical
        fixes += 1
    return fixes


def fix_ocr_digits(text: str) -> tuple[str, int]:
    """Sửa nhầm chữ/số trong cụm "trông như số" (ví dụ 09O1 234 567 -> 0901 234 567).

    Chỉ sửa khi cụm có ít nhất 6 chữ số thật và chiếm đa số, để không biến chữ
    thường ("Sinh", "Bob") thành số. Độ dài giữ nguyên.
    """
    fixes = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal fixes
        chunk = match.group()
        digits = sum(ch.isdigit() for ch in chunk)
        letters = sum(ch.isalpha() or ch == "|" for ch in chunk)
        if digits < 6 or letters == 0 or letters * 3 > digits:
            return chunk
        fixed = chunk.translate(_OCR_DIGIT_FIX)
        fixes += sum(a != b for a, b in zip(chunk, fixed))
        return fixed

    return _DIGITISH.sub(repl, text), fixes


def _fold_chars(text: str) -> str:
    """Bỏ dấu từng ký tự, giữ nguyên độ dài để vị trí vẫn khớp với văn bản gốc."""
    out = []
    for ch in text:
        base = unicodedata.normalize("NFD", ch)[0]
        out.append({"đ": "d", "Đ": "D"}.get(ch, base))
    return "".join(out)


def detect_ocr_text(text: str) -> list[Detection]:
    """Nhận diện trên chữ OCR. OCR hay làm rơi dấu ("Địa chi", "Quan 10") khiến
    từ khoá có dấu không khớp; chạy thêm một lượt trên bản bỏ dấu để bổ sung.

    Lượt bỏ dấu không dùng cho tên người (bỏ dấu thì "CHỦ NGHĨA" thành họ "Chu"),
    và chỉ thay vùng cũ khi bao trọn vùng đó (địa chỉ chứa tên đường "Lý Thường Kiệt").
    Cuối cùng che mọi dãy số dài còn sót (_LONG_NUMBER).
    """
    found = detect(text)
    for item in detect(_fold_chars(text)):
        if item.kind == "PERSON":
            continue
        overlapping = [old for old in found if old.start < item.end and old.end > item.start]
        if all(item.start <= old.start and old.end <= item.end for old in overlapping):
            found = [old for old in found if old not in overlapping]
            found.append(Detection(item.kind, item.start, item.end, item.risk, item.preview))
    occupied = {i for item in found for i in range(item.start, item.end)}
    for match in _LONG_NUMBER.finditer(text):
        if occupied.isdisjoint(range(*match.span())):
            value = match.group()
            found.append(Detection("LONG_NUMBER", match.start(), match.end(), "high", f"{value[:2]}***{value[-2:]}"))
    return sorted(found, key=lambda item: item.start)


def build_text(words: list[Word]) -> tuple[str, list[tuple[int, int, int]]]:
    """Ghép từ thành văn bản theo dòng; trả về văn bản và (start, end, chỉ số từ)."""
    parts: list[str] = []
    spans: list[tuple[int, int, int]] = []
    pos = 0
    previous_line = None
    for index, word in enumerate(words):
        if previous_line is not None:
            sep = " " if word.line == previous_line else "\n"
            parts.append(sep)
            pos += 1
        parts.append(word.text)
        spans.append((pos, pos + len(word.text), index))
        pos += len(word.text)
        previous_line = word.line
    return "".join(parts), spans


def find_qr_codes(image: Image.Image) -> list[dict]:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []
    array = np.array(image.convert("L"))
    detector = cv2.QRCodeDetector()
    found = []
    try:
        ok, texts, points, _ = detector.detectAndDecodeMulti(array)
        if not ok or points is None:
            # Bộ dò nhiều mã đôi khi trượt ảnh chỉ có một mã; thử bộ dò đơn.
            text, single, _ = detector.detectAndDecode(array)
            ok, texts, points = single is not None, (text,), single
    except cv2.error:
        ok, texts, points = False, (), None
    if ok and points is not None:
        for text, quad in zip(texts, points):
            xs, ys = quad[:, 0], quad[:, 1]
            found.append({"box": (int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)), "data": text or ""})
    return found


def _qr_summary(text: str) -> dict:
    """QR trên CCCD gắn chip có dạng "số CCCD|số CMND|họ tên|ngày sinh|giới tính|địa chỉ|ngày cấp"."""
    kinds = sorted({d.kind for d in detect(normalize_text(text))}) if text else []
    looks_cccd = bool(re.match(r"^\d{12}\|", text or ""))
    if looks_cccd and "NATIONAL_ID" not in kinds:
        kinds.append("NATIONAL_ID")
    return {"decoded": bool(text), "pii_types": kinds, "cccd_format": looks_cccd}


def analyze_image(data: bytes) -> ImageReport:
    started = time.perf_counter()
    image, has_exif, has_gps = load_image(data)
    image, skew = deskew(image)
    t_load = time.perf_counter()
    words = run_ocr(image)
    t_ocr = time.perf_counter()
    name_fixes = fix_ocr_surnames(words)
    raw_text, spans = build_text(words)
    text, fixes = fix_ocr_digits(raw_text)
    fixes += name_fixes
    detections = detect_ocr_text(text)
    t_detect = time.perf_counter()

    boxes: list[dict] = []
    for item in detections:
        # Gộp các ô chữ nằm trên cùng một dòng thành một hình chữ nhật.
        per_line: dict[tuple, list[tuple[int, int, int, int]]] = {}
        for start, end, index in spans:
            if start < item.end and end > item.start:
                per_line.setdefault(words[index].line, []).append(words[index].box)
        for line_boxes in per_line.values():
            boxes.append({
                "kind": item.kind,
                "box": (min(b[0] for b in line_boxes), min(b[1] for b in line_boxes),
                        max(b[2] for b in line_boxes), max(b[3] for b in line_boxes)),
            })

    qr_codes = find_qr_codes(image)
    for qr in qr_codes:
        boxes.append({"kind": "QR_CODE", "box": qr["box"]})

    redacted = image.copy()
    draw = ImageDraw.Draw(redacted)
    for item in boxes:
        left, top, right, bottom = item["box"]
        draw.rectangle((max(0, left - _PAD), max(0, top - _PAD), right + _PAD, bottom + _PAD), fill="black")
    out = BytesIO()
    # Lưu từ dữ liệu điểm ảnh, không truyền exif/icc: metadata gốc không đi theo.
    redacted.save(out, format="PNG", optimize=True)
    t_end = time.perf_counter()

    return ImageReport(
        ocr_text=text,
        detections=detections,
        redacted_png=out.getvalue(),
        boxes=[{"kind": b["kind"], "box": list(b["box"])} for b in boxes],
        qr_codes=[{"box": list(q["box"]), **_qr_summary(q["data"])} for q in qr_codes],
        id_document=bool(_ID_DOCUMENT.search(text)),
        exif_removed=has_exif,
        gps_removed=has_gps,
        ocr_fixes=fixes,
        skew_degrees=skew,
        width=image.width,
        height=image.height,
        timings_ms={
            "load": round((t_load - started) * 1000), "ocr": round((t_ocr - t_load) * 1000),
            "detect": round((t_detect - t_ocr) * 1000), "redact": round((t_end - t_detect) * 1000),
            "total": round((t_end - started) * 1000),
        },
    )
