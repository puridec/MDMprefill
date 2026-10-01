# graph/nodes.py
#
# Node functions for the LangGraph graph. Each node takes the current
# MDMState and returns a dict of the fields it updates - LangGraph
# merges this into state automatically (it does NOT replace the whole
# state, only the keys you return). Nodes are thin wrappers around the
# existing tools/ functions - no new logic lives here, on purpose.

from tools.llm_client import extract_packing_fields
from tools.enrich import compute_derived_weights
from tools.completeness import compute_completeness, needs_priority_review
from graph.state import MDMState
from tools.domain_sanity import check_domain_sanity
from datetime import datetime, timezone
from tools.llm_client import extract_packing_fields, extract_packing_fields_from_pdf
import json


def sanity_node(state: MDMState) -> dict:
    """Stage 5 - domain sanity. Pure function of enriched_fields, no LLM
    call, no ground truth. Returns sanity_flags only - deliberately
    never touches completeness_score or needs_priority_review, so the
    two signals stay separate all the way to L2."""
    flags = check_domain_sanity(state["enriched_fields"])
    return {"sanity_flags": flags}

def vlm_extract_node(state: MDMState) -> dict:
    """Stage 3, upload path - VLM reads the image directly and extracts
    fields in one call (Option B), instead of OCR-then-extract. Same
    output shape as extract_node, so enrich_node downstream needs no
    changes regardless of which path produced extracted_fields."""

    raw = extract_packing_fields_from_pdf(
        state["input_pdf_path"],
        template_id=state.get("template_id"),
    )
    usage = raw.pop("_usage", None)

    return {
        "extracted_fields": raw,
        "extraction_usage": usage,
    }

def extract_node(state: MDMState) -> dict:
    """Stage 3 - LLM extraction. extract_packing_fields() already
    handles its own bounded repair-prompt retry internally (see
    tools/llm_client.py) - this node adds no retry logic of its own,
    it just calls the tool once and unpacks the result."""
    raw = extract_packing_fields(state["input_text"])
    usage = raw.pop("_usage", None)

    return {
        "extracted_fields": raw,
        "extraction_usage": usage,
    }


def enrich_node(state: MDMState) -> dict:
    """Stage 4 - deterministic arithmetic + completeness scoring. Wraps
    compute_derived_weights() and completeness.py. No LLM call, no
    retry - purely a function of extracted_fields already in state, so
    this node is fully deterministic and side-effect free."""
    extracted = state["extracted_fields"]
    enriched = compute_derived_weights(extracted)

    return {
        "enriched_fields": enriched,
        "completeness_score": compute_completeness(enriched),
        "needs_priority_review": needs_priority_review(enriched),
    }

def l2_node(state: MDMState) -> dict:
    """Stage 6 - runs AFTER the human-review pause resumes. By this
    point an external caller has already injected reviewer_id,
    l2_approved, and manual_overrides into state (via LangGraph's
    update_state(), before resuming). This node does NOT decide
    whether to proceed to commit - that's a conditional edge in
    graph.py based on l2_approved. Its only job is applying whatever
    the human decided and logging exactly what changed."""
    enriched = state["enriched_fields"]
    overrides = state.get("manual_overrides") or {}

    final_fields = dict(enriched)
    delta = {}
    for field, new_value in overrides.items():
        old_value = enriched.get(field)
        if new_value != old_value:
            delta[field] = {"extracted": old_value, "override": new_value}
            final_fields[field] = new_value

    audit_entry = {
        "reviewer_id": state.get("reviewer_id"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "delta": delta,
        "approved": state.get("l2_approved"),
    }

    return {
        "final_fields": final_fields,
        "audit_trail": audit_entry,
        "status": "approved" if state.get("l2_approved") else "rejected",
    }


def commit_node(state: MDMState) -> dict:
    """Stage 7 - final step. Deliberately does NOT write to any real
    system (MDM/SAP integration is out of scope for this project).
    final_fields is what a Streamlit UI would display/consume once
    built - this just shows the same JSON that UI will eventually
    receive, so the shape is visible now without building the UI yet."""
    print("=== FINAL RECORD (JSON) ===")
    print(json.dumps(state.get("final_fields"), indent=2))
    return {}


def route_after_l2(state: MDMState) -> str:
    """Conditional edge, not a node - reads l2_approved (set externally
    before the graph resumes from the interrupt) and decides whether to
    proceed to commit or end the run."""
    return "commit" if state.get("l2_approved") else "end"


def route_by_input_type(state: MDMState) -> str:
    """Conditional entry point - decides which extraction path based on
    what's actually present in the initial state. Upload sets
    input_image_path; manual entry or product-dev-system text sets
    input_text. Deterministic type-check, not a model decision - same
    shape as the OCR confidence gate's Branch A/B routing."""
    if state.get("input_pdf_path"):
        return "vlm_extract"
    return "extract"