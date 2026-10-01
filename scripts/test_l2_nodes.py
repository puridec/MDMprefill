import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.nodes import l2_node

cases = [
    (
        "no overrides - reviewer just approves as-is",
        {
            "enriched_fields": {"item_unit": "PC", "master_weight_min": 1.33},
            "manual_overrides": {},
            "reviewer_id": "puri",
            "l2_approved": True,
        },
    ),
    (
        "one field corrected",
        {
            "enriched_fields": {"item_unit": "SACK", "master_weight_min": 1.33},
            "manual_overrides": {"item_unit": "SAC"},
            "reviewer_id": "puri",
            "l2_approved": True,
        },
    ),
    (
        "override matches existing value - should NOT appear in delta",
        {
            "enriched_fields": {"item_unit": "PC"},
            "manual_overrides": {"item_unit": "PC"},
            "reviewer_id": "puri",
            "l2_approved": True,
        },
    ),
    (
        "rejected record",
        {
            "enriched_fields": {"item_unit": "PC"},
            "manual_overrides": {},
            "reviewer_id": "puri",
            "l2_approved": False,
        },
    ),
]

for label, state in cases:
    result = l2_node(state)
    print(f"=== {label} ===")
    print(f"  final_fields: {result['final_fields']}")
    print(f"  audit_trail:  {result['audit_trail']}")
    print()