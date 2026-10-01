# MDMPrefill

**Individual Project — PE6201 Emerging AI Technologies**

Extracts packing and unit-of-measure (UOM) fields from R&D specification PDFs into governed MDM fields, replacing a manual data-entry process. A mandatory human sign-off gate ensures no field reaches the MDM system without reviewer approval.

---

## What it does

Given a product spec document (PDF or pasted text), MDMPrefill produces a structured set of packing fields:

| Field | Description |
|---|---|
| `item_qty` | Count of the smallest unit (almost always 1) |
| `item_unit` | Unit type — PC, EA, STK, EGG |
| `item_weight_min/max` | Per-item weight in KG |
| `inner_container_um` | Inner container type — BAG, SAC, BOX, TRA, etc. |
| `item_per_inner_qty` | Items per inner container |
| `inner_weight_min/max` | Inner container weight in KG (derived) |
| `inner_per_master_qty` | Inner containers per master carton |
| `master_container_um` | Master container — always CS |
| `master_weight_min/max` | Master carton weight in KG (derived) |
| `is_weighted` | Whether the product has a genuine weight range |

---

## Architecture

See `PRODUCT_DOC.md` for the full box diagram with persona, input/output contract, and metrics targeted vs. reached.

**Classified as Rung 2 (Prompt Chain)** on the course ladder — fixed node sequence, LLM used only for extraction, no step routes or replans based on model output.

### Pipeline stages

**1. Extraction**
- Text path: LLM reads packing text and maps natural language to governed field values and numeric quantities. Converts grams to KG. Abstains (`extractable=false`) when nothing useful can be determined.
- PDF path: Vision model (Gemini 2.5 Flash) reads the document image directly — no OCR step. Crop coordinates from `config/template_regions.py` (GEN or SEA template) isolate the packing detail region before the VLM call, reducing token cost and improving accuracy on fixed-format templates. Whole-page mode available as fallback.

**2. Enrich**
Pure deterministic arithmetic — no LLM involved:
- `inner_weight = item_weight × item_per_inner_qty`
- `master_weight = inner_weight × inner_per_master_qty`
- `is_weighted = (inner_weight_min ≠ inner_weight_max)`

**3. Sanity checks**
Four independent checks on enriched fields:
- Count positivity — all numeric quantities must be > 0
- UOM enum — container units must match `fields.yaml` allowed values
- Min ≤ max — weight min must not exceed weight max
- Hierarchy assertion — item weight ≤ inner weight ≤ master weight

**4. L2 human review (mandatory)**
Every record reaches the reviewer regardless of completeness or sanity flag status. The reviewer sees extracted fields, enriched fields, completeness score, and sanity flags as separate signals before approving, rejecting, or overriding individual fields. Nothing is committed without explicit approval.

**5. Commit**
Final fields written to state. Each approved record produces a delta log capturing which extracted values changed during L2 review, along with the approval timestamp. Combined with the source document, this provides traceable lineage from raw spec to committed field value. In this POC, `commit_node` prints the final JSON — real MDM system write is explicitly out of scope.

### Why LangGraph
LangGraph is used solely for `interrupt_before=["l2_review"]` checkpointing — it holds state before the human gate and does not route the workflow. It was chosen over a plain sequential script for two forward-looking reasons: the node structure makes it straightforward to add fields in future (storage type, product classification) without rewiring the pipeline, and decoupling the extraction node from enrichment and sanity keeps each stage independently testable and maintainable.

---

## Evaluation

### Eval set design

| Rows | Type | Description |
|---|---|---|
| 1–19 | Hand-written (operational) | Packing field text authored by an R&D practitioner familiar with real spec sheet conventions, with numerical values shifted. Surrounding document content is synthetic. |
| 20–40 | Synthetic (robustness) | Edge cases, ambiguous phrasing, abstention triggers, adversarial inputs. Not representative of operational reality. |

Ground truth was frozen before inference. Generation script is committed. Evaluation uses string equality against frozen ground truth — no LLM judge.

### Metrics

- **L1a** — Extraction accuracy: raw LLM output vs ground truth
- **L1b** — Arithmetic accuracy: enrich output vs ground truth
- **Completeness** — Fill rate normalized by document depth (2-level vs 3-level)
- **Abstention accuracy** — Fraction of unanswerable records correctly caught

See `eval/DATA_EXPLAINER.md` and `eval/EVAL_EXPLAINER.md` for full detail on how the eval set was built and how each metric is computed.

### Results (hand-written subset, rows 1–19, VLM path)

Canonical source: `eval/eval_results_vlm_1-10-2026.json`, via `python scripts/eval_vlm_handwritten_subset.py`.

| Metric | Score |
|---|---|
| L1a (extraction) | 89.5% (17/19) |
| L1b (arithmetic) | 89.5% (17/19) |
| Avg completeness | ~99% |

Both failing rows (6 and 7) fail for the same root cause — the non-atomic weight pattern (Known Limitations #1) — not two independent problems.

### Results (full eval set, 40 rows, VLM path)

| Metric | Score |
|---|---|
| Overall pass rate | 65.0% (26/40) |
| Avg completeness | 79.2% |
| Avg cost per record | $0.0015 |
| Total cost (40 runs) | $0.0619 |
| API errors | 0 |

The lower overall pass rate reflects the adversarial rows (20–40): blank PDFs, prompt injection strings, and non-governed units not representative of real supplier submissions.

`eval/eval_results_vlm_30-9-2026.json` is a superseded run, kept for reference only — a prompt tweak between runs changed which rows trigger sanity flags (8 → 2) and shifted cost per row slightly ($0.0017 → $0.0015). Treat the 1-10-2026 file as the source of truth for every number in this README and in the project report.

## Key design decisions

**No calculator-tool agent for Enrich** — the formula is fixed and known at design time. A tool call adds cost, latency, and failure surface for zero flexibility gained.

**OCR dropped entirely** — PDFs go through a vision model directly (VLM reads the page image and extracts fields in one call). OCR-then-extract was rejected because it discards the layout and visual context that is the VLM's main advantage over a text model.

**Retries are internal to node functions, not extra graph edges** — LLM retry fires only on invalid JSON at temperature 0.0 with a repair prompt. Retrying on low completeness risks the model fabricating values to look complete.

**`l2_node` never gates on sanity flags** — every record reaches the human regardless. Completeness, sanity, and L1a/L1b are three genuinely separate signals, never blended into a single pass/fail gate.

**Cropping vs whole-page** — crop coordinates isolate the packing information region of the spec sheet, reducing token cost and improving extraction accuracy by removing irrelevant page content. Whole-page mode is available as a fallback for cases where the crop fails (blank extraction) or when a future scope expansion requires fields from outside the packing region. Per-document explicit template tagging (`eval_doc_templates.json`) is used to assign the correct crop coordinates rather than inferring template from document position.

**Native PDF upload was planned, not used** — the original design assumed PDFs could go through OpenRouter's native file-upload path (`tools/llm_client.py`'s `_pdf_to_content_part()`, now unused). That path only works with models that have built-in native PDF support; Gemini 2.5 Flash rejects it outright. Pages are rendered locally to an image instead, reusing the same crop coordinates originally built for the abandoned OCR pipeline.

---

## Known limitations

**1. Non-atomic weight format (rows 6, 7, 14)**
Formats where a combined weight is stated before a count — e.g. `1.33KGX8BAGSX1OUTERBAG/CASE` or `990G(33STICK)X1BAG` — cause the model to extract the nominal value directly instead of dividing by the group count. The prompt does not include a worked division example for this pattern. Left as a known limitation rather than fixed: the format is uncommon enough in operational spec sheets that adding a division rule risks introducing errors on the more common per-unit formats. The L2 gate reliably surfaces the anomaly because the enriched master carton weight becomes implausibly large, which the sanity hierarchy check flags for the reviewer. Affects 3 of 19 hand-written eval rows.

**2. `master_container_um` BOX vs CS**
When source text says "per box" as the outermost container, the model occasionally returns `BOX` instead of the governed `CS`. The normalisation rule (all master containers map to CS) is in the prompt but not perfectly followed. Flagged by the sanity UOM check.

**3. Hierarchy level-shift on 2-level documents**
On documents with exactly one container level above the innermost unit, the model sometimes cannot determine whether that is an item+inner or inner+master document. The depth test prompt rule addresses this but does not fully eliminate the error.

**4. Abstain boundary failures**
The model occasionally extracts partial data from documents it should reject entirely (rows 31, 36 in eval). Clearer abstain instruction and a minimum-completeness threshold are under consideration. Both failure modes are acceptable in this POC because the L2 gate is the final backstop: if a value is wrong the reviewer corrects it; if a value is hallucinated the reviewer removes it and inputs manually.

**5. Eval set is synthetic PDFs**
All 40 eval PDFs are computer-generated documents. Packing field text for rows 1–19 is human-authored but surrounding document content is synthetic. Real production documents may present different layout variance, print quality, and handwritten annotations not covered by this eval set.

**6. No production system integration**
`commit_node` is a deliberate placeholder — it prints final JSON. Real MDM write and review workflow are explicitly out of scope for this POC. L2 review and commit are capabilities a production MDM platform would natively provide; both are simulated here in Streamlit because no live MDM system is available to integrate with.

---

## File map

| Path | Role |
|---|---|
| `config/settings.py` | Model names, retry limits, price fallback constants |
| `config/prompt_config.py` | Prompt builders for text and VLM paths |
| `config/resources/fields.yaml` | Field dictionary and allowed values |
| `config/resources/unit_translation.yaml` | Thai/English → MDM unit code lookup |
| `config/template_regions.py` | Crop coordinates for GEN and SEA templates |
| `tools/llm_client.py` | LLM and VLM extraction calls |
| `tools/enrich.py` | Deterministic arithmetic for derived weight fields |
| `tools/completeness.py` | Fill-rate scoring by document depth |
| `tools/domain_sanity.py` | Four sanity checks on enriched fields |
| `graph/state.py` | `MDMState` TypedDict |
| `graph/nodes.py` | All graph nodes and routing functions |
| `graph/graph.py` | `build_mdm_graph()` — wires the pipeline |
| `scripts/run_eval.py` | Offline eval harness, text path |
| `scripts/run_eval_vlm.py` | Offline eval harness, VLM/PDF path |
| `scripts/eval_vlm_handwritten_subset.py` | Subset report for rows 1–19 (reads `eval/eval_results_vlm_1-10-2026.json`) |
| `eval/eval_set.xlsx` | Frozen ground truth (40 rows) |
| `eval/eval_doc_templates.json` | Per-document template tagging |
| `eval/eval_results_vlm_1-10-2026.json` | Canonical eval results — source for every number in this README |
| `eval/test/` | 40 synthetic spec PDFs |
| `eval/DATA_EXPLAINER.md` | What's in the eval data and how it was built |
| `eval/EVAL_EXPLAINER.md` | What each script and metric does, how to read the results JSON |
| `PRODUCT_DOC.md` | Persona, input/output, architecture box diagram, metrics targeted vs. reached |
| `app.py` | Streamlit UI — input, extraction, L2 review, commit |
| `run_app.bat` | One-click launcher for Windows |

---

## How to run

**Install dependencies**
```bash
pip install -r requirements.txt
```

**Run the Streamlit UI**
```bash
streamlit run app.py
# or double-click run_app.bat on Windows
```

**Run eval (text path)**
```bash
python scripts/run_eval.py
```

**Run eval (VLM/PDF path)**
```bash
python scripts/run_eval_vlm.py
```

**Run hand-written subset report**
```bash
python scripts/eval_vlm_handwritten_subset.py
```
Reads `eval/eval_results_vlm_1-10-2026.json` by default — if you've just run `run_eval_vlm.py` fresh, rename its output (`eval/eval_results_vlm.json`) to match, or edit `RESULTS_FILE` in the script.

**Set up API key**
Create a `.env` file in the project root:
```
OPENROUTER_API_KEY=your_key_here
```

---

## Models used

| Path | Model |
|---|---|
| Text extraction | Configurable via `LLM_MODEL` in `config/settings.py` |
| PDF extraction | `google/gemini-2.5-flash` (via OpenRouter) |

`reasoning: {"enabled": false}` is set on all calls to suppress hidden reasoning traces.

---

*PE6201 Emerging AI Technologies — Individual Project — Puri Dechasiripong*
