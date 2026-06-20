#!/usr/bin/env python3
"""Regenerate the PopClip extension icon (requires Pillow: pip install pillow)."""
from PIL import Image, ImageDraw, ImageFont
import os

SIZE = 256
RADIUS = 45
BG = (66, 133, 244)  # Google blue #4285f4

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
# Transparent background — PopClip applies its own rounded rect via color: in Config.yaml

for fp in [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]:
    if os.path.exists(fp):
        font = ImageFont.truetype(fp, 100)
        break

text = "文A"
bbox = d.textbbox((0, 0), text, font=font)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
d.text(((SIZE - tw) / 2 - bbox[0], (SIZE - th) / 2 - bbox[1]), text, fill="white", font=font)

out = os.path.join(os.path.dirname(__file__), "../popclip/TranslatePanel.popclipext/icon.png")
img.save(os.path.abspath(out))
print(f"saved {os.path.abspath(out)}")
