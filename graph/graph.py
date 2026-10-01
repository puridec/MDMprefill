from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from graph.state import MDMState
from graph.nodes import (
    extract_node, vlm_extract_node, enrich_node, sanity_node, l2_node,
    commit_node, route_after_l2, route_by_input_type,
)

# graph/graph.py
#
# Wires the fixed-sequence pipeline into a LangGraph StateGraph.
# LangGraph exists here for exactly one reason: interrupt_before=
# ["l2_review"] gives the mandatory human gate a real pause/resume
# point, backed by a checkpointer, instead of a manual "stop and wait
# for input()" hack. It is not used for routing or replanning - every
# node runs in the same fixed order every time, regardless of what the
# model returns. See build_mdm_graph() below for the two entry points.


def build_mdm_graph():
    """OCR/ingestion (EasyOCR) is NOT in this graph - superseded by
    vlm_extract_node for the upload path (Option B). Two entry points
    converge before enrich: extract_node (text - manual entry or
    product-dev-system text) and vlm_extract_node (image/PDF upload).
    Everything from enrich onward is unchanged and shared between both
    paths - neither enrich_node nor anything after it cares which
    extraction node produced extracted_fields."""
    workflow = StateGraph(MDMState)

    workflow.add_node("extract", extract_node)
    workflow.add_node("vlm_extract", vlm_extract_node)
    workflow.add_node("enrich", enrich_node)
    workflow.add_node("sanity", sanity_node)
    workflow.add_node("l2_review", l2_node)
    workflow.add_node("commit", commit_node)

    workflow.set_conditional_entry_point(
        route_by_input_type,
        {"extract": "extract", "vlm_extract": "vlm_extract"},
    )

    workflow.add_edge("extract", "enrich")
    workflow.add_edge("vlm_extract", "enrich")
    workflow.add_edge("enrich", "sanity")
    workflow.add_edge("sanity", "l2_review")

    workflow.add_conditional_edges(
        "l2_review",
        route_after_l2,
        {"commit": "commit", "end": END},
    )
    workflow.add_edge("commit", END)

    memory = MemorySaver()
    return workflow.compile(
        checkpointer=memory,
        interrupt_before=["l2_review"],  # pause HERE, before l2_node runs
    )