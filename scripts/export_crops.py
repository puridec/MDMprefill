# scripts/export_crops.py
#
# Crops every eval doc to its assigned template's region - reads
# eval/eval_doc_templates.json directly (the explicit per-document
# tagging, not an inferred odd/even guess) to know which template each
# document belongs to. Re-run this any time template_regions.py or the
# tagging JSON changes, to visually confirm before spending API calls
# on a full eval run.

import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pymupdf
from config.template_regions import TEMPLATE_REGIONS

OUTPUT_DIR = Path("results/crop_previews")
DOC_TEMPLATES_PATH = Path("eval/eval_doc_templates.json")
EVAL_DOCS_DIR = Path("eval/test")  # match this to run_eval_vlm.py's EVAL_DOCS_DIR
NUM_DOCS = 40


def load_doc_templates() -> dict:
    with open(DOC_TEMPLATES_PATH, encoding="utf-8") as f:
        return json.load(f)


def crop_to_png(pdf_path: Path, template_id: str, dpi: int = 150) -> bytes:
    region = TEMPLATE_REGIONS[template_id]
    doc = pymupdf.open(str(pdf_path))
    page = doc[0]
    w, h = page.rect.width, page.rect.height
    clip = pymupdf.Rect(
        region["left"] * w, region["top"] * h,
        region["right"] * w, region["bottom"] * h,
    )
    pix = page.get_pixmap(dpi=dpi, clip=clip)
    return pix.tobytes("png")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    doc_templates = load_doc_templates()
    print(f"Loaded {len(doc_templates)} tagged documents from {DOC_TEMPLATES_PATH}\n")

    exported = 0
    skipped = []

    for eid in range(1, NUM_DOCS + 1):
        pdf_path = EVAL_DOCS_DIR / f"eval_doc_{eid:03d}.pdf"
        if not pdf_path.exists():
            print(f"{eid:03d}: SKIPPED (no PDF at {pdf_path})")
            skipped.append(eid)
            continue

        template_id = doc_templates.get(str(eid))
        if template_id is None:
            print(f"{eid:03d}: SKIPPED (not tagged in {DOC_TEMPLATES_PATH.name})")
            skipped.append(eid)
            continue
        if template_id not in TEMPLATE_REGIONS:
            print(f"{eid:03d}: SKIPPED (tagged '{template_id}', but that template has no coordinates in template_regions.py)")
            skipped.append(eid)
            continue

        png_bytes = crop_to_png(pdf_path, template_id)
        out_path = OUTPUT_DIR / f"eval_doc_{eid:03d}_{template_id}.png"
        out_path.write_bytes(png_bytes)
        print(f"{eid:03d} [{template_id}]: saved -> {out_path}")
        exported += 1

    print(f"\n{exported} crops exported to {OUTPUT_DIR}/")
    if skipped:
        print(f"{len(skipped)} skipped: {skipped}")


if __name__ == "__main__":
    main()