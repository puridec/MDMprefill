# scripts/pick_region.py
#
# Interactive tool: opens a rendered PDF page, click the top-left corner
# then the bottom-right corner of the region you want (e.g. the Packing
# Detail row), and this prints the fraction coordinates ready to paste
# into config/template_regions.py.
#
# Edit PDF_PATH below, then just run: python scripts/pick_region.py

import io
from pathlib import Path

import matplotlib.pyplot as plt
import pymupdf
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Edit this before running ---
PDF_PATH = "eval/test/eval_doc_001.pdf"
DPI = 300


def load_image(path: Path, dpi: int) -> Image.Image:
    if path.suffix.lower() == ".pdf":
        doc = pymupdf.open(str(path))
        pix = doc[0].get_pixmap(dpi=dpi)
        return Image.open(io.BytesIO(pix.tobytes("png")))
    return Image.open(path)


def main():
    path = PROJECT_ROOT / PDF_PATH

    image = load_image(path, DPI)
    w, h = image.size

    print(f"Image size: {w} x {h} pixels (rendered at {DPI} DPI)")
    print("A window will open. Click the TOP-LEFT corner of your region,")
    print("then the BOTTOM-RIGHT corner. Close the window when done.\n")

    fig, ax = plt.subplots(figsize=(12, 15))
    ax.imshow(image)
    ax.set_title("Click top-left, then bottom-right of the target region")

    points = plt.ginput(2, timeout=0)  # waits indefinitely for 2 clicks
    plt.close(fig)

    if len(points) != 2:
        print("Didn't get 2 clicks - try again.")
        return

    (x1, y1), (x2, y2) = points
    left, right = sorted([x1, x2])
    top, bottom = sorted([y1, y2])

    print("\n--- Pixel coordinates ---")
    print(f"left={int(left)}, top={int(top)}, right={int(right)}, bottom={int(bottom)}")

    print("\n--- Fraction coordinates (paste into template_regions.py) ---")
    print(f'"left": {left/w:.4f},')
    print(f'"top": {top/h:.4f},')
    print(f'"right": {right/w:.4f},')
    print(f'"bottom": {bottom/h:.4f},')


if __name__ == "__main__":
    main()