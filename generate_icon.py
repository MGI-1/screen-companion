"""Generate the Document Wizard app icon programmatically."""

import os
from PIL import Image, ImageDraw, ImageFont

SIZE = 512
OUT_DIR = os.path.join(os.path.dirname(__file__), "assets")


def generate_icon():
    os.makedirs(OUT_DIR, exist_ok=True)

    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background circle — deep navy
    pad = 20
    draw.ellipse(
        [pad, pad, SIZE - pad, SIZE - pad],
        fill="#142039",
        outline="#1e2d4d",
        width=4,
    )

    # Inner glow ring — orange
    ring_pad = 40
    draw.ellipse(
        [ring_pad, ring_pad, SIZE - ring_pad, SIZE - ring_pad],
        outline="#ff7e00",
        width=6,
    )

    # Document shape (white rectangle with folded corner)
    doc_left = 160
    doc_top = 120
    doc_right = 352
    doc_bottom = 400
    fold = 50

    # Document body
    doc_points = [
        (doc_left, doc_top),
        (doc_right - fold, doc_top),
        (doc_right, doc_top + fold),
        (doc_right, doc_bottom),
        (doc_left, doc_bottom),
    ]
    draw.polygon(doc_points, fill="#e2e8f0", outline="#94a3b8", width=2)

    # Folded corner
    fold_points = [
        (doc_right - fold, doc_top),
        (doc_right, doc_top + fold),
        (doc_right - fold, doc_top + fold),
    ]
    draw.polygon(fold_points, fill="#94a3b8")

    # Text lines on document
    line_y = doc_top + 70
    for i in range(5):
        line_width = 140 if i < 3 else 100 if i == 3 else 60
        draw.rounded_rectangle(
            [doc_left + 25, line_y, doc_left + 25 + line_width, line_y + 8],
            radius=4,
            fill="#ff7e00" if i == 0 else "#94a3b8",
        )
        line_y += 24

    # "W" letter at center-bottom (wizard mark)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 72)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 72)
        except (OSError, IOError):
            font = ImageFont.load_default()

    draw.text(
        (SIZE // 2, doc_bottom + 30),
        "W",
        fill="#ff7e00",
        font=font,
        anchor="mt",
    )

    # Save PNG
    png_path = os.path.join(OUT_DIR, "icon.png")
    img.save(png_path, "PNG")
    print(f"Saved: {png_path}")

    # Generate .icns for macOS
    try:
        _generate_icns(img)
    except Exception as e:
        print(f"Could not generate .icns: {e}")

    return png_path


def _generate_icns(img):
    """Generate macOS .icns file from a PIL Image."""
    import subprocess
    import tempfile

    icns_path = os.path.join(OUT_DIR, "icon.icns")

    # Create iconset directory with required sizes
    with tempfile.TemporaryDirectory() as tmpdir:
        iconset = os.path.join(tmpdir, "icon.iconset")
        os.makedirs(iconset)

        sizes = [16, 32, 64, 128, 256, 512]
        for size in sizes:
            resized = img.resize((size, size), Image.LANCZOS)
            resized.save(os.path.join(iconset, f"icon_{size}x{size}.png"))
            # @2x versions
            if size <= 256:
                resized2x = img.resize((size * 2, size * 2), Image.LANCZOS)
                resized2x.save(
                    os.path.join(iconset, f"icon_{size}x{size}@2x.png")
                )

        # Use iconutil to create .icns
        subprocess.run(
            ["iconutil", "-c", "icns", iconset, "-o", icns_path],
            check=True,
        )
        print(f"Saved: {icns_path}")


if __name__ == "__main__":
    generate_icon()
