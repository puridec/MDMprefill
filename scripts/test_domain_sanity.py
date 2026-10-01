import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.domain_sanity import check_domain_sanity



# Each case: (label, record, what we expect to see in the flags - a
# substring is enough since exact wording isn't the point, just whether
# the right check fired)
cases = [
    (
        "clean record (row 6-shaped, nothing wrong)",
        {
            "extractable": True,
            "item_qty": 1, "item_unit": "PC",
            "item_weight_min": 0.17, "item_weight_max": 0.17,
            "item_weight_basis": "total_for_group",
            "item_per_inner_qty": 8,
            "inner_container_um": "BAG",
            "inner_weight_min": 1.33, "inner_weight_max": 1.33,
            "inner_per_master_qty": 1,
            "master_container_um": "CS",
            "master_weight_min": 1.33, "master_weight_max": 1.33,
        },
        None,  # expect NO flags at all
    ),
    (
        "negative count",
        {"extractable": True, "item_per_inner_qty": -1},
        "ERR_INVALID_COUNT:item_per_inner_qty=-1",
    ),
    (
        "non-integer count",
        {"extractable": True, "item_per_inner_qty": 2.5},
        "ERR_INVALID_COUNT:item_per_inner_qty=2.5",
    ),
    (
        "ungoverned UOM",
        {"extractable": True, "item_unit": "SACK"},
        "WARN_UNGOVERNED_VALUE:item_unit=SACK",
    ),
    (
        "min > max",
        {"extractable": True, "item_weight_min": 5, "item_weight_max": 3},
        "ERR_MIN_GT_MAX",
    ),
    (
        "min == max (should NOT flag - standard fixed-weight product)",
        {"extractable": True, "item_weight_min": 2, "item_weight_max": 2},
        None,
    ),
    (
        "hierarchy violation (item heavier than inner)",
        {"extractable": True, "item_weight_min": 10, "inner_weight_min": 2},
        "ERR_HIERARCHY_VIOLATION",
    ),
    (
        "abstained record with nonsense values - should be ignored entirely",
        {"extractable": False, "item_per_inner_qty": -99, "item_unit": "GARBAGE"},
        None,
    ),
]

all_passed = True
for label, record, expected_substring in cases:
    flags = check_domain_sanity(record)
    if expected_substring is None:
        ok = (flags == [])
    else:
        ok = any(expected_substring in f for f in flags)

    status = "PASS" if ok else "FAIL"
    if not ok:
        all_passed = False
    print(f"[{status}] {label}")
    print(f"       flags: {flags}")

print()
print("ALL PASSED" if all_passed else "SOME FAILED - see above")