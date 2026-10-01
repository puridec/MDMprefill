# tools/completeness.py
#
# Measures how complete an extraction is, normalized by the packaging
# depth the record itself implies - NOT a fixed field count. A correctly-
# filled 2-level document should score 1.0 even though it has 5 fewer
# filled fields than a 3-level document; comparing raw filled-field counts
# across different depths would be unfair.
#
# This is a SEPARATE signal from L1a/L1b correctness. Completeness does
# not know whether a value is right - only whether the fields the record's
# own structure implies are missing were actually attempted. It exists to
# flag records that likely need closer human review, on top of the L2
# review every record already receives regardless.

COMPLETENESS_THRESHOLD = 0.8  # below this, flag for priority human review


def get_required_fields(extracted: dict) -> set:
    """Determines which fields SHOULD be filled, based on the packaging
    depth the extraction itself implies - inferred from whether any item-
    level field has a value, not from an external oracle (none exists at
    inference time)."""
    required = {"inner_container_um"}

    has_item_level = any(
        extracted.get(f) is not None
        for f in ("item_qty", "item_unit", "item_weight_min", "item_weight_max")
    )

    if has_item_level:
        # 3-level: item fields + item_per_inner_qty are all expected
        required |= {"item_qty", "item_unit", "item_weight_min", "item_weight_max", "item_per_inner_qty"}
    else:
        # 2-level: inner_weight is the LLM's direct statement, expected here
        required |= {"inner_weight_min", "inner_weight_max"}

    has_master_level = (
        extracted.get("inner_per_master_qty") is not None
        or extracted.get("master_container_um") is not None
    )
    if has_master_level:
        required |= {"inner_per_master_qty", "master_container_um"}

    return required


def compute_completeness(extracted: dict) -> float:
    """Fraction of the record's OWN implied required fields that were
    actually filled. Returns 0.0 for an abstained record (nothing to
    measure completeness of)."""
    if extracted.get("extractable") is False:
        return 0.0

    required = get_required_fields(extracted)
    if not required:
        return 1.0  # no fields expected at all - vacuously complete

    filled = sum(1 for f in required if extracted.get(f) is not None)
    return filled / len(required)


def needs_priority_review(extracted: dict) -> bool:
    """True if completeness falls below the threshold - a signal for
    which records deserve closer human scrutiny at L2, not a replacement
    for L2 itself (every record still goes through L2 regardless)."""
    return compute_completeness(extracted) < COMPLETENESS_THRESHOLD