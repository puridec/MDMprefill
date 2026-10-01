"""
eval_handwritten_subset.py

Reports L1a and L1b accuracy for rows 1-19 (hand-written subset)
from an existing eval_results_vlm.json file.
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

HANDWRITTEN_IDS = set(range(1, 20))  # rows 1-19 inclusive
RESULTS_FILE = Path("eval/eval_results_vlm_1-10-2026.json")


def main():
    if not RESULTS_FILE.exists():
        print(f"ERROR: {RESULTS_FILE} not found. Run run_eval_vlm.py first.")
        sys.exit(1)

    with open(RESULTS_FILE, encoding="utf-8") as f:
        data = json.load(f)

    subset = [r for r in data["results"] if r["id"] in HANDWRITTEN_IDS]

    if not subset:
        print("No rows found for IDs 1-19.")
        sys.exit(1)

    # --- Per-field L1a breakdown ---
    field_l1a = defaultdict(lambda: {"pass": 0, "fail": 0})
    for r in subset:
        for field, result in r.get("l1a_fields", {}).items():
            if result["match"]:
                field_l1a[field]["pass"] += 1
            else:
                field_l1a[field]["fail"] += 1

    print("\n  L1a per-field breakdown:")
    print(f"  {'Field':<30} {'Pass':>6} {'Fail':>6} {'Rate':>8}")
    print(f"  {'-'*54}")
    for field, counts in sorted(field_l1a.items()):
        total = counts["pass"] + counts["fail"]
        rate = counts["pass"] / total if total else 0
        print(f"  {field:<30} {counts['pass']:>6} {counts['fail']:>6} {rate:>8.1%}")

    # --- Per-field L1b breakdown ---
    field_l1b = defaultdict(lambda: {"pass": 0, "fail": 0})
    for r in subset:
        for field, result in r.get("l1b_fields", {}).items():
            if result["match"]:
                field_l1b[field]["pass"] += 1
            else:
                field_l1b[field]["fail"] += 1

    print("\n  L1b per-field breakdown:")
    print(f"  {'Field':<30} {'Pass':>6} {'Fail':>6} {'Rate':>8}")
    print(f"  {'-'*54}")
    for field, counts in sorted(field_l1b.items()):
        total = counts["pass"] + counts["fail"]
        rate = counts["pass"] / total if total else 0
        print(f"  {field:<30} {counts['pass']:>6} {counts['fail']:>6} {rate:>8.1%}")

        # --- Per-row detail for hand-written subset ---
    print("\n  Per-row detail:")
    print(f"  {'-'*80}")
    for r in sorted(subset, key=lambda x: x["id"]):
        print(f"\n  Row {r['id']} | status={r['status']} | l1a={'PASS' if r.get('l1a_pass') else 'FAIL'} | l1b={'PASS' if r.get('l1b_pass') else 'FAIL'}")
        print(f"  raw_text_seen: {r.get('raw_text_seen', 'N/A')}")

        l1a_fields = r.get("l1a_fields", {})
        if l1a_fields:
            print(f"  L1a fields:")
            for field, vals in l1a_fields.items():
                match_str = "✓" if vals["match"] else "✗"
                print(f"    {match_str} {field:<30} expected={str(vals['expected']):<15} actual={vals['actual']}")

        l1b_fields = r.get("l1b_fields", {})
        if l1b_fields:
            print(f"  L1b fields:")
            for field, vals in l1b_fields.items():
                match_str = "✓" if vals["match"] else "✗"
                print(f"    {match_str} {field:<30} expected={str(vals['expected']):<15} actual={vals['actual']}")

    # --- Completeness and sanity for hand-written subset ---
    print("\n  Completeness & sanity (rows 1-19):")
    print(f"  {'Row':<6} {'Completeness':>14} {'Priority Flag':>14} {'Sanity Flags'}")
    print(f"  {'-'*70}")

    below_threshold = []
    rows_with_flags = []

    for r in sorted(subset, key=lambda x: x["id"]):
        score = r.get("completeness_score")
        priority = r.get("needs_priority_review")
        flags = r.get("sanity_flags") or []

        score_str = f"{score:.1%}" if score is not None else "—"
        priority_str = "⚠ YES" if priority else "ok"
        flags_str = ", ".join(flags) if flags else "none"

        print(f"  {r['id']:<6} {score_str:>14} {priority_str:>14}  {flags_str}")

        if priority:
            below_threshold.append(r["id"])
        if flags:
            rows_with_flags.append(r["id"])

    scores = [r["completeness_score"] for r in subset if r.get("completeness_score") is not None]
    avg = sum(scores) / len(scores) if scores else 0

    print(f"\n  Avg completeness    : {avg:.1%}")
    print(f"  Below threshold     : {len(below_threshold)} rows {below_threshold if below_threshold else ''}")
    print(f"  Rows with sanity flags : {len(rows_with_flags)} rows {rows_with_flags if rows_with_flags else ''}")

        # --- Record-level pass rates ---
    l1a_pass = [r for r in subset if r.get("l1a_pass") is True]
    l1b_pass = [r for r in subset if r.get("l1b_pass") is True]

    print(f"\n=== Hand-written subset (rows 1-19) | n={len(subset)} ===\n")
    print(f"  L1a (extraction)  : {len(l1a_pass)}/{len(subset)} = {len(l1a_pass)/len(subset):.1%}")
    print(f"  L1b (arithmetic)  : {len(l1b_pass)}/{len(subset)} = {len(l1b_pass)/len(subset):.1%}")

    print()


if __name__ == "__main__":
    main()

    
