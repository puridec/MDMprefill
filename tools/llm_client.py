# tools/llm_client.py
#
# The actual LLM calls for Stage 3 extraction - both the text path and
# the vision path share one retry/cost-tracking core (_extract_with_retry),
# since "did the response parse as valid JSON" doesn't care which
# modality produced it. Plain functions, no LangGraph, no state dict -
# testable in isolation, same pattern as tools/ocr_engine.py.
#
# PDFs are sent directly to OpenRouter via the "file" content type
# (engine="native" forced explicitly) rather than rendered to an image
# locally first - see _pdf_to_content_part(). This avoids a silent
# fallback to an OCR-based parsing engine on OpenRouter's side, which
# would reintroduce the exact transcribe-then-interpret problem Option B
# was chosen to avoid.

import json
import base64
import time
from pathlib import Path
from openai import OpenAI
import pymupdf

from config.settings import (
    LLM_MODEL, VLM_MODEL, LLM_BASE_URL, LLM_TIMEOUT, LLM_TEMPERATURE,
    OPENROUTER_API_KEY, PRICE_IN, PRICE_OUT, VLM_PRICE_IN, VLM_PRICE_OUT,
    MAX_LLM_RETRIES,
)
from config.prompt_config import build_prompt, build_vlm_prompt
from config.template_regions import TEMPLATE_REGIONS

_client = OpenAI(base_url=LLM_BASE_URL, api_key=OPENROUTER_API_KEY, timeout=LLM_TIMEOUT)


def _extract_usage(response, price_in: float, price_out: float) -> dict:
    """Pulls token counts and $ cost off the raw API response.

    usage.cost is OpenRouter-specific - only present because we ask for it
    via extra_body={"usage": {"include": True}} below. It's the ACTUAL
    billed amount, not an estimate. If it's ever absent (provider/model
    swap that doesn't report it), fall back to price_in/price_out so cost
    tracking degrades to an estimate instead of silently returning None.
    price_in/price_out are passed in rather than imported directly, since
    the text and vision paths use different fallback prices.
    """
    usage = response.usage
    tokens_in = getattr(usage, "prompt_tokens", None)
    tokens_out = getattr(usage, "completion_tokens", None)
    cost_usd = getattr(usage, "cost", None)

    cost_estimated = cost_usd is None
    if cost_estimated and tokens_in is not None and tokens_out is not None:
        cost_usd = round(tokens_in * price_in + tokens_out * price_out, 6)

    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
        "cost_estimated": cost_estimated,  # True = fallback math, not OpenRouter's real figure
    }


def _call_llm(model: str, content, price_in: float, price_out: float, plugins: list = None) -> tuple:
    """One raw API call - no retry logic here, just send and parse.
    `content` is either a plain string (text path) or a list of content
    parts - e.g. [{"type": "text", ...}, {"type": "image_url", ...}] or
    [{"type": "text", ...}, {"type": "file", ...}] (vision path). The
    OpenAI-compatible messages format accepts any of these directly, so
    this function doesn't need to know or care which modality it's
    carrying. `plugins` is only used for the PDF file-content case, to
    force engine="native" rather than leave it to OpenRouter's default.
    Returns (parsed_dict, usage_dict)."""
    t0 = time.time()
    print(f"  [llm] calling {model}...", flush=True)

    extra_body = {
        "usage": {"include": True},
        "reasoning": {"enabled": False},  # this is a structured-extraction
        # task, not a reasoning task - a hidden chain-of-thought trace
        # before the JSON answer adds real cost and latency for zero
        # benefit here. Found via a 1,304-second, 8,724-output-token
        # call that should have taken seconds and ~150 tokens.
    }
    if plugins:
        extra_body["plugins"] = plugins

    response = _client.chat.completions.create(
        model=model,
        temperature=LLM_TEMPERATURE,
        messages=[{"role": "user", "content": content}],
        extra_body=extra_body,
    )

    print(f"  [llm] response received in {time.time()-t0:.1f}s", flush=True)

    usage = _extract_usage(response, price_in, price_out)
    raw = response.choices[0].message.content.strip()

    # Defensive: strip markdown code fences if the model adds them despite
    # instructions not to - cheap safety net, doesn't hurt if unnecessary.
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"error": "invalid_json", "raw_response": raw}
        print(f"  [llm] WARNING: response was not valid JSON", flush=True)

    return parsed, usage


def _build_repair_content(original_content, bad_raw_response: str):
    """Appends a correction notice - works whether original_content is a
    plain string (text path) or a list of content parts (vision path).
    For the list case, only the text part is modified; the image/file
    part is carried through UNCHANGED, so the retry still has access to
    the actual document, not just a description of its own previous bad
    guess. At LLM_TEMPERATURE=0.0 a blind resend of identical content
    would reproduce the identical broken output - showing the model its
    own bad response is what gives the retry any real chance."""
    notice = (
        "\n\nYOUR PREVIOUS RESPONSE WAS NOT VALID JSON:\n"
        + bad_raw_response
        + "\n\nReturn ONLY a valid JSON object this time - no markdown fences, "
          "no explanation, matching the exact field schema above."
    )
    if isinstance(original_content, str):
        return original_content + notice

    new_content = []
    notice_appended = False
    for part in original_content:
        if not notice_appended and part.get("type") == "text":
            part = {**part, "text": part["text"] + notice}
            notice_appended = True
        new_content.append(part)
    return new_content


def _extract_with_retry(model: str, content, price_in: float, price_out: float,
                          max_retries: int, plugins: list = None) -> dict:
    """Shared retry/cost-tracking core for both extract_packing_fields()
    and extract_packing_fields_from_image(). Retries ONLY on invalid
    JSON, up to max_retries times - the one failure signal checkable
    with no ground truth on either modality. Never retries on low
    completeness or any correctness signal: neither is knowable at
    inference time without labels, and re-prompting on a low-completeness
    result risks the model fabricating values just to fill fields that
    were correctly left null. Low completeness is a routing signal for
    L2, handled downstream - never fed back into another LLM call here,
    on either path. plugins passes through unchanged on a retry - the
    repair notice only ever touches the text part."""
    parsed, usage = _call_llm(model, content, price_in, price_out, plugins=plugins)

    attempts = 1
    total_tokens_in = usage["tokens_in"] or 0
    total_tokens_out = usage["tokens_out"] or 0
    total_cost = usage["cost_usd"] or 0
    any_estimated = usage["cost_estimated"]

    while parsed.get("error") == "invalid_json" and attempts <= max_retries:
        print(f"  [llm] retrying with repair prompt (attempt {attempts + 1})...", flush=True)
        repair_content = _build_repair_content(content, parsed["raw_response"])
        parsed, usage = _call_llm(model, repair_content, price_in, price_out, plugins=plugins)
        attempts += 1
        total_tokens_in += usage["tokens_in"] or 0
        total_tokens_out += usage["tokens_out"] or 0
        total_cost += usage["cost_usd"] or 0
        any_estimated = any_estimated or usage["cost_estimated"]

    parsed["_usage"] = {
        "tokens_in": total_tokens_in,
        "tokens_out": total_tokens_out,
        "cost_usd": round(total_cost, 6),
        "cost_estimated": any_estimated,
        "attempts": attempts,
    }
    return parsed


def extract_packing_fields(input_text: str, examples: str = "", max_retries: int = MAX_LLM_RETRIES) -> dict:
    """Text path - manual entry or product-dev-system-sourced text, both
    land here identically since neither is a new code path. Send
    packing-detail text to the LLM, get back structured fields.

    Returns the parsed JSON dict on success, or a dict with an "error" key
    if every attempt failed to parse - callers should check for this.
    Either way, the dict carries a "_usage" key summing tokens_in/
    tokens_out/cost_usd ACROSS all attempts, plus "attempts" (1 if no
    retry was needed).
    """
    prompt = build_prompt(input_text, examples=examples)
    return _extract_with_retry(LLM_MODEL, prompt, PRICE_IN, PRICE_OUT, max_retries)


def _photo_to_content_part(image_path: str) -> dict:
    """JPG/PNG/etc - already pixels, just base64-encode as-is into an
    image_url content part."""
    t0 = time.time()
    print(f"  [vlm] encoding {Path(image_path).name}...", flush=True)

    path = Path(image_path)
    img_bytes = path.read_bytes()
    ext = path.suffix.lower().lstrip(".")
    mime = f"image/{'jpeg' if ext == 'jpg' else ext}"
    b64 = base64.b64encode(img_bytes).decode("utf-8")

    print(f"  [vlm] encoded ({len(img_bytes)//1024} KB) in {time.time()-t0:.1f}s", flush=True)
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _pdf_to_content_part(pdf_path: str) -> dict:
    """PDF sent directly, no manual rendering - OpenRouter's file content
    type handles it server-side. engine="native" is forced by the caller
    (see extract_packing_fields_from_image) rather than left to
    OpenRouter's default, to guarantee the vision model actually sees
    the document itself rather than a silently OCR'd transcription."""
    t0 = time.time()
    print(f"  [vlm] encoding {Path(pdf_path).name}...", flush=True)

    pdf_bytes = Path(pdf_path).read_bytes()
    b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    print(f"  [vlm] encoded ({len(pdf_bytes)//1024} KB) in {time.time()-t0:.1f}s", flush=True)
    return {
        "type": "file",
        "file": {
            "filename": Path(pdf_path).name,
            "file_data": f"data:application/pdf;base64,{b64}",
        },
    }


# AFTER:
def extract_packing_fields_from_pdf(pdf_path: str, template_id: str = None, examples: str = "",
                                      max_retries: int = MAX_LLM_RETRIES) -> dict:
    """Vision path (Option B). Both cropped and whole-page modes render
    to an image and send via image_url - no "file" content type, no
    engine="native" plugin, since that mechanism is DeepSeek-specific
    and Qwen (vision-only) rejects it outright. If VLM_MODEL is ever
    switched to a model with genuine native PDF support, _pdf_to_content_part()
    is still here to switch back to."""
    if template_id:
        file_part = _cropped_pdf_to_content_part(pdf_path, template_id)
    else:
        file_part = _full_page_pdf_to_content_part(pdf_path)

    content = [
        {"type": "text", "text": build_vlm_prompt(examples=examples)},
        file_part,
    ]
    return _extract_with_retry(VLM_MODEL, content, VLM_PRICE_IN, VLM_PRICE_OUT, max_retries)



def _cropped_pdf_to_content_part(pdf_path: str, template_id: str) -> dict:
    """Crops the PDF page to a known region before sending - smaller
    image, fewer vision tokens, lower cost. Uses the same fixed
    fractional coordinates as the old OCR pipeline (config/
    template_regions.py) - same numbers, repurposed for a different
    reason (cost, not OCR crop accuracy). Trade-off: if the document's
    actual layout doesn't match its assigned template's coordinates,
    the model sees only the (wrong) slice, with no whole-page fallback
    - unlike the uncropped path, there's no chance for it to find the
    field elsewhere on the page."""
    import pymupdf

    region = TEMPLATE_REGIONS[template_id]

    t0 = time.time()
    print(f"  [vlm] cropping {Path(pdf_path).name} to '{template_id}' region...", flush=True)

    doc = pymupdf.open(pdf_path)
    page = doc[0]
    rect = page.rect
    clip = pymupdf.Rect(
        region["left"] * rect.width,
        region["top"] * rect.height,
        region["right"] * rect.width,
        region["bottom"] * rect.height,
    )
    pix = page.get_pixmap(dpi=200, clip=clip)
    img_bytes = pix.tobytes("png")
    b64 = base64.b64encode(img_bytes).decode("utf-8")

    print(f"  [vlm] cropped ({len(img_bytes)//1024} KB) in {time.time()-t0:.1f}s", flush=True)
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}


def _full_page_pdf_to_content_part(pdf_path: str) -> dict:
    """Whole page, no crop - rendered to an image and sent the same way
    _cropped_pdf_to_content_part() does. Qwen (and vision-only models in
    general) don't support OpenRouter's "file" content type or
    engine="native" PDF parsing - that path only works for models with
    genuine native PDF support (e.g. DeepSeek V4.1 Flash). This is the
    model-agnostic fallback: any vision model can accept a plain image."""
    t0 = time.time()
    print(f"  [vlm] rendering full page of {Path(pdf_path).name}...", flush=True)

    doc = pymupdf.open(pdf_path)
    page = doc[0]
    pix = page.get_pixmap(dpi=200)
    img_bytes = pix.tobytes("png")
    b64 = base64.b64encode(img_bytes).decode("utf-8")

    print(f"  [vlm] rendered ({len(img_bytes)//1024} KB) in {time.time()-t0:.1f}s", flush=True)
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}