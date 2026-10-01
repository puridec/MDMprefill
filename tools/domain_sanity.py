# tools/domain_sanity.py
#
# Runtime plausibility checks - the first point in the pipeline that
# looks at whether VALUES make sense, not just whether they're present
# (completeness) or well-formed JSON (extract's retry). Needs no ground
# truth, same as completeness - purely a function of the enriched record
# itself. A separate signal from completeness, never blended into it or
# into needs_priority_review - both just ride alongside to L2 for the
# reviewer to weigh together.

from config.prompt_config import load_fields

COUNT_FIELDS = ["item_qty", "item_per_inner_qty", "inner_per_master_qty"]
WEIGHT_PAIRS = [
    ("item_weight_min", "item_weight_max"),
    ("inner_weight_min", "inner_weight_max"),
    ("master_weight_min", "master_weight_max"),
]


def _allowed_values_by_field() -> dict:
    """Pulls allowed_values straight from fields.yaml - single source of
    truth, same list the prompt itself is built from. No duplication."""
    fields = load_fields()
    return {
        name: spec["extraction"]["allowed_values"]
        for name, spec in fields.items()
        if "allowed_values" in spec.get("extraction", {})
    }


def check_domain_sanity(enriched: dict) -> list:
    """Returns a list of flag strings - empty list means nothing to
    report. ERR_ prefix = something is actually wrong (broken math,
    nonsensical count). WARN_ prefix = unrecognized but not necessarily
    wrong (unmapped UOM vocabulary - matches the earlier decision that
    an ungoverned unit term shouldn't abort a record)."""
    if enriched.get("extractable") is False:
        return []  # nothing to sanity-check on an abstained record

    flags = []

    # --- count positivity: must be a whole number >= 1, if present ---
    for field in COUNT_FIELDS:
        value = enriched.get(field)
        if value is not None and (value < 1 or value != int(value)):
            flags.append(f"ERR_INVALID_COUNT:{field}={value}")

    # --- UOM enum: must match fields.yaml's allowed_values, if present ---
    allowed = _allowed_values_by_field()
    for field, values in allowed.items():
        value = enriched.get(field)
        if value is not None and value not in values:
            flags.append(f"WARN_UNGOVERNED_VALUE:{field}={value}")

    # --- min <= max, per weight level, if both present ---
    for min_field, max_field in WEIGHT_PAIRS:
        min_val = enriched.get(min_field)
        max_val = enriched.get(max_field)
        if min_val is not None and max_val is not None and min_val > max_val:
            flags.append(f"ERR_MIN_GT_MAX:{min_field}={min_val} > {max_field}={max_val}")

    # --- hierarchy: item <= inner <= master (defensive assert - should
    # basically never fire, since Enrich's own formulas guarantee this
    # by construction; a hit here means enrich.py itself broke) ---
    item_w = enriched.get("item_weight_min")
    inner_w = enriched.get("inner_weight_min")
    master_w = enriched.get("master_weight_min")
    if item_w is not None and inner_w is not None and item_w > inner_w:
        flags.append(f"ERR_HIERARCHY_VIOLATION:item_weight={item_w} > inner_weight={inner_w}")
    if inner_w is not None and master_w is not None and inner_w > master_w:
        flags.append(f"ERR_HIERARCHY_VIOLATION:inner_weight={inner_w} > master_weight={master_w}")

    return flags