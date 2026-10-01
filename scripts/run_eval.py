# scripts/run_eval.py
#
# Reads the frozen eval set, runs each row's input_text through the LLM
# extraction, and compares the result against ground truth (L1a check).
# Also runs a deterministic regex baseline on every row, for comparison -
# see baseline_extract() below.
# Does NOT compute Enrich/L1b (arithmetic) - that's a separate script,
# since Enrich is pure code and doesn't need an API call to test.

import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import openpyxl
from tools.llm_client import extract_packing_fields
from tools.enrich import compute_derived_weights

EVAL_SET_PATH = "eval/eval_set.xlsx"  # adjust to your actual eval set location/filename

# Ground-truth column name -> LLM output field name.
# The eval set's columns are prefixed "output_"; the LLM's JSON keys are not.
FIELD_MAP = {
    "output_item_qty": "item_qty",
    "output_item_unit": "item_unit",
    "output_item_weight_min": "item_weight_min",
    "output_item_weight_max": "item_weight_max",
    "output_inner_container_um": "inner_container_um",
    "output_item_per_inner_qty": "item_per_inner_qty",
    "output_inner_weight_min": "inner_weight_min",
    "output_inner_weight_max": "inner_weight_max",
    "output_inner_per_master_qty": "inner_per_master_qty",
    "output_master_container_um": "master_container_um",
    "is_weighted": "is_weighted",  # NOTE: no "output_" prefix - the real column
                                    # is just "is_weighted" (was "is_weight" in an
                                    # older eval set version) - "output_is_weighted"
                                    # never existed, so this field was silently
                                    # never being scored before this fix.
    "master_weight_min": "master_weight_min",  # also no "output_" prefix in the
    "master_weight_max": "master_weight_max",  # real sheet - same gap as is_weighted:
                                                # Enrich has always computed these,
                                                # the eval just never checked them.
}

# L1a: fields the LLM states directly (matches primary_tier: 3 in fields.yaml)
L1A_FIELDS = {
    "item_qty", "item_unit", "item_weight_min", "item_weight_max",
    "inner_container_um", "item_per_inner_qty",
    "inner_per_master_qty", "master_container_um",
}
# L1b: fields computed by Enrich - never asked of the LLM directly.
# is_weighted and master_weight are ALWAYS L1b, regardless of packaging
# depth - master_weight's derived_config in fields.yaml depends only on
# inner_weight + inner_per_master_qty, never on whether an item level
# exists.
L1B_ALWAYS_FIELDS = {"is_weighted", "master_weight_min", "master_weight_max"}
# inner_weight is L1b ONLY when an item level exists (3-level docs);
# for 2-level docs it's the LLM's direct statement, so it's checked
# under L1a there instead - see split_l1a_l1b() below.
L1B_ITEM_LEVEL_ONLY_FIELDS = {"inner_weight_min", "inner_weight_max"}

NUMERIC_FIELDS = {
    "item_qty", "item_weight_min", "item_weight_max",
    "item_per_inner_qty", "inner_weight_min", "inner_weight_max",
    "inner_per_master_qty", "master_weight_min", "master_weight_max",
}

TOLERANCE = 0.001  # float comparison tolerance


def values_match(field: str, expected, actual) -> bool:
    """None/None and blank/None both count as a match - the eval set
    uses blank cells for 'not applicable', the LLM uses null for the
    same concept."""
    if expected in (None, "") and actual is None:
        return True
    if expected is None and actual in (None, ""):
        return True
    if expected in (None, "") and actual in (None, ""):
        return True

    if field in NUMERIC_FIELDS:
        try:
            return abs(float(expected) - float(actual)) < TOLERANCE
        except (TypeError, ValueError):
            return False

    # string field - case-insensitive, trims whitespace
    return str(expected).strip().upper() == str(actual).strip().upper()


def baseline_extract(input_text: str) -> dict:
    """Deterministic regex baseline - NO attempt to handle every phrasing
    variant. Targets only the dominant explicit '[N]kg/bag x [N] bags/
    carton' pattern (English, 2-level, no ranges). Everything else (Thai
    phrasing, weight ranges, 3-level packaging, ambiguous/unanswerable
    text) correctly returns extractable=False - that gap IS the finding
    this baseline exists to produce, not a bug to fix. Do not add more
    patterns here; climbing the ladder to an LLM is justified precisely
    because a fixed regex cannot generalize the way language understanding
    does."""
    result = {}

    # "0.5KG/BAG" or "1 kgs/bag" -> per-unit weight, if slash directly follows
    weight_match = re.search(r'(\d+\.?\d*)\s*kgs?\s*/\s*bag', input_text, re.IGNORECASE)
    if weight_match:
        w = float(weight_match.group(1))
        result["inner_weight_min"] = w
        result["inner_weight_max"] = w
        result["inner_container_um"] = "BAG"

    # "x 12 bags/carton" / "x 8 BAGS/BOX" / "x 6 bags/case" -> count + master
    count_match = re.search(r'x\s*(\d+)\s*bags?\s*/\s*(carton|box|case)', input_text, re.IGNORECASE)
    if count_match:
        result["inner_per_master_qty"] = int(count_match.group(1))
        result["master_container_um"] = "CS"  # per real unit_translation.yaml mapping

    # Plain-English variant: "2kgs per bag and 12 bags per carton"
    if not result:
        alt_weight = re.search(r'(\d+\.?\d*)\s*kgs?\s*per\s*bag', input_text, re.IGNORECASE)
        alt_count = re.search(r'(\d+)\s*bags?\s*per\s*carton', input_text, re.IGNORECASE)
        if alt_weight and alt_count:
            w = float(alt_weight.group(1))
            result["inner_weight_min"] = w
            result["inner_weight_max"] = w
            result["inner_container_um"] = "BAG"
            result["inner_per_master_qty"] = int(alt_count.group(1))
            result["master_container_um"] = "CS"

    result["extractable"] = bool(result)  # empty dict -> False = correctly "I don't know"
    return result


def check_fields(extracted: dict, row: list, idx: dict) -> tuple:
    """Shared comparison logic, used for both the LLM's output and the
    baseline's output, so they're scored identically and fairly."""
    field_results = {}
    actual_extractable = extracted.get("extractable")
    all_match = (actual_extractable is True) or (actual_extractable is None)
    if actual_extractable is False:
        all_match = False

    for gt_col, field_name in FIELD_MAP.items():
        expected = row[idx[gt_col]] if gt_col in idx else None
        actual = extracted.get(field_name)
        match = values_match(field_name, expected, actual)
        field_results[field_name] = {"expected": expected, "actual": actual, "match": match}
        if not match:
            all_match = False

    return all_match, field_results


def check_fields_subset(extracted: dict, row, idx, field_names) -> tuple:
    """Same matching logic as check_fields(), restricted to a specific
    set of fields - used to score L1a and L1b independently."""
    field_results = {}
    all_match = True
    for gt_col, field_name in FIELD_MAP.items():
        if field_name not in field_names:
            continue
        expected = row[idx[gt_col]] if gt_col in idx else None
        actual = extracted.get(field_name)
        match = values_match(field_name, expected, actual)
        field_results[field_name] = {"expected": expected, "actual": actual, "match": match}
        if not match:
            all_match = False
    return all_match, field_results


def split_l1a_l1b(extracted_raw: dict, row, idx):
    """Compares LLM's raw extraction (L1a) and Enrich's computed weights
    (L1b) SEPARATELY - never blended into one pass/fail, since they test
    genuinely different things (language understanding vs. arithmetic)."""
    enriched = compute_derived_weights(extracted_raw)
    has_item_level = extracted_raw.get("item_weight_min") is not None

    if has_item_level:
        l1a_fields = L1A_FIELDS
        l1b_fields = L1B_ALWAYS_FIELDS | L1B_ITEM_LEVEL_ONLY_FIELDS
    else:
        # 2-level doc: inner_weight is LLM-direct, belongs to L1a instead
        l1a_fields = L1A_FIELDS | {"inner_weight_min", "inner_weight_max"}
        l1b_fields = L1B_ALWAYS_FIELDS

    l1a_pass, l1a_detail = check_fields_subset(extracted_raw, row, idx, l1a_fields)
    l1b_pass, l1b_detail = check_fields_subset(enriched, row, idx, l1b_fields) if l1b_fields else (True, {})

    return l1a_pass, l1a_detail, l1b_pass, l1b_detail


def run_eval(limit: int = None, show_prompt: bool = True):
    wb = openpyxl.load_workbook(EVAL_SET_PATH, data_only=True)
    ws = wb.active
    header = [c.value for c in ws[1]]
    idx = {h: i for i, h in enumerate(header)}
    rows = [list(r) for r in ws.iter_rows(min_row=2, values_only=True)]

    if limit:
        rows = rows[:limit]

    if show_prompt and rows:
        from config.prompt_config import build_prompt
        sample_prompt = build_prompt(rows[0][idx["input_text"]])
        print("=" * 60)
        print("SAMPLE PROMPT (shown once, using first row's input_text)")
        print("=" * 60)
        print(sample_prompt)
        print("=" * 60)
        print()

    results = []

    for row in rows:
        eid = row[idx["example_id"]]
        input_text = row[idx["input_text"]]
        expected_extractable = row[idx["extractable"]]
        is_unanswerable_gt = (expected_extractable is False or expected_extractable == "FALSE")

        # --- Baseline (no API call, runs regardless of LLM outcome) ---
        baseline_result = baseline_extract(input_text)
        if is_unanswerable_gt:
            baseline_passed = (baseline_result.get("extractable") is False)
            baseline_fields = {}
        else:
            baseline_passed, baseline_fields = check_fields(baseline_result, row, idx)

        # --- LLM ---
        print(f"Running row {eid}...", end=" ", flush=True)
        try:
            extracted = extract_packing_fields(input_text)
        except Exception as e:
            print(f"API ERROR: {e}")
            results.append({
                "id": eid, "input_text": input_text, "status": "api_error", "error": str(e),
                "baseline_passed": baseline_passed,
            })
            continue

        usage = extracted.pop("_usage", None)  # strip before any field-matching logic sees it
        actual_extractable = extracted.get("extractable")

        if is_unanswerable_gt:
            llm_passed = (actual_extractable is False)
            subtype = row[idx["abstain_subtype"]] if "abstain_subtype" in idx else None

            fabricated_and_wrong = None
            if not llm_passed:
                # Model did NOT abstain when it should have - check whether
                # what it fabricated was also factually wrong.
                if subtype == "should_abstain":
                    # No real answer exists for ANY field - any non-null
                    # output at all is a fabrication, no comparison needed.
                    fabricated_and_wrong = any(
                        v is not None for k, v in extracted.items() if k != "extractable"
                    )
                elif subtype == "should_extract_partial":
                    # Some fields DO have real ground truth - only count it
                    # as a dangerous fabrication if a field WITH real ground
                    # truth was gotten wrong (missing fields don't count,
                    # that's the expected gap this row is testing).
                    _, partial_check = check_fields(extracted, row, idx)
                    fabricated_and_wrong = any(
                        not f["match"] for f in partial_check.values() if f["expected"] not in (None, "")
                    )

            print("PASS" if llm_passed else f"FAIL (model said extractable={actual_extractable})")
            print_cost_line(usage)
            print_row_comparison(eid, input_text, mode="extractable_check_only",
                                  expected_extractable=False, actual_extractable=actual_extractable)
            results.append({
                "id": eid, "input_text": input_text,
                "status": "pass" if llm_passed else "fail",
                "mode": "extractable_check_only",
                "expected_extractable": False, "actual_extractable": actual_extractable,
                "baseline_passed": baseline_passed,
                "should_have_abstained": True,
                "abstain_subtype": subtype,
                "did_abstain": llm_passed,
                "fabricated_and_wrong": fabricated_and_wrong,
                "usage": usage,
            })
            continue

        l1a_pass, l1a_detail, l1b_pass, l1b_detail = split_l1a_l1b(extracted, row, idx)
        llm_passed = l1a_pass and l1b_pass  # kept for baseline/API-error bookkeeping compatibility

        print(f"L1a(extraction): {'PASS' if l1a_pass else 'FAIL'}  "
              f"L1b(arithmetic): {'PASS' if l1b_pass else 'FAIL'}  "
              f"(baseline: {'PASS' if baseline_passed else 'FAIL'})")
        print_cost_line(usage)
        print_row_comparison(eid, input_text, mode="full_field_check", fields={**l1a_detail, **l1b_detail})

        results.append({
            "id": eid, "input_text": input_text,
            "status": "pass" if llm_passed else "fail",
            "mode": "full_field_check",
            "l1a_pass": l1a_pass, "l1a_fields": l1a_detail,
            "l1b_pass": l1b_pass, "l1b_fields": l1b_detail,
            "baseline_passed": baseline_passed,
            "usage": usage,
        })

    return results


def print_cost_line(usage):
    """One line per row: $ cost + token counts, plus a retry note if the
    repair-prompt retry fired. Silent if usage is missing (e.g. a row
    that errored before the API call returned)."""
    if not usage or usage.get("cost_usd") is None:
        return
    tag = " (estimated)" if usage.get("cost_estimated") else ""
    retry_note = f"  [retried, {usage.get('attempts')} attempts]" if usage.get("attempts", 1) > 1 else ""
    print(f"    cost: ${usage['cost_usd']:.6f}{tag}  "
          f"({usage.get('tokens_in')} in / {usage.get('tokens_out')} out){retry_note}")

def print_row_comparison(eid, input_text, mode, fields=None,
                          expected_extractable=None, actual_extractable=None):
    """Prints a full side-by-side table for this row, regardless of
    pass/fail - lets you see exactly what the model did, every time."""
    print(f"    input_text: {input_text}")
    if mode == "extractable_check_only":
        match = "match" if expected_extractable == actual_extractable else "MISMATCH"
        print(f"    {'field':<24}{'expected':<18}{'actual':<18}{'result'}")
        print(f"    {'extractable':<24}{str(expected_extractable):<18}{str(actual_extractable):<18}{match}")
    else:
        print(f"    {'field':<24}{'expected':<18}{'actual':<18}{'result'}")
        for field, info in fields.items():
            match = "match" if info["match"] else "MISMATCH"
            print(f"    {field:<24}{str(info['expected']):<18}{str(info['actual']):<18}{match}")
    print()


def summarize_cost(results) -> dict:
    """Aggregates $ cost, token counts, and retry stats across every row
    that has usage data. Shared by print_summary() and save_json_report()
    so the two never drift apart."""
    usages = [r["usage"] for r in results if r.get("usage")]
    if not usages:
        return {
            "total_usd": 0.0, "avg_usd_per_row": None,
            "total_tokens_in": 0, "total_tokens_out": 0,
            "rows_with_cost": 0, "any_cost_estimated": False,
            "rows_needing_retry": 0, "total_extra_attempts": 0,
        }
    total_cost = sum(u["cost_usd"] for u in usages if u.get("cost_usd") is not None)
    attempts_list = [u.get("attempts", 1) for u in usages]
    return {
        "total_usd": round(total_cost, 6),
        "avg_usd_per_row": round(total_cost / len(usages), 6),
        "total_tokens_in": sum(u.get("tokens_in") or 0 for u in usages),
        "total_tokens_out": sum(u.get("tokens_out") or 0 for u in usages),
        "rows_with_cost": len(usages),
        "any_cost_estimated": any(u.get("cost_estimated") for u in usages),
        "rows_needing_retry": sum(1 for a in attempts_list if a > 1),
        "total_extra_attempts": sum(a - 1 for a in attempts_list),
    }


def print_summary(results):
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "pass")
    errors = sum(1 for r in results if r["status"] == "api_error")
    baseline_passed = sum(1 for r in results if r.get("baseline_passed"))

    print(f"LLM (combined L1a+L1b) -- Passed: {passed}  Failed: {total - passed - errors}  API errors: {errors}")
    print(f"Baseline -- Passed: {baseline_passed} / {total}  ({baseline_passed/total*100:.1f}%)" if total else "")

    cost = summarize_cost(results)
    if cost["rows_with_cost"]:
        note = "  (some costs estimated, not OpenRouter-reported)" if cost["any_cost_estimated"] else ""
        print(f"\nCost -- total: ${cost['total_usd']:.4f}  avg/row: ${cost['avg_usd_per_row']:.6f}  "
              f"tokens: {cost['total_tokens_in']} in / {cost['total_tokens_out']} out{note}")
        if cost["rows_needing_retry"]:
            print(f"Retries -- {cost['rows_needing_retry']} / {cost['rows_with_cost']} rows needed a "
                  f"repair-prompt retry ({cost['total_extra_attempts']} extra API call(s) total)")

    # L1a and L1b reported SEPARATELY - never blended, since they test
    # different things (LLM language understanding vs. code arithmetic).
    full_field_results = [r for r in results if r.get("mode") == "full_field_check"]
    if full_field_results:
        l1a_passed = sum(1 for r in full_field_results if r["l1a_pass"])
        l1b_passed = sum(1 for r in full_field_results if r["l1b_pass"])
        n = len(full_field_results)
        print(f"\nL1a (LLM extraction only):  {l1a_passed}/{n} ({l1a_passed/n*100:.1f}%)")
        print(f"L1b (Enrich arithmetic only): {l1b_passed}/{n} ({l1b_passed/n*100:.1f}%)")

    # --- Abstention reporting (the two numbers the rubric asks for) ---
    unanswerable = [r for r in results if r.get("should_have_abstained")]
    if unanswerable:
        correctly_abstained = sum(1 for r in unanswerable if r["did_abstain"])
        false_negatives = [r for r in unanswerable if not r["did_abstain"]]
        dangerous = [r for r in false_negatives if r.get("fabricated_and_wrong")]

        print(f"\nAbstention accuracy: {correctly_abstained}/{len(unanswerable)} "
              f"({correctly_abstained/len(unanswerable)*100:.1f}%) correctly abstained when they should have")
        if false_negatives:
            print(f"Of {len(false_negatives)} cases that did NOT abstain when they should have, "
                  f"{len(dangerous)} fabricated a factually wrong answer")
        else:
            print("No false-negative abstentions - every unanswerable case was correctly caught")

    print("\nFailures (detail):")
    for r in results:
        if r["status"] == "fail":
            print(f"\n  Row {r['id']}:")
            if r.get("mode") == "extractable_check_only":
                print(f"    expected extractable=False, model said {r['actual_extractable']}")
            else:
                for field, info in r.get("fields", {}).items():
                    if not info["match"]:
                        print(f"    {field}: expected={info['expected']!r} actual={info['actual']!r}")


import json
from datetime import datetime, timezone


def save_json_report(results, path="eval/eval_results.json"):
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "pass")
    errors = sum(1 for r in results if r["status"] == "api_error")
    baseline_passed = sum(1 for r in results if r.get("baseline_passed"))

    report = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": total,
            "llm_passed": passed,
            "llm_failed": total - passed - errors,
            "api_errors": errors,
            "llm_pass_rate_pct": round(passed / total * 100, 1) if total else None,
            "baseline_passed": baseline_passed,
            "baseline_pass_rate_pct": round(baseline_passed / total * 100, 1) if total else None,
            "cost": summarize_cost(results),
        },
        "results": results,
    }

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\nJSON report written to: {out_path}")


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    results = run_eval(limit=limit)
    print_summary(results)
    save_json_report(results)