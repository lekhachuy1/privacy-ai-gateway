"""Đo Image Guard trên bộ ảnh giả có đáp án (sinh bởi make_sample_images.py).

So sánh hai cấu hình:
  baseline : một lượt OCR ảnh xám + PII Detector của luồng văn bản (cách làm "ngây thơ")
  full     : OCR hai lượt (chuẩn hoá màu nền) + sửa lỗi OCR (số, dấu của họ)
             + nhận diện thêm trên bản bỏ dấu + che mã QR

Chỉ số cho mỗi giá trị PII đã chèn vào ảnh:
  detected : giá trị nằm trong một vùng bị nhận diện (nên sẽ bị che)
  residual : sau khi che, OCR lại ảnh vẫn đọc ra giá trị đó (lọt)
Kèm thời gian xử lý trung bình trên CPU.

Chạy:  python scripts/bench_image_guard.py [--out data/samples/bench.json]
"""
from io import BytesIO
from pathlib import Path
import argparse
import json
import random
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from PIL import Image, ImageDraw, ImageOps  # noqa: E402

import make_sample_images as samples  # noqa: E402
from app.services import image_guard as g  # noqa: E402
from app.services.pii_detector import detect  # noqa: E402

VARIANTS = ["clean", "blur", "rotate", "noise", "small", "jpeg"]


def squash(text: str) -> str:
    return "".join(ch for ch in g._fold_chars(text).casefold() if ch.isalnum())


def baseline(image: Image.Image):
    scale = max(1.0, g._MIN_OCR_WIDTH / image.width)
    work = image if scale == 1.0 else image.resize((round(image.width * scale), round(image.height * scale)))
    words = g._tesseract_words(g.tesseract_cmd(), work.convert("L"), scale, "vie+eng", 0)
    text, spans = g.build_text(words)
    detections = detect(text)
    redacted = image.copy()
    draw = ImageDraw.Draw(redacted)
    for item in detections:
        for start, end, index in spans:
            if start < item.end and end > item.start:
                left, top, right, bottom = words[index].box
                draw.rectangle((left - g._PAD, top - g._PAD, right + g._PAD, bottom + g._PAD), fill="black")
    return text, detections, redacted


def full(image: Image.Image):
    out = BytesIO()
    image.save(out, format="PNG")
    report = g.analyze_image(out.getvalue())
    return report.ocr_text, report.detections, Image.open(BytesIO(report.redacted_png)).convert("RGB")


def score(values: dict, text: str, detections, redacted: Image.Image) -> dict:
    detected_text = " ".join(text[d.start:d.end] for d in detections)
    leftover = squash(g.build_text(g.run_ocr(redacted))[0])
    result = {}
    for key, value in values.items():
        target = squash(value)
        result[key] = {"detected": target in squash(detected_text), "residual": target in leftover}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "data" / "samples" / "bench.json"))
    args = parser.parse_args()
    if not g.ocr_available():
        print("Chưa cài Tesseract OCR")
        return 1
    rng = random.Random(447)
    rows = []
    for person_no, person in enumerate(samples.PEOPLE, 1):
        for doc, build in samples.BUILDERS.items():
            base = build(person)
            for variant in VARIANTS:
                image = samples.degrade(base, variant, rng)
                if variant == "jpeg":
                    buf = BytesIO()
                    image.save(buf, format="JPEG", quality=45)
                    image = Image.open(BytesIO(buf.getvalue())).convert("RGB")
                values = {key: person[key] for key in samples.EXPECTED[doc]}
                for config, run in (("baseline", baseline), ("full", full)):
                    started = time.perf_counter()
                    text, detections, redacted = run(image)
                    elapsed = (time.perf_counter() - started) * 1000
                    rows.append({"person": person_no, "doc": doc, "variant": variant, "config": config,
                                 "ms": round(elapsed), "values": score(values, text, detections, redacted)})
                    print(f"{doc:8} {variant:7} {config:8} {elapsed:6.0f} ms "
                          + " ".join(f"{k}:{'D' if v['detected'] else '-'}{'L' if v['residual'] else ''}"
                                     for k, v in rows[-1]["values"].items()), flush=True)

    summary = {}
    for config in ("baseline", "full"):
        for group in ["all", *VARIANTS]:
            chosen = [r for r in rows if r["config"] == config and group in ("all", r["variant"])]
            cells = [v for r in chosen for v in r["values"].values()]
            summary.setdefault(config, {})[group] = {
                "values": len(cells),
                "detected_pct": round(100 * sum(c["detected"] for c in cells) / len(cells), 1),
                "residual_pct": round(100 * sum(c["residual"] for c in cells) / len(cells), 1),
                "median_ms": round(statistics.median(r["ms"] for r in chosen)),
            }
    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nCấu hình  Nhóm     Số giá trị  Nhận diện  Còn đọc được  Trung vị ms")
    for config, groups in summary.items():
        for group, s in groups.items():
            print(f"{config:9} {group:8} {s['values']:10} {s['detected_pct']:9}% {s['residual_pct']:12}% {s['median_ms']:11}")
    print(f"\nĐã ghi {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
