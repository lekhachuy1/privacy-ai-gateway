"""Theo dõi egress log và in gọn từng request gửi tới Gemini/Ollama.

Chạy từ thư mục project:  python scripts/watch_egress.py
Cần bật EGRESS_LOG_ENABLED=true trong .env. Nhấn Ctrl+C để dừng.

Tùy chọn --tim: dò các giá trị do người xem tự chọn trên toàn bộ body thô, không
dựa vào bộ nhận diện của hệ thống (tránh việc hệ thống tự kiểm tra chính mình):
    python scripts/watch_egress.py --tim "Nguyễn Văn An" 0901234567 an@example.com

Phép dò cố ý "nghi ngờ thì báo động": giá trị bị coi là lọt nếu xuất hiện nguyên
văn, hoặc chỉ khác hoa/thường, dấu tiếng Việt, khoảng trắng, hay cách viết số
("090 123 4567", "+84 90..."). Báo nhầm thì tốt hơn bỏ sót.
"""
from pathlib import Path
import json
import os
import re
import sys
import time
import unicodedata
import warnings

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

with warnings.catch_warnings():
    warnings.simplefilter("ignore")  # cảnh báo APP_SECRET không liên quan tới việc theo dõi
    from app.config import settings  # noqa: E402
from app.services.pii_detector import TOKEN_PATTERN, detect  # noqa: E402

LOG = Path(settings.egress_log_path)
YELLOW, GREEN, RED, DIM, BOLD, RESET = "\033[33m", "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def _normalize(text: str) -> str:
    """Cùng chuẩn NFKC như gateway, bỏ phân biệt hoa thường.

    Chữ "ễ" có thể là 1 ký tự dựng sẵn hoặc "e" + dấu tổ hợp tùy bộ gõ, chữ số có
    thể là full-width; không chuẩn hóa thì có thể báo không thấy dù có trong request.
    """
    return unicodedata.normalize("NFKC", text).casefold()


def _loose(text: str) -> str:
    """Bỏ dấu tiếng Việt và gộp khoảng trắng: "Nguyễn  Văn" → "nguyen van"."""
    decomposed = unicodedata.normalize("NFD", _normalize(text)).replace("đ", "d")
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(without_marks.split())


def _digit_pattern(value: str) -> re.Pattern[str] | None:
    """Dãy số của giá trị, cho phép dấu cách/chấm/gạch/ngoặc xen giữa các chữ số."""
    digits = re.sub(r"\D", "", _normalize(value))
    if len(digits) < 6:
        return None
    variants = [digits]
    if digits.startswith("0"):
        variants.append("84" + digits[1:])  # 0901… và +84 901… là một số
    elif digits.startswith("84"):
        variants.append("0" + digits[2:])
    sep = r"[\s.\-()+]*"
    return re.compile("|".join(rf"(?<!\d){sep.join(v)}(?!\d)" for v in variants))


def find_value(body: str, value: str) -> str | None:
    """Trả về cách giá trị xuất hiện trong body, hoặc None nếu không thấy."""
    # Có ranh giới từ để "an" không khớp với "an toàn", "0901234567" không khớp
    # với một dãy số dài hơn.
    def contains(haystack: str, needle: str) -> bool:
        return bool(needle) and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None

    if contains(_normalize(body), _normalize(value).strip()):
        return "nguyên văn"
    if contains(_loose(body), _loose(value)):
        return "khác dấu/hoa thường/khoảng trắng"
    pattern = _digit_pattern(value)
    if pattern and pattern.search(_normalize(body)):
        return "khác cách viết số"
    return None


def highlight(text: str) -> str:
    return TOKEN_PATTERN.sub(lambda m: f"{YELLOW}{BOLD}{m.group()}{RESET}", text)


def messages(provider: str, payload: dict) -> list[tuple[str, str]]:
    """Trích (vai, nội dung) từ body Gemini hoặc Ollama, bỏ qua chỉ dẫn hệ thống."""
    if provider == "gemini":
        return [(c["role"], " ".join(p.get("text", "") for p in c["parts"])) for c in payload.get("contents", [])]
    return [(m["role"], m["content"]) for m in payload.get("messages", []) if m["role"] != "system"]


def show(line: str, watched: list[str] | None = None) -> None:
    try:
        entry = json.loads(line)
        provider = entry["provider"]
        payload = entry["payload"]
        rows = messages(provider, payload)
    except (ValueError, KeyError, TypeError, AttributeError):
        print(f"\n{RED}{BOLD}Dòng log không đọc được (hỏng hoặc sai định dạng):{RESET} {line[:200]!r}")
        return
    where = "CLOUD" if provider == "gemini" else "LOCAL"
    print(f"\n{BOLD}── {str(entry.get('time', ''))[11:19]} · {provider.upper()} ({where}) ──{RESET}")
    print(f"{DIM}{entry.get('url', '')}{RESET}")
    found = []
    for role, text in rows:
        print(f"  {DIM}{role:>9}:{RESET} {highlight(text)}")
        found += [d.kind for d in detect(text)]
    if found:
        print(f"  {RED}{BOLD}CẢNH BÁO: phát hiện dữ liệu cá nhân trong request: {', '.join(sorted(set(found)))}{RESET}")
    else:
        print(f"  {GREEN}{BOLD}✓ Bộ nhận diện không thấy dữ liệu cá nhân trong request gửi đi{RESET}")
    if watched:
        # Dò trên toàn bộ body thô (kể cả chỉ dẫn hệ thống, lịch sử), không qua bộ nhận diện.
        body = json.dumps(payload, ensure_ascii=False)
        for value in watched:
            how = find_value(body, value)
            if how:
                print(f"  {RED}{BOLD}✗ THẤY \"{value}\" trong request ({how}){RESET}")
            else:
                print(f"  {GREEN}✓ Không thấy \"{value}\" trong request{RESET}")


def follow(path: Path):
    """Như `tail -f`: trả từng dòng hoàn chỉnh mới ghi; xử lý file bị xóa/ghi lại."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    file = path.open(encoding="utf-8")
    file.seek(0, os.SEEK_END)
    pending = ""
    try:
        while True:
            chunk = file.readline()
            if chunk:
                pending += chunk
                if pending.endswith("\n"):  # chưa có "\n" nghĩa là dòng đang ghi dở
                    yield pending
                    pending = ""
                continue
            try:
                truncated = path.stat().st_size < file.tell()
            except FileNotFoundError:
                truncated = True
            if truncated:  # log bị xóa hoặc làm trống: đọc lại từ đầu file mới
                file.close()
                path.touch(exist_ok=True)
                file = path.open(encoding="utf-8")
                pending = ""
            time.sleep(0.3)
    finally:
        file.close()


def main() -> None:
    os.system("")  # bật màu ANSI trên console Windows
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    watched = args[args.index("--tim") + 1:] if "--tim" in args else []
    if not settings.egress_log_enabled:
        print(f"{RED}{BOLD}Chú ý: EGRESS_LOG_ENABLED đang tắt trong .env — server sẽ không ghi log, "
              f"màn hình trống KHÔNG có nghĩa là không có request nào.{RESET}")
    if watched:
        print("Dò: " + ", ".join(f'"{v}"' for v in watched))
    print(f"Đang theo dõi {LOG} … (Ctrl+C để dừng)")
    for line in follow(LOG):
        if line.strip():
            show(line, watched)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
