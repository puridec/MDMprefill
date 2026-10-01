import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.llm_client import extract_packing_fields
from tools.enrich import compute_derived_weights
from tools.completeness import compute_completeness, needs_priority_review

# Row 1 from your eval set - known ground truth: 1 kgs/bag, 12/carton, net 12.0 KG
test_text = "1.33KGX8BAGSX1OUTERBAG/CASE"

print(f"INPUT: {test_text}\n")

raw = extract_packing_fields(test_text)
usage = raw.pop("_usage", None)  # separate cost info from the actual fields

print("=" * 50)
print("STAGE 3 - LLM extraction (raw, L1a)")
print("=" * 50)
for k, v in raw.items():
    print(f"  {k}: {v}")

if usage:
    tag = " (estimated)" if usage.get("cost_estimated") else ""
    print(f"\n  cost: ${usage['cost_usd']:.6f}{tag}  "
          f"({usage.get('tokens_in')} in / {usage.get('tokens_out')} out)")

print()
print("=" * 50)
print("STAGE 4 - Enrich (derived weights, L1b)")
print("=" * 50)
enriched = compute_derived_weights(raw)
derived_only = {k: v for k, v in enriched.items() if k not in raw}
if derived_only:
    for k, v in derived_only.items():
        print(f"  {k}: {v}")
else:
    print("  (nothing derived - check item_per_inner_qty / inner_per_master_qty are present)")

print()
print("=" * 50)
print("Completeness")
print("=" * 50)
score = compute_completeness(enriched)
print(f"  score: {score:.2f}")
print(f"  needs_priority_review: {needs_priority_review(enriched)}")

print()
print("=" * 50)
print("FULL enriched record (what L1 would actually check)")
print("=" * 50)
for k, v in enriched.items():
    print(f"  {k}: {v}")