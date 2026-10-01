import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.graph import build_mdm_graph


def show(label, data):
    print(f"  {label}:")
    print(json.dumps(data, indent=2))


def run_full_trace(thread_id, input_text, l2_approved, manual_overrides):
    graph = build_mdm_graph()
    config = {"configurable": {"thread_id": thread_id}}
    path = []

    print(f"\n{'='*70}")
    print(f"CASE: {thread_id}  (l2_approved={l2_approved}, overrides={manual_overrides})")
    print(f"{'='*70}")

    print("\n--- before pause ---")
    for update in graph.stream({"input_text": input_text}, config, stream_mode="updates"):
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

    print(f"\n--- PATH TAKEN: start -> " + " -> ".join(path) + (" -> END" if reached_end else " -> [STILL PAUSED]") + " ---")


TEST_TEXT = input("Enter input text to test: ").strip()

run_full_trace("trace-approved-clean", TEST_TEXT,
                l2_approved=True, manual_overrides={})

run_full_trace("trace-approved-with-correction", TEST_TEXT,
                l2_approved=True, manual_overrides={"master_container_um": "CS-CORRECTED"})

run_full_trace("trace-rejected", TEST_TEXT,
                l2_approved=False, manual_overrides={})