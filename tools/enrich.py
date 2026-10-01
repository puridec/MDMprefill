# tools/enrich.py
#
# Pure deterministic arithmetic - no LLM involved, no API call. The LLM
# only ever states ONE weight number (the smallest level present in the
# document); every weight above that is computed here.
#
# Rule: does an item level exist?
#   Yes (3-level) -> LLM states item_weight only; inner_weight and
#                     master_weight are both computed here.
#   No  (2-level) -> LLM states inner_weight directly (it's the smallest
#                     level that exists); master_weight is computed here.

def compute_derived_weights(extracted: dict) -> dict:
    """Fills in weight fields that are arithmetic derivations, never the
    LLM's job to state directly. Returns a NEW dict - does not mutate
    the original LLM output, so the raw extraction is still available
    separately for L1a checking."""
    result = dict(extracted)

    if extracted.get("extractable") is False:
        return result  # cascade rule - no computation on an abstained record

     # LLM always outputs the per-unit weight (the weight of ONE item).
    # inner_weight is always item_weight x item_per_inner_qty regardless
    # of item_weight_basis - the total_for_group branch was removed because
    # the LLM consistently outputs pre-divided per-unit values, making the
    # branch unreliable and causing L1b failures on correct L1a extractions.
    item_weight_min = extracted.get("item_weight_min")
    item_weight_max = extracted.get("item_weight_max")
    item_per_inner_qty = extracted.get("item_per_inner_qty")

    if item_weight_min is not None and item_per_inner_qty:
        result["inner_weight_min"] = round(item_weight_min * item_per_inner_qty, 2)
        result["inner_weight_max"] = round(item_weight_max * item_per_inner_qty, 2)

    # master_weight = inner_weight x inner_per_master_qty (always
    # computed, never LLM-stated - matches fields.yaml's existing
    # primary_tier: derived setting for this field).
    inner_weight_min = result.get("inner_weight_min")
    inner_weight_max = result.get("inner_weight_max")
    inner_per_master_qty = extracted.get("inner_per_master_qty")

    if inner_weight_min is not None and inner_per_master_qty:
        result["master_weight_min"] = round(inner_weight_min * inner_per_master_qty, 2)
        result["master_weight_max"] = round(inner_weight_max * inner_per_master_qty, 2)

    # is_weighted: whether the packaged unit (inner level) has a genuine
    # min/max range rather than a fixed single value. Computed here, not
    # asked of the LLM - it depends only on inner_weight_min/max, which
    # are themselves either LLM-stated (2-level) or just-computed above
    # (3-level) by the time we reach this line.
    final_inner_min = result.get("inner_weight_min")
    final_inner_max = result.get("inner_weight_max")
    if final_inner_min is not None and final_inner_max is not None:
        result["is_weighted"] = (final_inner_min != final_inner_max)
    else:
        result["is_weighted"] = None  # can't determine without both bounds

    return result