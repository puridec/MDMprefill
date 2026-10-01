# scripts/run_eval_vlm.py
#
# PDF/VLM equivalent of run_eval.py - reads the SAME frozen eval set
# (ground truth doesn't change based on input modality), but runs each
# row's matching PDF through extract_packing_fields_from_pdf() instead
# of extract_packing_fields(input_text). Comparison logic (FIELD_MAP,
# values_match, split_l1a_l1b, etc.) is imported from run_eval.py
# directly rather than duplicated - it's the same ground truth being
# checked against, regardless of which extraction path produced the
# answer.
#
# No baseline comparison here - run_eval.py's regex baseline only makes
# sense against text input, there's no equivalent for images.
#
# Cropping: template_id_for() below is an EVAL-ONLY convention (odd
# rows = GEN, even rows = SEA) based on how the 40 test PDFs were
# built. This is NOT how production decides template_id - in the real
# pipeline it comes from the user's UI selection at upload
# (graph/state.py's template_id field), never inferred from row number.

import sys
import json
from pathlib import Path
import json as _json
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).parent.parent))

import openpyxl
from tools.llm_client import extract_packing_fields_from_pdf
from config.template_regions import TEMPLATE_REGIONS
from scripts.run_eval import (
    EVAL_SET_PATH, split_l1a_l1b, summarize_cost, print_cost_line, check_fields,
)
from tools.completeness import compute_completeness, needs_priority_review, COMPLETENESS_THRESHOLD
from tools.domain_sanity import check_domain_sanity
from tools.enrich import compute_derived_weights

# --- Adjust these two to match where your 40 PDFs actually are ---
EVAL_DOCS_DIR = "eval/test"
def pdf_path_for(example_id) -> Path:
    return Path(EVAL_DOCS_DIR) / f"eval_doc_{int(example_id):03d}.pdf"



DOC_TEMPLATES_PATH = Path("eval/eval_doc_templates.json")

def _load_doc_templates() -> dict:
    with open(DOC_TEMPLATES_PATH, encoding="utf-8") as f:
        return _json.load(f)

_DOC_TEMPLATES = _load_doc_templates()

def template_id_for(example_id) -> str:
    """Reads the explicit per-document template assignment from
    eval/eval_doc_templates.json, rather than inferring odd/even - the
    inferred convention already proved wrong once (rows 20-40 broke
    the "same template = same layout" assumption), so this is recorded
    ground truth, not a guess. Still EVAL-ONLY: production gets
    template_id from the user's UI selection at upload, not a lookup
    table keyed by row number."""
    return _DOC_TEMPLATES.get(str(example_id))


def print_row_comparison(eid, pdf_path, mode, fields=None,
                          expected_extractable=None, actual_extractable=None):
    print(f"    pdf: {pdf_path}")
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


def run_eval_vlm(limit: int = None):
    wb = openpyxl.load_workbook(EVAL_SET_PATH, data_only=True)
    ws = wb.active
    header = [c.value for c in ws[1]]
    idx = {h: i for i, h in enumerate(header)}
    rows = [list(r) for r in ws.iter_rows(min_row=2, values_only=True)]

    if limit:
        rows = rows[:limit]

    results = []
    skipped = []

    for row in rows:
        eid = row[idx["example_id"]]
        pdf_path = pdf_path_for(eid)

        if not pdf_path.exists():
            print(f"Row {eid}: SKIPPED (no PDF found at {pdf_path})")
            skipped.append(eid)
            continue

        template_id = template_id_for(eid)
        if template_id is not None and template_id not in TEMPLATE_REGIONS:
            print(f"Row {eid}: SKIPPED (template '{template_id}' has no coordinates yet)")
            skipped.append(eid)
            continue

        expected_extractable = row[idx["extractable"]]
        is_unanswerable_gt = (expected_extractable is False or expected_extractable == "FALSE")

        print(f"Running row {eid} ({pdf_path.name}, template={template_id})...", end=" ", flush=True)
        try:
            extracted = extract_packing_fields_from_pdf(str(pdf_path), template_id=template_id)
        except Exception as e:
            print(f"API ERROR: {e}")
            results.append({
                "id": eid, "pdf": str(pdf_path), "template_id": template_id,
                "status": "api_error", "error": str(e),
            })
            continue

        usage = extracted.pop("_usage", None)
        actual_extractable = extracted.get("extractable")

        # --- completeness and sanity on enriched fields ---
        enriched = compute_derived_weights(extracted)
        completeness = compute_completeness(enriched)
        priority_flag = needs_priority_review(enriched)
        sanity_flags = check_domain_sanity(enriched)

        if is_unanswerable_gt:
            llm_passed = (actual_extractable is False)
            subtype = row[idx["abstain_subtype"]] if "abstain_subtype" in idx else None

            fabricated_and_wrong = None
            if not llm_passed:
                if subtype == "should_abstain":
                    fabricated_and_wrong = any(
                        v is not None for k, v in extracted.items() if k not in ("extractable", "raw_text_seen")
                    )
                elif subtype == "should_extract_partial":
                    _, partial_check = check_fields(extracted, row, idx)
                    fabricated_and_wrong = any(
                        not f["match"] for f in partial_check.values() if f["expected"] not in (None, "")
                    )

            print("PASS" if llm_passed else f"FAIL (model said extractable={actual_extractable})")
            print_cost_line(usage)
            print_row_comparison(eid, pdf_path, mode="extractable_check_only",
                                  expected_extractable=False, actual_extractable=actual_extractable)
            results.append({
                "id": eid, "pdf": str(pdf_path), "template_id": template_id,
                "status": "pass" if llm_passed else "fail",
                "mode": "extractable_check_only",
                "expected_extractable": False, "actual_extractable": actual_extractable,
                "should_have_abstained": True,
                "abstain_subtype": subtype,
                "did_abstain": llm_passed,
                "fabricated_and_wrong": fabricated_and_wrong,
                "raw_text_seen": extracted.get("raw_text_seen"),
                "usage": usage,
                "completeness_score": completeness,
                "needs_priority_review": priority_flag,
                "sanity_flags": sanity_flags,
            })
            continue

        l1a_pass, l1a_detail, l1b_pass, l1b_detail = split_l1a_l1b(extracted, row, idx)
        llm_passed = l1a_pass and l1b_pass

        print(f"L1a(extraction): {'PASS' if l1a_pass else 'FAIL'}  "
              f"L1b(arithmetic): {'PASS' if l1b_pass else 'FAIL'}")
        print_cost_line(usage)
        print_row_comparison(eid, pdf_path, mode="full_field_check", fields={**l1a_detail, **l1b_detail})

        results.append({
            "id": eid, "pdf": str(pdf_path), "template_id": template_id,
            "status": "pass" if llm_passed else "fail",
            "mode": "full_field_check",
            "l1a_pass": l1a_pass, "l1a_fields": l1a_detail,
            "l1b_pass": l1b_pass, "l1b_fields": l1b_detail,
            "raw_text_seen": extracted.get("raw_text_seen"),
            "usage": usage,
            "completeness_score": completeness,
            "needs_priority_review": priority_flag,
            "sanity_flags": sanity_flags,
        })

    if skipped:
        print(f"\n{len(skipped)} row(s) skipped: {skipped}")

    return results


def print_summary(results):
    print("\n" + "=" * 50)
    print("SUMMARY (VLM/PDF path)")
    print("=" * 50)
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "pass")
    errors = sum(1 for r in results if r["status"] == "api_error")

    print(f"VLM (combined L1a+L1b) -- Passed: {passed}  Failed: {total - passed - errors}  API errors: {errors}")

    cost = summarize_cost(results)
    if cost["rows_with_cost"]:
        note = "  (some costs estimated, not OpenRouter-reported)" if cost["any_cost_estimated"] else ""
        print(f"\nCost -- total: ${cost['total_usd']:.4f}  avg/row: ${cost['avg_usd_per_row']:.6f}  "
              f"tokens: {cost['total_tokens_in']} in / {cost['total_tokens_out']} out{note}")
        if cost["rows_needing_retry"]:
            print(f"Retries -- {cost['rows_needing_retry']} / {cost['rows_with_cost']} rows needed a "
                  f"repair-prompt retry ({cost['total_extra_attempts']} extra API call(s) total)")

    full_field_results = [r for r in results if r.get("mode") == "full_field_check"]
    if full_field_results:
        l1a_passed = sum(1 for r in full_field_results if r["l1a_pass"])
        l1b_passed = sum(1 for r in full_field_results if r["l1b_pass"])
        n = len(full_field_results)
        print(f"\nL1a (VLM extraction only):  {l1a_passed}/{n} ({l1a_passed/n*100:.1f}%)")
        print(f"L1b (Enrich arithmetic only): {l1b_passed}/{n} ({l1b_passed/n*100:.1f}%)")

    # Per-template breakdown - since GEN and SEA use different
    # coordinates, worth seeing whether one template performs worse
    # than the other rather than only a blended number.
    for tid in sorted(set(r.get("template_id") for r in results if r.get("template_id"))):
        subset = [r for r in full_field_results if r.get("template_id") == tid]
        if subset:
            l1a_n = sum(1 for r in subset if r["l1a_pass"])
            l1b_n = sum(1 for r in subset if r["l1b_pass"])
            print(f"  [{tid}]  L1a: {l1a_n}/{len(subset)}  L1b: {l1b_n}/{len(subset)}")

    # --- completeness and sanity summary ---
    scoreable = [r for r in results if r.get("completeness_score") is not None]
    if scoreable:
        avg_completeness = sum(r["completeness_score"] for r in scoreable) / len(scoreable)
        below_threshold = [r for r in scoreable if r.get("needs_priority_review")]
        print(f"\nCompleteness (avg): {avg_completeness:.1%}  "
              f"Below threshold (<{COMPLETENESS_THRESHOLD:.0%}): {len(below_threshold)}/{len(scoreable)}")
        if below_threshold:
            print("  Rows below threshold:")
            for r in below_threshold:
                print(f"    Row {r['id']} [{r.get('template_id')}]: {r['completeness_score']:.1%}")

    rows_with_flags = [r for r in results if r.get("sanity_flags")]
    if rows_with_flags:
        print(f"\nSanity flags ({len(rows_with_flags)} rows):")
        for r in rows_with_flags:
            print(f"  Row {r['id']} [{r.get('template_id')}]: {', '.join(r['sanity_flags'])}")
    else:
        print("\nSanity flags: none across all rows.")

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
            print(f"\n  Row {r['id']} [{r.get('template_id')}]:")
            if r.get("mode") == "extractable_check_only":
                print(f"    expected extractable=False, model said {r['actual_extractable']}")
            else:
                for field, info in r.get("fields", {}).items():
                    if not info["match"]:
                        print(f"    {field}: expected={info['expected']!r} actual={info['actual']!r}")


def save_json_report(results, path="eval/eval_results_vlm.json"):
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "pass")
    errors = sum(1 for r in results if r["status"] == "api_error")

    report = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": total,
            "vlm_passed": passed,
            "vlm_failed": total - passed - errors,
            "api_errors": errors,
            "vlm_pass_rate_pct": round(passed / total * 100, 1) if total else None,
            "cost": summarize_cost(results),
            "avg_completeness_pct": round(
                sum(r.get("completeness_score", 0) for r in results if r.get("completeness_score") is not None)
                / max(1, sum(1 for r in results if r.get("completeness_score") is not None)) * 100, 1
            ),
            "rows_below_completeness_threshold": sum(1 for r in results if r.get("needs_priority_review")),
            "rows_with_sanity_flags": sum(1 for r in results if r.get("sanity_flags")),
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
    results = run_eval_vlm(limit=limit)
    print_summary(results)
    save_json_report(results)