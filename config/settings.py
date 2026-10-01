# config/settings.py
#
# Every tunable number in the pipeline lives here, and only here.
# When you eventually run the real degraded-scan samples and need to
# adjust a threshold, this is the one file you touch - nothing else
# should have a number hardcoded in it.

# --- LLM extraction retry ---
MAX_LLM_RETRIES = 1
# NOT the same kind of retry as OCR resubmission above. This fires ONLY
# on invalid JSON from the model (a formatting failure, checkable with
# zero ground truth) - never on low completeness or any accuracy signal,
# since correctness isn't knowable at inference time without labels, and
# retrying on that risks the model fabricating values to look complete.
# See tools/llm_client.py extract_packing_fields() for the repair-prompt
# mechanism - a blind resend at LLM_TEMPERATURE=0.0 would just reproduce
# the same broken output.

# --- LLM extraction ---
import os
from dotenv import load_dotenv

load_dotenv()  # reads .env in the project root and puts values into os.environ

LLM_MODEL = "google/gemini-2.5-flash"
LLM_BASE_URL = "https://openrouter.ai/api/v1"
LLM_TIMEOUT = 60
LLM_TEMPERATURE = 0.0

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# --- Cost tracking (fallback only) ---
# OpenRouter returns the ACTUAL billed cost in usage.cost when the request
# asks for it (see tools/llm_client.py) - that's always the source of truth.
# These two are only used if that field is ever missing (e.g. a different
# provider/model swap that doesn't report cost).
PRICE_IN = 0.3 / 1_000_000   # USD per input token, fallback estimate
PRICE_OUT = 2.50 / 1_000_000  # USD per output token, fallback estimate

VLM_MODEL = "google/gemini-2.5-flash"
# Vision-capable, replaces the OCR+extract combination for the upload
# path (Option B). LLM_MODEL stays as-is - the text path (manual entry,
# product-dev system text) is unaffected and keeps using it.

VLM_PRICE_IN = 0.3 / 1_000_000   # USD per input token, fallback estimate
VLM_PRICE_OUT = 2.50 / 1_000_000  # USD per output token, fallback estimate
# Same fallback-only role as PRICE_IN/PRICE_OUT - usage.cost from
# OpenRouter is still the real source of truth. These are DIFFERENT
# numbers from the text model's pricing on purpose - do not reuse
# PRICE_IN/PRICE_OUT here, the vision model is priced ~2-4x higher.