#!/usr/bin/env python3
"""
Increase (or decrease) the size of a logo inside a PNG
while keeping the image canvas size unchanged.

Usage:
  python scale_logo.py input.png output.png 1.2
"""

import argparse

from PIL import Image


def scale_logo(input_path: str, output_path: str, scale: float) -> None:
    img = Image.open(input_path).convert("RGBA")
    w, h = img.size

    # Scale the image
    new_w = int(round(w * scale))
    new_h = int(round(h * scale))

    scaled = img.resize((new_w, new_h), resample=Image.BICUBIC)

    # Create same-size transparent canvas
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    # Center the scaled logo
    offset_x = (w - new_w) // 2
    offset_y = (h - new_h) // 2

    out.paste(scaled, (offset_x, offset_y), scaled)
    out.save(output_path, format="PNG")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="Input PNG")
    ap.add_argument("output", help="Output PNG")
    ap.add_argument("scale", type=float, help="Scale factor (e.g. 1.1 = +10%, 0.9 = -10%)")
    args = ap.parse_args()

    scale_logo(args.input, args.output, args.scale)


if __name__ == "__main__":
    main()
