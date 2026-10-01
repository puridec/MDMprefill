# config/template_regions.py
#
# Fork B design: template known ahead of time via form reference code,
# not inferred by any model - plain data lookup.
#
# Coordinates are stored as FRACTIONS of page width/height (0.0-1.0),
# not pixel counts - this makes them work correctly regardless of what
# DPI the page gets rendered at (150 DPI for EasyOCR memory limits,
# 300 DPI elsewhere, a photo at some other resolution, etc.).
# Pixel coordinates get computed at runtime from the actual image size.

TEMPLATE_REGIONS = {
    "GEN": {
        "left": 0.1073,
        "top": 0.5089,
        "right": 0.6959,
        "bottom": 0.5609,
        "description": "Poultry FORM GEN-101 style - Section 3 Packing Detail row",
    },
    "SEA": {   # <- a genuinely different document layout goes here,
        "left": 0.6570,
        "top": 0.2238,
        "right": 0.9394,
        "bottom": 0.2908,
        "description": "Seafood FORM SEA-201 style - Packing Detail section",
    },
}