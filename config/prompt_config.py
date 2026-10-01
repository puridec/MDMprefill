# config/prompt_config.py
#
# Reads fields.yaml at prompt-build time so allowed_values in the prompt
# can never drift out of sync with the field dictionary. Do not hardcode
# a copy of any value list here.

import re
import yaml
from pathlib import Path

CONFIG_DIR = Path(__file__).parent
FIELDS_PATH = CONFIG_DIR / "resources" / "fields.yaml"
UNIT_TRANSLATION_PATH = CONFIG_DIR / "resources" / "unit_translation.yaml"


def looks_like_total_for_group(input_text: str) -> bool:
    """Heuristic: per_unit style states weight immediately before a slash +
    container ('0.5KG/BAG'). total_for_group style states weight directly
    before an 'X' + count with no slash ('1.33KG X 8 BAGS'). This is a
    detection heuristic on raw text shape, not a semantic judgment - used
    only to decide whether to show the total_for_group worked example,
    so a wrong guess here costs nothing except an unused/unhelpful
    example, never a wrong extraction on its own."""
    has_slash_after_weight = bool(re.search(r"\d+(\.\d+)?\s*KG\s*/", input_text, re.IGNORECASE))
    has_x_after_weight = bool(re.search(r"\d+(\.\d+)?\s*KG\s*[Xx]\s*\d+", input_text))
    return has_x_after_weight and not has_slash_after_weight

SYSTEM_ROLE = """You are a packaging data extraction expert specializing in Thai and English product specifications.
You understand packaging hierarchies: item (smallest unit) -> inner (intermediate container) -> master (shipping container)."""

TASK_DESCRIPTION = """Extract structured packaging information from packing text.
The text may be in Thai, English, or mixed languages.
Packaging follows a hierarchy: individual items are packed into inner containers, which are packed into master containers.
Not every document has all three levels - some have only inner+master (2-level), some have item+inner+master (3-level)."""

CRITICAL_INSTRUCTIONS_STATIC = [
    "master_container_um if have any master level then it should be CS even if input says box or boxes which imply BOX"
    "Leave item fields EMPTY (null) if the product is sold in bulk with no individual item breakdown",
    "Leave item fields EMPTY if packing text shows only container->container (e.g., '2kg/bag x 10 bags/carton' has no item breakdown)",
    "All weights MUST be in kilograms (KG). Convert grams by dividing by 1000 (e.g., 400g -> 0.4 KG)",
    "For Thai text 'ถุงละ X ชิ้น', this means 'X items per bag' (reversed word order from English)",
    "For Thai text 'บรรจุ X ต่อ Y', this means 'packed X per Y'",
    "For weight ranges, extract min and max separately, converting to KG if needed - e.g. '75-85g/pcs' -> item_weight_min=0.075, item_weight_max=0.085 (grams converted to KG); '100-120kg' -> item_weight_min=100, item_weight_max=120 (already KG, just split min/max directly, no conversion needed)",
    "For weight ranges, if only one value given (e.g., '2kg/bag'), use same value for both min and max",
    "For parenthetical counts like '20KG(2HEAD)/BAG', calculate item weight by division: 20kg / 2 = 10kg per head",
    "For additions like '40G(+10G SAUCE)/BAG', extract only the base weight (40g), ignore additions",
    "Animal part names (wing, leg, breast, thigh, etc.) describe WHAT the item is, not its unit - never put them in item_unit. A whole bird or whole cut counted as one unit uses EA; a portioned/cut piece uses PC.",
    "If text shows 'X/bag' with no item breakdown, leave item fields null - the bag IS the selling unit (2-level document)",
    "MECHANICAL depth test - count how many container levels sit ABOVE the innermost stated unit. (a) TWO containers above it (innermost -> container -> container): this is a 3-level document. item=innermost, inner=the first container above it, master=the outermost container. (b) Exactly ONE container above the innermost unit: check what kind of word the innermost unit itself is. If it is a genuine item-type unit (PC, EA, STK, EGG - a countable individual thing), this is a 2-level ITEM+INNER document: item=innermost, inner=the one container above it, has_master=false, ALL master fields null. If instead the innermost unit is ITSELF a container-type word (BAG, SAC, TRA, PAC, SET, TNK, BOX), this is a 2-level INNER+MASTER document: ALL item fields null, inner_container_um=the innermost container word, master_container_um=the one container above it.",
    "Depth test example, case (a) 3-level: '0.4KG/BAG x 6 BAGS/BOX x 5 BOX/CAR' - BAG has two containers above it (BOX, then CAR/CS). item_unit=BAG, inner_container_um=BOX, master_container_um=CS.",
    "Depth test example, case (b-item) 2-level ITEM+INNER: '6 sticks per sachet, 120g per sachet' - STK is a genuine item unit with exactly one container (the sachet/BAG) above it, and no further container is mentioned anywhere. item_unit=STK, inner_container_um=BAG, has_master=false, master_container_um and master_weight_min/max ALL null.",
    "Depth test example, case (b-container) 2-level INNER+MASTER: '2kg/bag x 10 bags/carton' - BAG is itself a container word with exactly one container (carton) above it. ALL item fields null, inner_container_um=BAG, master_container_um=CS.",
    "has_master should be TRUE only if text mentions a master/shipping container - these all map to the single code CS, there is no separate BOX or CAR code",
    "extractable=false means NOTHING useful can be determined from the text at all (e.g. no numbers, no containers mentioned, pure instructions like 'store in a cool place'). If SOME fields can be determined even though others cannot (e.g. counts are stated but weight is missing, or vice versa), set extractable=true and extract every field you CAN determine, leaving ONLY the genuinely undeterminable fields as null. Do NOT set extractable=false just because one or two fields are missing - partial extraction with some null fields is the CORRECT and EXPECTED behavior whenever any real information is present.",
    "WORKED partial-extraction EXAMPLE: '7 ชิ้น/ถุง 4 ถุงต่อกล่อง' (7 pieces/bag, 4 bags/box) states clear counts but no weight anywhere. This is extractable=true with item_per_inner_qty=7, inner_container_um=BAG, inner_per_master_qty=4, master_container_um=CS - and item_weight_min/max, item_qty, item_unit left null (weight genuinely not stated). Do NOT return extractable=false here - the counts ARE real, usable information.",
    "item_qty is almost always 1 (it describes ONE unit of item_unit, e.g. one stick weighs item_weight_min kg). The COUNT of items packed into the inner container goes in item_per_inner_qty, never in item_qty. Example: '6 sticks per sachet, 120g per sachet' means item_qty=1, item_unit=STK, item_weight=0.02 (120g / 6 sticks), item_per_inner_qty=6.",
    "When a weight is stated for a group (e.g. '100g per sachet' containing multiple pieces/sticks), divide by the count to get the correct item_weight - do not use the group weight as the item_weight directly.",
    "WORKED 3-LEVEL EXAMPLE: '0.4KG/BAG x 6 BAGS/BOX x 5 BOX/CAR' describes THREE nested containers (bag -> box -> carton), because the bag itself gets grouped into a box, and the box gets grouped into a carton. Correct extraction: item_qty=1, item_unit=BAG, item_weight_min=0.4, item_weight_max=0.4, inner_container_um=BOX, item_per_inner_qty=6, inner_weight_min=2.4, inner_weight_max=2.4, inner_per_master_qty=5, master_container_um=CS. Note that item_unit is BAG here even though BAG is usually a container word - it is correct because a further container (BOX) exists above it. Do NOT extract this as a 2-level document with inner_container_um=BAG and item fields null - that would be treating the box as if it does not exist.",
    "EXCEPTION to the 'leave item fields null' rule: if the container holds exactly ONE whole, intact animal or carcass (e.g. a whole chicken, a whole carcass, a whole bird - not a cut or portion of one) rather than a loose/generic quantity of product, extract item_qty=1 and item_unit=EA even though no explicit count number appears in the text. item_weight_min/max in this case equals the same weight stated for the container, since the single item IS the container's contents. ALSO set item_per_inner_qty=1 in this case - the one item fills the one inner container, so this count field must be explicitly 1, never left null, since an item level does genuinely exist here.",
    "IMPORTANT: a stated WEIGHT RANGE (e.g. '200-220g/pcs') does NOT by itself mean EA - it usually means item_unit=PC (a cut, portion, or piece of an animal, like a pork leg cut or chicken thigh piece), NOT a whole animal. Only use EA when the text describes a genuinely WHOLE, uncut animal or carcass. A weighted/portioned cut - even with a wide range, even packed loose in bulk - is still PC, never EA. When uncertain whether something is a whole animal or a cut, look for words indicating portioning (cut, leg, thigh, breast, piece, pcs) vs. wholeness (whole, carcass, whole bird).",
    "WORKED single-bulk-unit EXAMPLE: 'ขนาด 100-120kg บรรจุถุงใบใหญ่' (100-120kg packed in a large bag) describing a whole carcass - this is ONE discrete unit (the carcass), not a generic bulk quantity. Correct extraction: item_qty=1, item_unit=EA, item_weight_min=100, item_weight_max=120, item_per_inner_qty=1, inner_container_um=BAG, inner_weight_min=100, inner_weight_max=120 (same numbers as item, since the one item fills the one bag - item_per_inner_qty=1 is required here, not null). Contrast this with a generic bulk quantity such as '2.5 kg/sack x 8 sacks/pallet', where the bag/sack holds loose product measured only by weight, not one discrete named object - that case correctly leaves ALL item fields (including item_per_inner_qty) null.",
    "item_weight_basis: classify whether the stated weight is per_unit (already the weight of ONE item, e.g. '0.5KG/BAG' - the 0.5 is one bag's weight) or total_for_group (the weight covers ALL item_per_inner_qty units combined, e.g. '1.33KG X 8 BAGS' - the 1.33 is the weight of all 8 bags together, not one bag). Extract item_weight_min/max as the RAW number exactly as it appears in the text either way - do NOT divide it yourself. The distinguishing signal: '[weight]/[unit] x [N] [unit]s' (weight stated per single unit, followed by 'x') is per_unit. '[weight] X [N] [unit]s' with no '/' directly after the weight, where the weight comes first and the count follows, is usually total_for_group.",
    "total_for_group EXAMPLE: '3.6KGX4BAGSX1OUTERBAG/CASE' - the 3.6kg is stated BEFORE '4 BAGS', with no per-bag division shown, meaning 3.6kg is the combined weight of all 4 bags. Correct extraction: item_weight_min=3.6, item_weight_max=3.6, item_weight_basis=total_for_group, item_per_inner_qty=4, inner_container_um=BAG, inner_per_master_qty=1, master_container_um=CS - the '1OUTERBAG/CASE' at the end means one inner-level unit fills one case directly. Leave the actual per-bag division to downstream processing - your job is only to correctly identify and report item_weight_basis and the counts.",
    #"total_for_group PARENTHETICAL EXAMPLE: '800G(40STICK)X1BAGX10INN CARTON' - the 800g is stated BEFORE '(40STICK)', meaning 800g is the combined weight of all 40 sticks in the bag, NOT one stick's weight. Correct extraction: item_weight_min=0.8, item_weight_max=0.8 (convert 800g to KG), item_weight_basis=total_for_group, item_per_inner_qty=40, item_unit=STK, inner_container_um=BAG, inner_per_master_qty=10, master_container_um=CS. Do NOT divide 0.8 by 40 - report the raw converted total and leave division to downstream processing.",
]

OUTPUT_FORMAT_INSTRUCTIONS = """OUTPUT FORMAT:
Return ONLY a valid JSON object with the requested fields.
Use null (not empty strings) for missing values.
Do not include any explanation, preamble, or markdown code fences.
Ensure all field names exactly match the requested fields."""

EXAMPLES_HEADER = """EXAMPLES OF SIMILAR PACKING TEXT:
Study these examples to understand the extraction pattern."""

EXTRACTION_HEADER = "NOW EXTRACT FROM THIS INPUT:"


def load_fields() -> dict:
    with open(FIELDS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["fields"]


def build_unit_translation_reference() -> str:
    """Formats unit_translation.yaml into a compact lookup table for the
    prompt - so the model has the real Thai/English -> code mapping as
    a given fact, rather than relying on its own general knowledge of
    Thai vocabulary (which may not cover abbreviations or be reliable)."""
    with open(UNIT_TRANSLATION_PATH, encoding="utf-8") as f:
        entries = yaml.safe_load(f)

    lines = []
    for entry in entries:
        code = entry["mdm_unit_code"]
        th = entry.get("mdm_unit_text", {}).get("th", [])
        en = entry.get("mdm_unit_text", {}).get("en", [])
        variants = ", ".join(th + en)
        if variants:
            lines.append(f"- {code}: {variants}")
    return "\n".join(lines)


def get_allowed_values(field_name: str) -> list:
    fields = load_fields()
    field = fields.get(field_name, {})
    return field.get("extraction", {}).get("allowed_values", [])


def build_critical_instructions() -> list:
    instructions = list(CRITICAL_INSTRUCTIONS_STATIC)

    item_unit_values = get_allowed_values("item_unit")
    if item_unit_values:
        instructions.append(f"item_unit must be one of: {', '.join(item_unit_values)}")

    inner_values = get_allowed_values("inner_container_um")
    if inner_values:
        instructions.append(f"inner_container_um must be one of: {', '.join(inner_values)}")

    master_values = get_allowed_values("master_container_um")
    if master_values:
        instructions.append(
            f"master_container_um must be one of: {', '.join(master_values)} "
            f"(this is intentionally a single value)"
        )

    return instructions


def build_field_schema() -> list:
    """List only the fields the LLM is actually responsible for producing
    (primary_tier == 3) - derived fields (master_weight, has_master, etc.)
    are computed by code downstream, never asked of the model."""
    fields = load_fields()
    lines = []
    for name, spec in fields.items():
        if spec.get("extraction", {}).get("primary_tier") == 3:
            lines.append(f"- {name} ({spec['data_type']}): {spec['description']}")
    lines.append('- extractable (boolean): false ONLY if literally nothing useful can be determined from the text. true whenever ANY field is determinable, even if others must be left null - partial extraction is expected and correct.')
    return lines


def build_prompt(input_text: str, examples: str = "") -> str:
    critical = build_critical_instructions()
    if not looks_like_total_for_group(input_text):
        # Only show the total_for_group worked example on inputs that
        # structurally resemble that pattern - keeps per_unit cases
        # (e.g. "0.5KG/BAG x 8 BAGS/BOX") from ever seeing an unrelated
        # example that could bias them toward the wrong convention.
        critical = [line for line in critical if "WORKED total_for_group EXAMPLE" not in line]

    parts = [
        SYSTEM_ROLE,
        "",
        TASK_DESCRIPTION,
        "",
        "FIELDS TO EXTRACT:",
        *build_field_schema(),
        "",
        "UNIT CODE REFERENCE (Thai/English word -> code - use these exact mappings, do not guess):",
        build_unit_translation_reference(),
        "",
        "CRITICAL INSTRUCTIONS:",
        *[f"- {line}" for line in critical],
        "",
        OUTPUT_FORMAT_INSTRUCTIONS,
    ]
    if examples:
        parts += ["", EXAMPLES_HEADER, examples]
    parts += ["", EXTRACTION_HEADER, input_text]
    return "\n".join(parts)



VLM_TASK_HEADER = """You are looking at a photo or scanned document, not typed text.
Read the packaging information directly from the image. The document may be
in Thai, English, or mixed languages, and may be rotated, imperfectly lit,
or lower quality than a clean digital scan."""

VLM_CRITICAL_INSTRUCTIONS = [
    "If a field is genuinely not printed anywhere on the document, leave it null (same as the text-extraction rule) - this is different from a field that IS printed but you cannot read clearly due to image quality (blur, glare, damage). For the second case, ALSO leave it null rather than guessing a plausible-looking value - the visual evidence of degradation is not license to fill in what a document 'probably' says.",
    "raw_text_seen: separately from the structured fields, report the literal packing-detail text you can visually make out on the document, character for character as best you can read it - even if partial or uncertain. This lets a human reviewer cross-check your structured answer against what you actually saw, without reopening the image themselves.",
    "A total_for_group pattern (a weight stated before a count with no per-unit division shown, e.g. a number immediately followed by 'X' and a bag/piece count) works the same way visually as it does in typed text - classify item_weight_basis accordingly, do not divide the number yourself.",
    #"A total_for_group pattern appears in two forms visually: (1) '[WEIGHT] X [N] [UNIT]s' with no per-unit slash — e.g. '3.6KG X 4 BAGS' — means 3.6kg is the combined weight of all 4 bags. (2) '[WEIGHT]([N][UNIT])' parenthetical format — e.g. '990G(33STICK)' — means 990g is the combined weight of all 33 sticks. In BOTH cases: set item_weight_basis=total_for_group, convert the raw weight to KG if needed, report it as-is in item_weight_min/max — do NOT divide it yourself. The division happens downstream.",
]


def build_vlm_prompt(examples: str = "") -> str:
    """VLM prompt builder - parallel to build_prompt() but for the image
    path. Reuses the SAME field schema and unit reference (via
    build_field_schema()/build_unit_translation_reference()) so field
    definitions can never drift between the text and vision paths - only
    the task framing and worked examples differ, since "read a photo"
    and "parse typed text" are genuinely different tasks that can't
    share one set of examples."""
    parts = [
        SYSTEM_ROLE,
        "",
        VLM_TASK_HEADER,
        "",
        "FIELDS TO EXTRACT:",
        *build_field_schema(),
        "- raw_text_seen (string): the literal packing-detail text you can read on the document, as-is",
        "",
        "UNIT CODE REFERENCE (Thai/English word -> code - use these exact mappings, do not guess):",
        build_unit_translation_reference(),
        "",
        "CRITICAL INSTRUCTIONS:",
        *[f"- {line}" for line in CRITICAL_INSTRUCTIONS_STATIC],
        *[f"- {line}" for line in VLM_CRITICAL_INSTRUCTIONS],
        "",
        OUTPUT_FORMAT_INSTRUCTIONS,
    ]
    if examples:
        parts += ["", EXAMPLES_HEADER, examples]
    return "\n".join(parts)


if __name__ == "__main__":
    x = build_prompt(input_text="sdsdsd")
    print(x)