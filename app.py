# app.py
# MDMPrefill — Streamlit UI
# Run from project root: streamlit run app.py

import streamlit as st
from pathlib import Path
from PIL import Image, ImageDraw
import fitz  # pymupdf
import sys
import json
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from config.template_regions import TEMPLATE_REGIONS

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MDMPrefill",
    page_icon="📦",
    layout="centered",
)

# ── styling ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stSelectbox label, .stTextArea label, .stFileUploader label {
        font-size: 0.85rem; font-weight: 600; color: #555; letter-spacing: 0.02em;
    }
    .section-title {
        font-size: 0.75rem; font-weight: 700; letter-spacing: 0.08em;
        color: #999; text-transform: uppercase;
        margin-bottom: 0.25rem; margin-top: 1.5rem;
    }
    .preview-box {
        background: #f8f8f8; border: 1px solid #e0e0e0; border-radius: 6px;
        padding: 0.75rem 1rem; font-size: 0.85rem; font-family: monospace;
        color: #333; margin-top: 0.5rem; word-break: break-all;
    }
    .badge-ready {
        display: inline-block; background: #e6f4ea; color: #2d7a3a;
        font-size: 0.75rem; font-weight: 600;
        padding: 0.2rem 0.6rem; border-radius: 99px; margin-left: 0.5rem;
    }
    .badge-pending {
        display: inline-block; background: #fff3e0; color: #b35c00;
        font-size: 0.75rem; font-weight: 600;
        padding: 0.2rem 0.6rem; border-radius: 99px; margin-left: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)


# ── helpers ───────────────────────────────────────────────────────────────────
def show_pdf_preview(pdf_path: str, template_id: str | None):
    try:
        doc = fitz.open(pdf_path)
        page = doc[0]
        mat = fitz.Matrix(150 / 72, 150 / 72)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
    except Exception as e:
        st.warning(f"Could not render PDF preview: {e}")
        return

    w, h = img.size
    col1, col2 = st.columns(2)

    with col1:
        st.caption("📄 Full page")
        if template_id and template_id in TEMPLATE_REGIONS:
            region = TEMPLATE_REGIONS[template_id]
            overlay = img.copy().convert("RGBA")
            draw = ImageDraw.Draw(overlay, "RGBA")
            draw.rectangle([(0, 0), (w, h)], fill=(0, 0, 0, 80))
            x0 = int(region["left"] * w)
            y0 = int(region["top"] * h)
            x1 = int(region["right"] * w)
            y1 = int(region["bottom"] * h)
            draw.rectangle([(x0, y0), (x1, y1)], fill=(0, 0, 0, 0))
            draw.rectangle([(x0, y0), (x1, y1)], outline=(255, 165, 0, 255), width=2)
            final = Image.alpha_composite(img.convert("RGBA"), overlay)
            st.image(final, use_container_width=True)
        else:
            st.image(img, use_container_width=True)

    with col2:
        st.caption(f"✂️ Crop region ({template_id or 'none'})")
        if template_id and template_id in TEMPLATE_REGIONS:
            region = TEMPLATE_REGIONS[template_id]
            x0 = int(region["left"] * w)
            y0 = int(region["top"] * h)
            x1 = int(region["right"] * w)
            y1 = int(region["bottom"] * h)
            cropped = img.crop((x0, y0, x1, y1))
            scale = max(1, int(300 / max(1, y1 - y0)))
            cropped_large = cropped.resize(((x1 - x0) * scale, (y1 - y0) * scale), Image.LANCZOS)
            st.image(cropped_large, use_container_width=True)
            st.caption(f"_{region['description']}_")
        else:
            st.info("Select a template to see the crop region.")


def fields_to_table(fields: dict, label_col: str = "Field", value_col: str = "Value") -> list[dict]:
    """Convert fields dict to a list of {Field, Value} rows for st.table."""
    skip = {"raw_test_seen"}
    return [
        {label_col: k, value_col: ("—" if v is None else str(v))}
        for k, v in fields.items()
        if k not in skip
    ]


def save_result(thread_id, initial_state, extracted, enriched, sanity_flags,
                completeness, reviewer_id, l2_approved, overrides, final_fields, audit_trail):
    out_dir = Path("results")
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{thread_id}_{ts}.json"
    log = {
        "thread_id": thread_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input": {
            "input_text": initial_state.get("input_text") or None,
            "input_pdf_path": initial_state.get("input_pdf_path") or None,
            "template_id": initial_state.get("template_id") or None,
        },
        "extracted_fields": extracted,
        "enriched_fields": enriched,
        "completeness_score": completeness,
        "sanity_flags": sanity_flags,
        "reviewer_id": reviewer_id,
        "l2_approved": l2_approved,
        "manual_overrides": overrides,
        "final_fields": final_fields,
        "audit_trail": audit_trail,
    }
    path = out_dir / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, default=str)
    return str(path)


# ── session state init ────────────────────────────────────────────────────────
for key in ["extraction_done", "graph", "graph_config", "initial_state",
            "extracted_fields", "enriched_fields", "sanity_flags",
            "completeness_score", "needs_priority_review", "l2_done",
            "final_fields", "audit_trail"]:
    if key not in st.session_state:
        st.session_state[key] = None

if "extraction_done" not in st.session_state:
    st.session_state.extraction_done = False
if "l2_done" not in st.session_state:
    st.session_state.l2_done = False

# ── header ────────────────────────────────────────────────────────────────────
st.markdown("## 📦 MDMPrefill")
st.markdown("Extract packing and UOM fields from R&D spec documents into governed MDM fields.")
st.divider()

# ── section 1: input type ─────────────────────────────────────────────────────
st.markdown('<div class="section-title">1 — Input type</div>', unsafe_allow_html=True)
input_type = st.selectbox(
    "How are you providing the spec?",
    options=["Text (manual / system paste)", "PDF — pick from eval set", "PDF — upload your own"],
    index=0,
    label_visibility="collapsed",
)

# ── section 2: document template ─────────────────────────────────────────────
is_pdf = input_type.startswith("PDF")
st.markdown('<div class="section-title">2 — Document template</div>', unsafe_allow_html=True)

template_options = {
    "Template 1 - GEN": "GEN",
    "Template 2 - SEA": "SEA",
    "Whole page (no crop)": None,
}
template_label = st.selectbox(
    "Document layout template",
    options=list(template_options.keys()),
    disabled=not is_pdf,
    help="Only applies to PDF input.",
)
template_id = template_options[template_label]

if not is_pdf:
    st.caption("Template selection only applies to PDF input.")
else:
    st.caption(f"Crop region: **{template_id}**" if template_id else "Sending full page — no crop.")

# ── section 3: spec input ─────────────────────────────────────────────────────
st.markdown('<div class="section-title">3 — Spec input</div>', unsafe_allow_html=True)

input_text = None
input_pdf_path = None
uploaded_file = None
selected_name = None

if input_type == "Text (manual / system paste)":
    input_text = st.text_area(
        "Paste packing spec text",
        placeholder="e.g.  1 KG/BAG x 12 BAGS/BOX x 6 BOX/CAR",
        height=120,
    )
    if input_text and input_text.strip():
        st.markdown('✓ Text ready <span class="badge-ready">ready</span>', unsafe_allow_html=True)
    else:
        st.markdown('Waiting for input <span class="badge-pending">pending</span>', unsafe_allow_html=True)

elif input_type == "PDF — pick from eval set":
    eval_dir = Path("eval/test")
    pdf_names = sorted(p.name for p in eval_dir.glob("*.pdf")) if eval_dir.exists() else \
                [f"eval_doc_{str(i).zfill(3)}.pdf" for i in range(1, 41)]
    selected_name = st.selectbox("Select eval document", options=pdf_names)
    input_pdf_path = str(Path("eval/test") / selected_name)
    st.markdown(f'<div class="preview-box">📄 {input_pdf_path}</div>', unsafe_allow_html=True)
    st.markdown('<span class="badge-ready">ready</span>', unsafe_allow_html=True)
    if Path(input_pdf_path).exists():
        show_pdf_preview(input_pdf_path, template_id)
    else:
        st.caption("_(PDF preview unavailable — file not found)_")

elif input_type == "PDF — upload your own":
    uploaded_file = st.file_uploader("Upload a spec PDF", type=["pdf"])
    if uploaded_file:
        tmp_dir = Path("tmp_uploads")
        tmp_dir.mkdir(exist_ok=True)
        tmp_path = tmp_dir / uploaded_file.name
        tmp_path.write_bytes(uploaded_file.read())
        input_pdf_path = str(tmp_path)
        st.markdown(
            f'<div class="preview-box">📄 {uploaded_file.name} ({uploaded_file.size / 1024:.1f} KB)</div>',
            unsafe_allow_html=True,
        )
        st.markdown('<span class="badge-ready">ready</span>', unsafe_allow_html=True)
        show_pdf_preview(input_pdf_path, template_id)
    else:
        st.markdown('No file uploaded yet <span class="badge-pending">pending</span>', unsafe_allow_html=True)

# ── section 4: thread id ──────────────────────────────────────────────────────
st.markdown('<div class="section-title">4 — Run ID</div>', unsafe_allow_html=True)
thread_id = st.text_input("Thread ID", value="test-001",
                           help="Unique identifier for this run.")

# ── ready check ───────────────────────────────────────────────────────────────
if input_type == "Text (manual / system paste)":
    ready = bool(input_text and input_text.strip())
elif input_type == "PDF — pick from eval set":
    ready = bool(input_pdf_path)
else:
    ready = bool(input_pdf_path)

# ── summary ───────────────────────────────────────────────────────────────────
st.markdown("""
    <style>
    [data-testid="stMetricValue"] {
        font-size: 1rem;
    }
    </style>
""", unsafe_allow_html=True)

st.divider()
st.markdown("#### Run configuration")
if input_type == "Text (manual / system paste)":
    c1, c2 = st.columns(2)
    c1.metric("Input type", "Text")
    c2.metric("Template", "N/A")
elif input_type == "PDF — pick from eval set":
    c1, c2, c3 = st.columns(3)
    c1.metric("Input type", "PDF (eval set)")
    c2.metric("File", selected_name or "—")
    c3.metric("Template", template_id or "Whole page")
else:
    c1, c2, c3 = st.columns(3)
    c1.metric("Input type", "PDF (upload)")
    c2.metric("File", uploaded_file.name if uploaded_file else "—")
    c3.metric("Template", template_id or "Whole page")
st.markdown(f"**Thread ID:** `{thread_id}`")

# ── extract button ────────────────────────────────────────────────────────────
st.divider()
extract_btn = st.button(
    "Extract fields →",
    disabled=not ready,
    type="primary",
    use_container_width=True,
)

# ── extraction + streaming ────────────────────────────────────────────────────
if extract_btn and ready:
    from graph.graph import build_mdm_graph

    initial_state = {
        "input_text": input_text or "",
        "input_pdf_path": input_pdf_path,
        "template_id": template_id,
    }

    graph = build_mdm_graph()
    config = {"configurable": {"thread_id": thread_id}}

    st.markdown("#### Extraction pipeline")
    status_box = st.empty()

    with st.spinner("Running pipeline…"):
        for update in graph.stream(initial_state, config, stream_mode="updates"):
            for node_name, changes in update.items():
                if not isinstance(changes, dict):
                    continue
                status_box.info(f"✓ `{node_name}` completed")

                if node_name == "vlm_extract" or node_name == "extract":
                    st.session_state.extracted_fields = changes.get("extracted_fields", {})
                if node_name == "enrich":
                    st.session_state.enriched_fields = changes.get("enriched_fields", {})
                    st.session_state.completeness_score = changes.get("completeness_score")
                    st.session_state.needs_priority_review = changes.get("needs_priority_review")
                if node_name == "sanity":
                    st.session_state.sanity_flags = changes.get("sanity_flags", [])

    status_box.success("Pipeline paused — awaiting L2 review.")
    st.session_state.extraction_done = True
    st.session_state.graph = graph
    st.session_state.graph_config = config
    st.session_state.initial_state = initial_state
    st.session_state.l2_done = False

# ── extraction results ────────────────────────────────────────────────────────
if st.session_state.extraction_done and st.session_state.extracted_fields:
    st.divider()
    st.markdown("#### Extraction results")

    raw_text = st.session_state.extracted_fields.get("raw_text_seen")
    if raw_text:
        st.caption(f"**Raw text seen by model:** `{raw_text}`")

    col_l1a, col_enrich = st.columns(2)

    with col_l1a:
        st.markdown("**L1a — Extracted fields**")
        extracted = st.session_state.extracted_fields or {}
        st.table(fields_to_table(extracted, "Field", "Extracted"))

    with col_enrich:
        st.markdown("**Enriched fields**")
        enriched = st.session_state.enriched_fields or {}
        st.table(fields_to_table(enriched, "Field", "Enriched"))

    score = st.session_state.completeness_score
    flags = st.session_state.sanity_flags or []
    priority = st.session_state.get("needs_priority_review")

    st.markdown(f"**Completeness:** `{score:.0%}`" if score is not None else "**Completeness:** —")

    if flags:
        st.warning("⚠️ Sanity flags: " + ", ".join(flags))
    else:
        st.success("✅ No sanity flags.")

    if priority:
        st.warning("⚠️ Priority review flagged — completeness below threshold.")
    elif priority is False:
        st.success("✅ Completeness within threshold — no priority flag.")

# ── L2 review panel ───────────────────────────────────────────────────────────
if st.session_state.extraction_done and not st.session_state.l2_done:
    st.divider()
    st.markdown("#### L2 Review")

    reviewer_id = st.text_input("Reviewer name", placeholder="e.g. puri")

    st.markdown("**Manual field overrides** _(optional — leave blank to keep extracted values)_")
    enriched = st.session_state.enriched_fields or {}

    override_fields = {k: v for k, v in enriched.items()
                    if k not in {"extractable", "raw_text_seen"}}
    overrides = {}
    for field, current_val in override_fields.items():
        new_val = st.text_input(
            f"{field}",
            value="" if current_val is None else str(current_val),
            key=f"override_{field}",
        )
        if new_val.strip() and new_val.strip() != str(current_val):
            try:
                overrides[field] = int(new_val)
            except ValueError:
                try:
                    overrides[field] = float(new_val)
                except ValueError:
                    overrides[field] = new_val

    st.markdown("---")
    col_approve, col_reject = st.columns(2)

    with col_approve:
        approve_btn = st.button("✅ Approve", type="primary", use_container_width=True,
                                disabled=not reviewer_id)
    with col_reject:
        reject_btn = st.button("❌ Reject", use_container_width=True,
                               disabled=not reviewer_id)

    if approve_btn or reject_btn:
        l2_approved = bool(approve_btn)
        graph = st.session_state.graph
        config = st.session_state.graph_config

        graph.update_state(config, {
            "reviewer_id": reviewer_id,
            "l2_approved": l2_approved,
            "manual_overrides": overrides,
        })

        with st.spinner("Finalising…"):
            for update in graph.stream(None, config, stream_mode="updates"):
                for node_name, changes in update.items():
                    if not isinstance(changes, dict):
                        continue
                    if node_name == "l2_review":
                        st.session_state.final_fields = changes.get("final_fields", {})
                        st.session_state.audit_trail = changes.get("audit_trail", {})

        log_path = save_result(
            thread_id=thread_id,
            initial_state=st.session_state.initial_state,
            extracted=st.session_state.extracted_fields,
            enriched=st.session_state.enriched_fields,
            sanity_flags=st.session_state.sanity_flags,
            completeness=st.session_state.completeness_score,
            reviewer_id=reviewer_id,
            l2_approved=l2_approved,
            overrides=overrides,
            final_fields=st.session_state.final_fields,
            audit_trail=st.session_state.audit_trail,
        )

        st.session_state.l2_done = True
        st.session_state.l2_approved = l2_approved
        st.session_state.log_path = log_path
        st.rerun()

# ── final result ──────────────────────────────────────────────────────────────
if st.session_state.l2_done:
    st.divider()
    approved = st.session_state.get("l2_approved")

    if approved:
        st.success("✅ Record approved and committed.")
    else:
        st.error("❌ Record rejected.")

    if st.session_state.final_fields:
        st.markdown("#### Final committed fields")
        st.table(fields_to_table(st.session_state.final_fields, "Field", "Final value"))

    if st.session_state.audit_trail:
        st.markdown("#### Audit trail")
        st.json(st.session_state.audit_trail)

    log_path = st.session_state.get("log_path")
    if log_path:
        st.caption(f"📁 Result saved to `{log_path}`")

    if st.button("🔄 Start new run", use_container_width=True):
        for key in ["extraction_done", "graph", "graph_config", "initial_state",
                    "extracted_fields", "enriched_fields", "sanity_flags",
                    "completeness_score", "l2_done", "final_fields",
                    "audit_trail", "l2_approved", "log_path"]:
            st.session_state[key] = None
        st.rerun()
