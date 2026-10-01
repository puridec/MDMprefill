# Eval Scripts & Metrics — How to Read the Results

Companion to `DATA_EXPLAINER.md` (which covers the data itself). This explains what each script does, what each metric actually measures, and how to read the results JSON.

---

## Scripts

| Script | What it runs |
|---|---|
| `scripts/run_eval.py` | Text-path eval — feeds each row's `input_text` column straight to the LLM extraction function. Also runs a regex baseline for comparison. |
| `scripts/run_eval_vlm.py` | **The eval that matters for this project.** PDF-path eval — feeds each row's actual PDF (`eval/test/eval_doc_XXX.pdf`) through the vision model, using the same ground truth and comparison logic as `run_eval.py` (imported directly, not duplicated). Writes `eval/eval_results_vlm.json`. |
| `scripts/eval_vlm_handwritten_subset.py` | Doesn't call the model. Reads an existing results JSON (hardcoded to `eval_results_vlm_1-10-2026.json`) and reports a per-field and per-row breakdown for rows 1–19 only — the operational subset. |

To reproduce the canonical numbers: run `python scripts/run_eval_vlm.py`, then `python scripts/eval_vlm_handwritten_subset.py` for the subset detail. Running `run_eval_vlm.py` writes to `eval/eval_results_vlm.json` by default — rename it to `eval_results_vlm_1-10-2026.json` (or edit `RESULTS_FILE` in the subset script) if you want the subset report to pick it up.

## Metrics, defined precisely

Every row falls into one of two evaluation modes depending on its ground truth:

**`full_field_check` mode** (rows where `extractable=TRUE`) — every governed field is compared individually.
- **L1a (extraction accuracy)** — compares the *raw* fields the model returned straight out of extraction (`item_weight`, `inner_container_um`, counts, etc.) against ground truth. This measures whether the model read the document correctly.
- **L1b (arithmetic accuracy)** — compares the *derived* fields (`inner_weight`, `master_weight`, `is_weighted`) computed by `tools/enrich.py` against ground truth. Since enrichment is pure arithmetic on the L1a fields, an L1b failure almost always traces back to an L1a failure upstream — enrichment itself doesn't introduce new errors.
- A row only counts as an overall **pass** if both L1a and L1b pass.

**`extractable_check_only` mode** (rows where `extractable=FALSE`, i.e. the model should abstain) — the only thing checked is whether the model correctly returned `extractable=false`. This is the **abstention accuracy** metric. For rows that fail to abstain, the script further checks whether the model *fabricated* field values on a document it should have rejected (`fabricated_and_wrong`) — a worse failure than simply guessing wrong on an answerable row.

**Completeness** — a separate signal computed by `tools/completeness.py`, independent of ground truth. It measures what fraction of the fields a document's own packaging depth implies should be filled are actually filled. A 2-level document (item → master, no inner) scoring 100% is not penalized for not having inner-level fields; a 3-level document missing its inner weight would be. This runs on *every* row, including ones with no ground truth to compare against, and is what feeds `needs_priority_review` for the L2 reviewer.

**Sanity flags** — from `tools/domain_sanity.py`. Four checks (count positivity, UOM enum membership, min ≤ max, weight hierarchy) run against the enriched output, independent of ground truth and independent of completeness. This is the same check that runs in the live pipeline, not an eval-only metric.

## Reading `eval_results_vlm_1-10-2026.json`

```
{
  "run_timestamp": "...",
  "summary": {
    "total": 40,
    "vlm_passed": 26,              # rows where BOTH L1a and L1b passed (or correctly abstained)
    "vlm_pass_rate_pct": 65.0,      # 26/40, ALL rows including the adversarial set
    "cost": { "avg_usd_per_row": 0.001548, ... },
    "avg_completeness_pct": 79.2,
    "rows_with_sanity_flags": 2
  },
  "results": [ ... ]               # one object per row — l1a_fields / l1b_fields show
                                    # expected vs actual per field, with a "match" bool
}
```

The `summary.vlm_pass_rate_pct` (65.0%) is the full-set number, dragged down by the adversarial rows 20–40 by design (see `DATA_EXPLAINER.md`). The operational-subset numbers (what the report and README actually lead with) come from running `eval_vlm_handwritten_subset.py` against this same file, which filters to rows 1–19 and reports L1a and L1b separately.

### Canonical operational-subset numbers (rows 1–19, from this file)

| Metric | Result |
|---|---|
| L1a (extraction accuracy) | 17/19 = 89.5% |
| L1b (arithmetic accuracy) | 17/19 = 89.5% |
| Avg completeness | ~99% |

Both failing rows (6 and 7) are the same two rows, and both fail for the same underlying reason — the non-atomic weight pattern (see README "Known limitations" #1). That's why L1a and L1b land on the identical count here: the extraction failure and the arithmetic failure aren't independent, they're the same root cause showing up twice.

## Why no LLM judge

Every comparison is exact-match (or type-aware numeric match, e.g. `12` vs `12.0`) against frozen ground truth — see `values_match()` / `split_l1a_l1b()` in `run_eval.py`. There's no LLM grading another LLM's output here. This keeps the eval deterministic and reproducible, at the cost of being strict: a value that's semantically equivalent but not an exact match (e.g. rounding differences beyond float tolerance) would fail, even though an LLM judge might call it close enough.
