from __future__ import annotations

import re
from pathlib import Path
from PIL import Image
import pytesseract

FIELDS = {
    "calories": r"calories?\s*(?:from fat\s*)?(\d+[\d,.]*)",
    "protein_g": r"protein\s*(\d+[\d,.]*)\s*g",
    "carbohydrates_g": r"(?:total\s*)?(?:carbohydrate|carbs?)\s*(\d+[\d,.]*)\s*g",
    "fat_g": r"(?:total\s*)?fat\s*(\d+[\d,.]*)\s*g",
    "serving_g": r"serving size.*?(\d+[\d,.]*)\s*g",
}

def parse_label(path: Path) -> tuple[str, dict[str, float], int]:
    image = Image.open(path).convert("L")
    text = pytesseract.image_to_string(image)
    normalized = re.sub(r"\s+", " ", text.lower())
    draft: dict[str, float] = {}
    for field, pattern in FIELDS.items():
        match = re.search(pattern, normalized, flags=re.I)
        if match:
            draft[field] = float(match.group(1).replace(",", ""))
    confidence = min(100, len(draft) * 20 + (20 if "nutrition" in normalized else 0))
    return text, draft, confidence
