import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.llm_client import extract_packing_fields_from_pdf
from tools.enrich import compute_derived_weights
pdf_path = input("Enter path to a test PDF (e.g. eval/test/doc_row1.pdf): ").strip()
template_id = input("Template ID (e.g. GEN, or None for whole-page): ").strip()
if template_id.lower() in ("none", ""):
    template_id = None

print(f"\nPDF: {pdf_path}  TEMPLATE: {template_id}\n")
raw = extract_packing_fields_from_pdf(pdf_path, template_id=template_id)
usage = raw.pop("_usage", None)

print("=== VLM extraction (raw) ===")
print(json.dumps(raw, indent=2))

if usage:
    tag = " (estimated)" if usage.get("cost_estimated") else ""
    print(f"\ncost: ${usage['cost_usd']:.6f}{tag}  "
          f"({usage.get('tokens_in')} in / {usage.get('tokens_out')} out)  "
          f"attempts: {usage.get('attempts')}")

print()
print("=== Enrich (derived weights) ===")
enriched = compute_derived_weights(raw)
derived_only = {k: v for k, v in enriched.items() if k not in raw}
print(json.dumps(derived_only, indent=2))