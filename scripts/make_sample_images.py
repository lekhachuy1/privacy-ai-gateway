"""Sinh ảnh mẫu GIẢ để demo và đo Image Guard: CCCD giả, hoá đơn giả, ảnh chụp
màn hình chat giả. Mọi số liệu đều bịa, không phải dữ liệu của người thật.

Mỗi ảnh có đáp án (giá trị PII đã chèn) trong samples.json để chấm tự động.
Có thêm các biến thể khó (mờ, nghiêng, nhiễu, JPEG nén mạnh) cho phần đánh giá.

Chạy:  python scripts/make_sample_images.py [--variants]
"""
from pathlib import Path
import argparse
import json
import random
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "samples"
FONT_DIR = Path("C:/Windows/Fonts")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for name in (("arialbd.ttf", "DejaVuSans-Bold.ttf") if bold else ("arial.ttf", "DejaVuSans.ttf")):
        for folder in (FONT_DIR, Path("/usr/share/fonts/truetype/dejavu")):
            if (folder / name).exists():
                return ImageFont.truetype(str(folder / name), size)
    return ImageFont.load_default(size)


def qr_image(data: str, size: int) -> Image.Image:
    import qrcode
    qr = qrcode.QRCode(border=1, box_size=4)
    qr.add_data(data)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB").resize((size, size), Image.NEAREST)


def fake_cccd(person: dict) -> Image.Image:
    img = Image.new("RGB", (1000, 630), (226, 238, 230))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 999, 110), fill=(196, 222, 205))
    d.text((300, 18), "CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM", font=font(26, True), fill="black")
    d.text((380, 58), "Độc lập - Tự do - Hạnh phúc", font=font(22), fill="black")
    d.text((290, 130), "CĂN CƯỚC CÔNG DÂN (MẪU GIẢ)", font=font(32, True), fill=(170, 20, 20))
    d.rectangle((40, 150, 250, 420), fill=(180, 190, 200), outline="black")
    d.text((95, 270), "ẢNH", font=font(30, True), fill=(90, 90, 90))
    img.paste(qr_image("|".join([person["cccd"], "", person["name"], person["dob"].replace("/", ""),
                                 "Nam", person["address"], "01012021"]), 170), (60, 440))
    lines = [
        ("Số / No.:", person["cccd"]),
        ("Họ và tên / Full name:", person["name"]),
        ("Ngày sinh / Date of birth:", person["dob"]),
        ("Giới tính / Sex: Nam", ""),
        ("Quốc tịch / Nationality: Việt Nam", ""),
        ("Nơi thường trú:", person["address"]),
    ]
    y = 200
    for label, value in lines:
        d.text((290, y), label, font=font(24), fill="black")
        if value:
            d.text((290 + d.textlength(label, font=font(24)) + 12, y - 2), value, font=font(28, True), fill="black")
        y += 62
    return img


def fake_invoice(person: dict) -> Image.Image:
    img = Image.new("RGB", (900, 1100), "white")
    d = ImageDraw.Draw(img)
    d.text((250, 40), "HOÁ ĐƠN BÁN HÀNG (MẪU GIẢ)", font=font(34, True), fill="black")
    rows = [
        f"Khách hàng: {person['name']}",
        f"Số điện thoại: {person['phone']}",
        f"Email: {person['email']}",
        f"Địa chỉ: {person['address']}",
        f"Mã số thuế: {person['tax']}",
        f"Số tài khoản: {person['bank']}",
        "",
        "Sản phẩm             SL      Đơn giá",
        "Bàn phím cơ          1       850.000 đ",
        "Chuột không dây      2       320.000 đ",
        "Tổng cộng:                   1.490.000 đ",
    ]
    y = 140
    for row in rows:
        d.text((70, y), row, font=font(28), fill="black")
        y += 70
    return img


def fake_chat(person: dict) -> Image.Image:
    img = Image.new("RGB", (720, 1000), (240, 242, 245))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 719, 80), fill=(0, 104, 255))
    d.text((30, 22), "Chăm sóc khách hàng", font=font(28, True), fill="white")
    bubbles = [
        (False, "Chào anh, anh cho em xin thông tin xác minh ạ"),
        (True, f"Anh là {person['name']}"),
        (True, f"SĐT của anh: {person['phone']}"),
        (True, f"CCCD: {person['cccd']}"),
        (False, "Dạ em cảm ơn, anh cần hỗ trợ gì ạ?"),
        (True, f"Thẻ của anh số {person['card']} bị trừ tiền 2 lần"),
    ]
    y = 110
    for mine, text in bubbles:
        f = font(24)
        width = min(640, int(d.textlength(text, font=f)) + 40)
        x = 700 - width if mine else 20
        d.rounded_rectangle((x, y, x + width, y + 60), radius=18, fill=(0, 132, 255) if mine else "white")
        d.text((x + 20, y + 16), text, font=f, fill="white" if mine else "black")
        y += 90
    return img


PEOPLE = [
    {"name": "NGUYỄN VĂN AN", "cccd": "079090001234", "dob": "15/08/1990", "phone": "0901 234 567",
     "email": "an.nguyen@example.com", "address": "12 Lý Thường Kiệt, Quận 10, TP. Hồ Chí Minh",
     "tax": "0312345678", "bank": "1903 4567 8901 23", "card": "4111 1111 1111 1111"},
    {"name": "TRẦN THỊ BÌNH", "cccd": "001185004321", "dob": "02/11/1985", "phone": "0987 654 321",
     "email": "binh.tran@example.com", "address": "45 Nguyễn Văn Linh, Hải Châu, Đà Nẵng",
     "tax": "0109876543", "bank": "0071 0000 12345", "card": "5555 5555 5555 4444"},
]

# Giá trị cần che theo từng loại ảnh (để chấm: còn đọc được trên ảnh đã che là lọt).
EXPECTED = {
    "cccd": ("cccd", "name", "dob"),
    "invoice": ("name", "phone", "email", "tax", "bank"),
    "chat": ("name", "phone", "cccd", "card"),
}
BUILDERS = {"cccd": fake_cccd, "invoice": fake_invoice, "chat": fake_chat}


def gps_exif() -> Image.Exif:
    exif = Image.Exif()
    exif[0x010F] = "DemoPhone"  # Make
    exif[0x8825] = {1: "N", 2: (10.0, 46.0, 30.0), 3: "E", 4: (106.0, 41.0, 20.0)}
    return exif


def degrade(img: Image.Image, kind: str, rng: random.Random) -> Image.Image:
    if kind == "blur":
        return img.filter(ImageFilter.GaussianBlur(1.6))
    if kind == "rotate":
        return img.rotate(rng.choice([-4, -3, 3, 4]), expand=True, fillcolor="white")
    if kind == "noise":
        noisy = img.copy()
        pixels = noisy.load()
        for _ in range(img.width * img.height // 25):
            x, y = rng.randrange(img.width), rng.randrange(img.height)
            pixels[x, y] = (rng.randrange(256),) * 3
        return noisy
    if kind == "small":
        return img.resize((img.width // 2, img.height // 2), Image.BILINEAR)
    return img


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variants", action="store_true", help="sinh thêm biến thể mờ/nghiêng/nhiễu/nhỏ/jpeg")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(447)
    manifest = []
    variants = ["clean", "blur", "rotate", "noise", "small", "jpeg"] if args.variants else ["clean"]
    for index, person in enumerate(PEOPLE, 1):
        for doc, build in BUILDERS.items():
            base = build(person)
            for variant in variants:
                img = degrade(base, variant, rng)
                jpeg = variant == "jpeg" or doc == "invoice"
                name = f"{doc}_{index}_{variant}.{'jpg' if jpeg else 'png'}"
                if jpeg:
                    # Hoá đơn mô phỏng ảnh chụp điện thoại: có EXIF kèm toạ độ GPS.
                    img.save(OUT / name, quality=45 if variant == "jpeg" else 90, exif=gps_exif())
                else:
                    img.save(OUT / name)
                manifest.append({"file": name, "doc": doc, "variant": variant,
                                 "values": {key: person[key] for key in EXPECTED[doc]},
                                 "has_qr": doc == "cccd", "has_gps": jpeg})
    (OUT / "samples.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Đã sinh {len(manifest)} ảnh giả vào {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
