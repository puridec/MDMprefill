# MDMPrefill — Product Documentation

Persona, input/output contract, architecture, and targeted vs. reached metrics — kept separate from `README.md` (which covers running the code) and the course write-up (which covers reasoning and critique).

---

## Persona

| Role | Relationship to the system |
|---|---|
| **R&D (data steward)** | Owns the field definitions, authors the original spec sheet, and is the **mandatory L2 reviewer**. No record reaches the MDM system without R&D's explicit approval, override, or rejection on every field. |
| **Sales Operations (primary user)** | Consumer of the end result. Measured on time-to-ready for a new SKU's master data — this is who the automation is actually saving time for, even though they never touch the tool directly. |
| **Downstream departments (Finance, Supply Chain)** | Currently re-transcribe the same spec sheet independently into their own systems (the core problem this project addresses). Once governed master data exists as a single source of truth, they consume it rather than re-keying it. |

## Input

| Input | Format | Path |
|---|---|---|
| Product specification document | PDF | VLM path — vision model reads the page image directly |
| Pasted packing text | Plain text | Text path — used for manual entry or when text is already available from another system |

Supported container/weight vocabulary and allowed unit values are governed by `config/resources/fields.yaml` — this is the single place that defines what a "valid" extracted value looks like.

## Output

A structured record of governed MDM fields, approved by a human reviewer before it exists anywhere downstream:

| Field | Description |
|---|---|
| `item_qty`, `item_unit` | Count and unit of the smallest packaging level |
| `item_weight_min/max` | Per-item weight (KG) |
| `inner_container_um`, `item_per_inner_qty` | Inner container type and item count |
| `inner_weight_min/max` | Inner container weight (KG) — **derived**, not extracted |
| `inner_per_master_qty`, `master_container_um` | Master carton composition (always `CS`) |
| `master_weight_min/max` | Master carton weight (KG) — **derived**, not extracted |
| `is_weighted` | Whether the product has a genuine weight range vs. a fixed weight |

Plus, on every commit: a **delta log** (which fields changed during L2 review) and an **approval timestamp** — the basic lineage record described in the README's Governance section.

## Architecture (box diagram)

```
                         ┌─────────────────────────┐
  PDF spec sheet ───────▶│   EXTERNAL INTELLIGENCE   │
                         │   Gemini 2.5 Flash (VLM)  │──┐
  Pasted text ──────────▶│   (text-path LLM call)    │  │
                         └─────────────────────────┘  │
                                                        ▼
                         ┌─────────────────────────────────────┐
                         │   CODE LOGIC — no LLM involved        │
                         │                                        │
                         │   1. enrich (tools/enrich.py)          │
                         │      inner_weight = item_wt × per_inner│
                         │      master_weight = inner_wt × per_mst│
                         │                                        │
                         │   2. sanity (tools/domain_sanity.py)   │
                         │      4 independent checks               │
                         │                                        │
                         │   3. completeness (tools/completeness.py)│
                         │      fill-rate vs. document depth        │
                         └───────────────────┬────────────────────┘
                                             ▼
                         ┌─────────────────────────────────────┐
                         │   L2 HUMAN GATE (hardcoded, mandatory) │
                         │   R&D reviews: extracted fields,        │
                         │   enriched fields, completeness score,  │
                         │   sanity flags — as separate signals    │
                         │   Approve / Reject / Override per field │
                         └───────────────────┬────────────────────┘
                                             ▼
                         ┌─────────────────────────────────────┐
                         │   COMMIT                                │
                         │   Delta log + timestamp → governed      │
                         │   MDM field (prints JSON in this POC;   │
                         │   real ERP write is out of scope)       │
                         └─────────────────────────────────────┘
```

**For L2 Human gate, it simulates an MDM system's native stewardship/approval workflow with streamlit — no live MDM platform available for this POC.**

**Orchestration tool:** LangGraph wires these stages into a `StateGraph`, used solely to give the L2 gate a real pause/resume point (`interrupt_before=["l2_review"]`) backed by a checkpointer. It does not route or replan — every node runs in the same fixed order regardless of what the model returns. This is a Rung 2 fixed-sequence prompt chain, not an autonomous agent.

## Metrics — Targeted vs. Reached

| Metric | Targeted | Reached | Source |
|---|---|---|---|
| Extraction accuracy, operational docs (hand-written subset, rows 1–19) | ≥ 75% | **89.5%** (17/19, L1a) | `eval/eval_results_vlm_1-10-2026.json` via `scripts/eval_vlm_handwritten_subset.py` |
| Arithmetic accuracy, operational docs | ≥ 75% | **89.5%** (17/19, L1b) | same |
| Cost per record | < $0.01 | **$0.0015** avg | same, `summary.cost.avg_usd_per_row` |
| API errors | — | **0** / 40 runs | same |
| Overall pass rate, full 40-row set (incl. adversarial) | Not targeted — full set includes intentional stress cases | 65.0% (26/40) | same |
| Avg completeness, full set | — | 79.2% | same |

The operational-subset target (≥75%) was set as the bar for "good enough to be worth a mandatory human review step rather than a fully manual process" — not a bar for full autonomy, since the human gate is permanent regardless of score. Both L1a and L1b clear that target with headroom. The two failing rows (6, 7) share a single root cause — the non-atomic weight pattern — documented in the README's Known Limitations.

The 65% full-set number is not compared against a target because rows 20–40 were built to be adversarial (blank documents, prompt injection, non-governed units) and are not representative of expected production input — see `eval/DATA_EXPLAINER.md`.
