#!/usr/bin/env python3
"""Create deterministic 1000x750 portfolio images from verified workbook renders."""

from __future__ import annotations

import hashlib
import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "artifacts" / "verification"
OUTPUT_ROOT = ROOT / "artifacts" / "portfolio"
FRAME_ROOT = ROOT / "artifacts" / "video-frames"

WIDTH = 1000
HEIGHT = 750
NAVY = "#16324F"
TEAL = "#0F766E"
INK = "#182433"
MUTED = "#5F6B76"
BACKGROUND = "#F4F7FA"
PALE_BLUE = "#EAF1F8"
PALE_AMBER = "#FFF4D6"
WHITE = "#FFFFFF"

FONT_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canvas() -> Image.Image:
    return Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)


def rounded_card(base: Image.Image, box: tuple[int, int, int, int], radius: int = 22) -> None:
    x1, y1, x2, y2 = box
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((x1 + 8, y1 + 12, x2 + 8, y2 + 12), radius, fill=(17, 33, 51, 45))
    shadow = shadow.filter(ImageFilter.GaussianBlur(12))
    base.paste(shadow, (0, 0), shadow)
    ImageDraw.Draw(base).rounded_rectangle(box, radius, fill=WHITE)


def paste_contain(base: Image.Image, source_path: Path, box: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    source = Image.open(source_path).convert("RGB")
    source.thumbnail((x2 - x1, y2 - y1), Image.Resampling.LANCZOS)
    x = x1 + (x2 - x1 - source.width) // 2
    y = y1 + (y2 - y1 - source.height) // 2
    base.paste(source, (x, y))


def draw_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    width: int,
    selected_font: ImageFont.FreeTypeFont,
    fill: str,
    spacing: int = 8,
) -> int:
    average_char = max(8, selected_font.size * 0.55)
    lines = textwrap.wrap(text, width=max(8, int(width / average_char)))
    y = xy[1]
    for line in lines:
        draw.text((xy[0], y), line, font=selected_font, fill=fill)
        y += selected_font.size + spacing
    return y


def pill(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, fill: str) -> None:
    draw.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, fill=fill)
    label_font = font(18, bold=True)
    bounds = draw.textbbox((0, 0), text, font=label_font)
    text_width = bounds[2] - bounds[0]
    text_height = bounds[3] - bounds[1]
    draw.text(
        (box[0] + (box[2] - box[0] - text_width) / 2, box[1] + (box[3] - box[1] - text_height) / 2 - 2),
        text,
        font=label_font,
        fill=WHITE,
    )


def make_cover(
    output: Path,
    title: str,
    subtitle: str,
    metric: str,
    summary_image: Path,
) -> None:
    image = canvas()
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 18), fill=TEAL)
    draw_lines(draw, title, (58, 95), 330, font(48, bold=True), NAVY, spacing=10)
    draw_lines(draw, subtitle, (58, 285), 330, font(23), MUTED, spacing=7)
    pill(draw, (58, 520, 352, 570), metric, TEAL)
    draw.text((58, 606), "Offline by default • Human review required", font=font(18, bold=True), fill=INK)
    rounded_card(image, (420, 72, 958, 665))
    paste_contain(image, summary_image, (448, 98, 930, 638))
    image.save(output, format="PNG", optimize=True)


def make_detail(output: Path, title: str, caption: str, source_image: Path) -> None:
    image = canvas()
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 96), fill=NAVY)
    draw.text((46, 26), title, font=font(34, bold=True), fill=WHITE)
    draw.text((48, 112), caption, font=font(20), fill=MUTED)
    rounded_card(image, (36, 154, 964, 712), radius=18)
    paste_contain(image, source_image, (54, 172, 946, 694))
    image.save(output, format="PNG", optimize=True)


def make_text_slide(output: Path, eyebrow: str, title: str, bullets: list[str], footer: str) -> None:
    image = canvas()
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 24, HEIGHT), fill=TEAL)
    draw.text((70, 72), eyebrow.upper(), font=font(17, bold=True), fill=TEAL)
    draw_lines(draw, title, (70, 112), 800, font(46, bold=True), NAVY, spacing=8)
    y = 275
    for bullet in bullets:
        draw.ellipse((75, y + 8, 91, y + 24), fill=TEAL)
        y = draw_lines(draw, bullet, (112, y), 780, font(25), INK, spacing=7) + 18
    draw.rounded_rectangle((70, 650, 930, 705), radius=16, fill=PALE_AMBER)
    draw.text((92, 665), footer, font=font(20, bold=True), fill="#6B4F00")
    image.save(output, format="PNG", optimize=True)


def copy_for_frame(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image.convert("RGB").save(destination, format="PNG", optimize=True)


def build_workflow_assets(kind: str, config: dict[str, object]) -> list[Path]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    frames = FRAME_ROOT / kind
    frames.mkdir(parents=True, exist_ok=True)

    cover = OUTPUT_ROOT / f"{kind}-cover.png"
    register = OUTPUT_ROOT / f"{kind}-register.png"
    review = OUTPUT_ROOT / f"{kind}-review.png"
    audit = OUTPUT_ROOT / f"{kind}-audit.png"
    boundary = OUTPUT_ROOT / f"{kind}-boundary.png"
    closing = OUTPUT_ROOT / f"{kind}-closing.png"

    make_cover(
        cover,
        str(config["title"]),
        str(config["subtitle"]),
        str(config["metric"]),
        Path(config["summary"]),
    )
    make_detail(register, str(config["register_title"]), str(config["register_caption"]), Path(config["register"]))
    make_detail(review, "Human Review Queue", "Every item begins pending; approval is explicit and editable.", Path(config["review"]))
    make_detail(audit, "Local Audit Trail", "Hashes, formats, counts, and offline mode — no credentials or full environment values.", Path(config["audit"]))
    make_text_slide(
        boundary,
        "Safety boundary",
        "Automation prepares evidence. A human keeps the decision.",
        list(config["boundary_bullets"]),
        "No automatic sending • No compliance conclusion • No hidden approval",
    )
    make_text_slide(
        closing,
        "7-day pilot",
        "One input. One workflow. One review gate.",
        [
            "Public, redacted, or synthetic sample data",
            "Client-owned code, tests, runbook, and reviewer guide",
            "Fixed acceptance cases and visible exclusions",
        ],
        "Launch pilot: $149 for the first two verified case studies",
    )

    sources = [cover, register, review, audit, boundary, closing]
    for index, source in enumerate(sources, start=1):
        copy_for_frame(source, frames / f"{index:02d}.png")
    return sources


def main() -> int:
    configs = {
        "evidence": {
            "title": "Auditable Evidence Register",
            "subtitle": "Local documents → source-linked evidence → human review",
            "metric": "26 evidence items",
            "summary": SOURCE_ROOT / "evidence" / "evidence-summary.png",
            "register": SOURCE_ROOT / "evidence" / "evidence-evidence.png",
            "review": SOURCE_ROOT / "evidence" / "evidence-review-queue.png",
            "audit": SOURCE_ROOT / "evidence" / "evidence-audit.png",
            "register_title": "Source-Linked Evidence",
            "register_caption": "Four synthetic formats normalized into one reviewable register.",
            "boundary_bullets": [
                "Canonical JSON preserves source, quote, field, value, and confidence",
                "Spreadsheet cells are protected from formula injection",
                "Default execution is offline and requires no API key",
            ],
        },
        "changes": {
            "title": "Controlled Change Review",
            "subtitle": "Before/after documents → explainable differences → human approval",
            "metric": "13 detected changes",
            "summary": SOURCE_ROOT / "changes" / "changes-summary.png",
            "register": SOURCE_ROOT / "changes" / "changes-changes.png",
            "review": SOURCE_ROOT / "changes" / "changes-review-queue.png",
            "audit": SOURCE_ROOT / "changes" / "changes-audit.png",
            "register_title": "Explainable Old / New Values",
            "register_caption": "8 high-priority and 5 medium-priority review hints from visible rules.",
            "boundary_bullets": [
                "Risk levels prioritize review; they are not regulatory judgments",
                "Source-qualified fields keep every change traceable",
                "No model is required to detect or classify the included changes",
            ],
        },
    }

    generated: list[Path] = []
    source_files: set[Path] = set()
    for kind, config in configs.items():
        generated.extend(build_workflow_assets(kind, config))
        for key in ("summary", "register", "review", "audit"):
            source_files.add(Path(config[key]))

    manifest = {
        "format": "1000x750 PNG, 4:3",
        "content": "Deterministic compositions of verified workbook renders and exact demonstrated counts.",
        "sources": [{"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in sorted(source_files)],
        "outputs": [{"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in sorted(generated)],
        "video_frames": {
            kind: [str(path.relative_to(ROOT)) for path in sorted((FRAME_ROOT / kind).glob("*.png"))]
            for kind in configs
        },
        "videos": [
            {
                "path": str(path.relative_to(ROOT)),
                "sha256": sha256(path),
                "format": "H.264 MP4, 1000x750, 30 seconds",
            }
            for path in sorted(OUTPUT_ROOT.glob("*-demo.mp4"))
        ],
    }
    (OUTPUT_ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "generated_images": len(generated)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
