import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.graph import build_mdm_graph


def show(label, data):
    print(f"  {label}:")
    print(json.dumps(data, indent=2))


def run_full_trace(thread_id, initial_state, l2_approved, manual_overrides):
    """initial_state is the whole dict passed to graph.stream() - either
    {"input_text": ...} for the text path or {"input_image_path": ...}
    for the upload/VLM path. route_by_input_type() reads whichever key
    is present to decide which entry node to run."""
    graph = build_mdm_graph()
    config = {"configurable": {"thread_id": thread_id}}
    path = []

    print(f"\n{'='*70}")
    print(f"CASE: {thread_id}  (l2_approved={l2_approved}, overrides={manual_overrides})")
    print(f"input: {initial_state}")
    print(f"{'='*70}")

    print("\n--- before pause ---")
    for update in graph.stream(initial_state, config, stream_mode="updates"):
        for node_name, changes in update.items():
            path.append(node_name)
            print(f"\n[{node_name}] ran")
            show("changed", changes)
            show("full state now", graph.get_state(config).values)

    state = graph.get_state(config)
    print(f"\n>>> PAUSED - waiting on: {state.next}")

    graph.update_state(config, {
        "reviewer_id": "puri",
        "l2_approved": l2_approved,
        "manual_overrides": manual_overrides,
    })

    print("\n--- after human decision, resuming ---")
    for update in graph.stream(None, config, stream_mode="updates"):
        for node_name, changes in update.items():
            path.append(node_name)
            print(f"\n[{node_name}] ran")
            show("changed", changes)
            show("full state now", graph.get_state(config).values)

    final_state = graph.get_state(config)
    reached_end = not final_state.next
    print(f"\n>>> FINAL - next: {final_state.next}  (empty = run complete)")
    print(f">>> FINAL STATUS: {final_state.values.get('status')}")

    print(f"\n--- PATH TAKEN: start -> " + " -> ".join(path) + (" -> END" if reached_end else " -> [STILL PAUSED]") + " ---")


mode = input("Test which entry point - (t)ext or (i)mage? ").strip().lower()

if mode == "i":
    image_path = input("Enter path to a test image/PDF: ").strip()
    base_state = {"input_pdf_path": image_path}
else:
    text = input("Enter input text to test: ").strip()
    base_state = {"input_text": text}

run_full_trace("trace-approved-clean", base_state,
                l2_approved=True, manual_overrides={})

run_full_trace("trace-approved-with-correction", base_state,
                l2_approved=True, manual_overrides={"master_container_um": "CS-CORRECTED"})

run_full_trace("trace-rejected", base_state,
                l2_approved=False, manual_overrides={})