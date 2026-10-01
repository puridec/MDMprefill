# graph/state.py
#
# Shared state threaded through every node. LangGraph's actual job in
# this pipeline is narrow (see the folded workflow design): the L2
# human-review pause is the one place state needs to survive outside a
# single process call. Everything else is plain data flowing straight
# through function calls - the graph exists to hold this dict and to
# make L2's pause/resume possible, not because any stage needs an
# agent-style runtime decision.

from typing import Optional, Dict, Any, List
from typing_extensions import TypedDict


class MDMState(TypedDict):
    # --- Input ---
    input_text: str  # raw spec text. Once OCR exists, this is OCR's
                      # output; for now (OCR parked) it's fed directly.
    input_pdf_path: Optional[str]  # path to an uploaded photo/PDF -
                                     # set instead of input_text when
                                     # the upload entry point is used
    template_id: Optional[str]  # user-selected doc type from the UI
                                  # dropdown (e.g. "GEN") - if set,
                                  # vlm_extract_node crops to that
                                  # region instead of sending the whole
                                  # PDF. None = send whole page.
    

    # --- Stage 3: LLM extraction ---
    extracted_fields: Dict[str, Any]
    extraction_usage: Dict[str, Any]  # tokens_in, tokens_out, cost_usd,
                                       # cost_estimated, attempts - from
                                       # extract_packing_fields()'s _usage

    # --- Stage 4: Enrich ---
    enriched_fields: Dict[str, Any]
    completeness_score: Optional[float]
    needs_priority_review: Optional[bool]

    # --- Stage 5: Domain sanity (not built yet) ---
    sanity_flags: List[str]

    # --- Stage 6: L2 human review ---
    l2_approved: Optional[bool]
    reviewer_id: Optional[str]
    manual_overrides: Dict[str, Any]
    final_fields: Dict[str, Any]      # enriched_fields + manual_overrides applied
    audit_trail: Optional[Dict[str, Any]]  # reviewer_id, timestamp, delta, approved
    status: Optional[str]  # "approved" | "rejected" - set by l2_node