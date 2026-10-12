"""The looks offered in step 2 of the page. Each is a set of /api/make parameters on top of the defaults.

"controls" names the few plain controls the page shows for that look; everything else lives under Advanced.
All in-book parts stay at or under 1.5 mm (a bank card is 0.76 mm).
"""

STYLES = [
    {"key": "paws", "name": "Paws over the page",
     "blurb": "Your pet sits on top of the book with its paws hanging over the page.",
     "params": {"style": "paws", "width": 16, "length": 90, "thickness": 0.9, "art_width": 60, "art_height": 50,
                "border": 1.0, "art_raise": 0.6, "gap": 1.0, "bottom": "round", "page_line": 0.78},
     "controls": ["size", "outline", "raise", "paws", "text"]},
    {"key": "peek", "name": "Peeking",
     "blurb": "Head pops out of the top of the book, feet stick out of the bottom.",
     "params": {"style": "solid", "peek": 1, "width": 24, "length": 110, "thickness": 0.9, "art_width": 50,
                "art_height": 60, "border": 1.5, "art_raise": 0.6, "peek_split": 0.7},
     "controls": ["size", "outline", "raise", "text"]},
    {"key": "clip", "name": "Page clip",
     "blurb": "A paperclip-style bookmark with your pet on top.",
     "params": {"style": "clip", "bottom": "round", "width": 24, "length": 110, "thickness": 0.9, "art_width": 50,
                "art_height": 60, "border": 1.5, "art_raise": 0.6},
     "controls": ["size", "outline", "raise", "shape", "text"]},
    {"key": "corner", "name": "Corner biter",
     "blurb": "Your pet's face on a pocket that slips over the corner of a page.",
     "params": {"style": "corner", "corner_leg": 55, "art_width": 50, "art_height": 45, "border": 1.5,
                "art_raise": 0.6, "crop": 0.55},
     "controls": ["size", "outline", "raise", "crop"]},
    {"key": "memorial", "name": "Memorial",
     "blurb": "Silhouette with a name and dates, and a tassel hole.",
     "params": {"style": "solid", "bottom": "round", "width": 30, "length": 120, "thickness": 0.9,
                "art_width": 45, "art_height": 45, "border": 1.5, "art_raise": 0.6, "hole": 1,
                "text_mode": "raised", "font": "dejavu-serif"},
     "controls": ["size", "outline", "raise", "text"], "text_hint": ["Name", "2012 - 2026"]},
    {"key": "photo", "name": "Photo layers",
     "blurb": "Your photo in 2 to 4 shades of filament (HueForge-style).",
     "params": {"mode": "photo", "style": "solid", "width": 40, "length": 120, "thickness": 0.7, "levels": 3},
     "controls": ["size", "levels"]},
]
