# MDMPrefill — Mock Document Generation Spec

This is the finalized, approved template for generating printable R&D spec
documents used as eval-set test fixtures. Two real template families,
alternated by row for variety.

---

## What's genuine vs. synthetic (the core rule)

**Only Section 3's "Packing Detail" field is real input to the pipeline.**
Everything else on the page is cosmetic filler — confirmed to have zero
dependency on extraction correctness, present only so the document looks
complete and realistic for OCR to correctly ignore.

| Field | Source |
|---|---|
| Packing Detail text | `input_text` from the eval set, inserted **verbatim** |
| Net Wt. | **Computed** from ground truth (`master_weight`, or `inner_weight` if no master level) — never independently typed |
| Product name, customer, dates, spec numbers, system codes | Cosmetic, drawn from a rotating name pool, no repeats within a batch |

---

## Template 1 — Poultry FORM-GEN (based on real "FORM GEN-101" reference)

```
Form Ref: FORM GEN-{id}
REQUEST FOR SPEC NO. AND SYSTEM CODE — NEW PRODUCT
Poultry Product Research & Development Division

SECTION 1 — Completed by Sales / Customer Coordination, sent to Product
Development and (copy) Plant Planning
  [table] Attn (Product Dev.) | Plant
  [table] From (Sales/CPFNW) | Customer Name
  [table] Product Name (spans, product name UPPERCASE) | Country
  [table] Shipment Date | Ref. Spec/Sample No.
  [table] Plant Ref. No.
  Other Requirements: [ ] HALAL [X] NON-HALAL [ ] OTHER _______
  Sales Channel: [ ] Convenience [ ] Hypermarket [ ] Cash & Carry
    [X] Food Service [ ] Modern Trade [X] OEM [ ] Other
  Remark: _________________________________________

SECTION 2 — Completed by Product Development, sent to R&D Center
  [THICK BORDERED BOX — normal table-line weight, not extra-heavy]
  containing:
    - Heading: "SECTION 2 — Completed by Product Development, sent to
      R&D Center" (bold)
    - [inner bordered table] From (Plant Product Dev.) + Date
    - [inner bordered table] Raw Meat Used (product-specific, e.g.
      "F-1504: Boneless chicken breast, vacuum sealed portion")
    - "PRODUCTION PROCESS (mark CORE TEMP. at the fully-cooked step)"
    - Process flow line, arrow-separated (➤), PRODUCT-SPECIFIC steps —
      not generic. E.g. vacuum-packed breast → "Portioning ➤ Vacuum
      Sealing ➤ Weighing ➤ Metal Detect ➤ Chilling"; skewer product →
      "Skewering ➤ Marinating ➤ Grilling ➤ Chilling ➤ Packing"

SECTION 3 — PACKING DETAIL (CONFIRMED)
  [table] Packing Detail: {input_text verbatim} | Net Wt.: {computed} KG

  Remark: ___________________________________

SECTION 4 — Completed by R&D Center, sent to Product Dev., Planning,
and Documentation
  Date: {date}     From (RD Center): {name}
  [table] PRODUCT NAME | SPEC NO. | SYSTEM CODE (FG) | SYSTEM CODE (WIP)
    | NET WT.
  — NOTE: the "PACKING DETAIL" row that appears in the original real
    reference form is DELETED here — redundant with Section 3, removed
    per explicit request.

  Copy to: Product Development, Plant Planning, Sales/Customer
  Coordination, Documentation Team
  Revision 21 — Effective 01 Jan 2026
```

**Key layout decisions locked in during review:**
- Section 2 gets its own bordered box, same line-weight as the rest of the
  document (an earlier thicker/darker border was tried and reverted —
  "remove the darken border of section 2").
- Process flow uses real arrow glyphs (➤), not plain text "->".
- Section 4's duplicate Packing Detail row is removed (kept only NET WT.).
- No debug/tracking tag in the corner — the document's own **Ref.
  Spec/Sample No.** field is the link back to the eval row, not an
  artificial label.

---

## Template 2 — Pork / Meridian style (based on real Meridian reference)

```
Meridian Foods Manufacturing Co., Ltd.
Product Manufacturing Standard Specification

[table] Product Name | Customer
[table] Product Type ("Fresh Pork Cuts") | Product Code
[table] Spec No. | Rev No. / Issue

Product Category: [X/ ] Chilled  [X/ ] Frozen
Packaging Type: [ ] Bulk [X] Carton [ ] Basket

[table, 3 columns]
  Production Steps (product-specific, numbered, e.g. "1. Cut shoulder to
    target weight 2. Vacuum pack, 1 piece per bag 3. Blast freeze 4. Box
    for shipment")
  | Specification / Notes ("No signs of spoilage. No foreign material.
    Delivered at 0-4°C.")
  | Packaging Detail ({input_text verbatim} + "Net weight: {computed} kg")

Controlled document — internal use only.
```

**Key decisions:**
- Cosmetic fields (product name, customer, category checkboxes) must
  match the animal type implied by the template — a mismatch (e.g. a pork
  document reading "Fresh Poultry Cuts") was caught and fixed during
  review; templates and product identity must stay cohesive.
- Production steps are written per-product, not a fixed generic string —
  same requirement as Template 1.

---

## Assignment rules

- **Alternate templates** (poultry / pork) across consecutive eval rows
  for visual variety — not tied to the row's actual animal content,
  since animal type was confirmed cosmetic-only (doesn't affect scoring).
- **No repeated names, dates, customers, or spec/system codes** across
  the full batch of generated documents — each pulled from a rotating
  pool sized to the batch (≥15 unique entries per pool for a 15-19
  document batch).
- **Every "Packing Detail" cell gets the exact `input_text` string**,
  character for character — no paraphrasing, no reformatting.
- **Net Wt. is always computed**, never manually typed, to avoid ever
  creating a document whose two weight mentions disagree.

---

## Still outstanding (not yet part of the approved template)

**No document currently has a printed border for deskew purposes.** The
OpenCV corner-detection pipeline (`tools/deskew.py`) needs a bold,
high-contrast rectangle printed on the page to reliably find in a
photograph — confirmed necessary after a real test photo showed the
page's own edge (white paper on a light background) wasn't detectable,
and the algorithm instead locked onto Section 2's internal box by
mistake. This border has not yet been added to either template's
generation code.

---

## Reference: known real documents this spec is based on

- `FORM GEN-101` — poultry-division New Product Request form (real
  company reference, redacted)
- Meridian Foods pork spec sheet (real company reference, redacted)
- `test5.png` — a third real bilingual reference (Thai/English,
  brand-code fields, HALAL checkboxes) — informed field-naming
  conventions but was NOT used as the template basis after review
  (its specific fields, like Thai brand-code cells, were found to be
  a different form variant and excluded to avoid mixing two real
  templates' fields into one synthetic document).
