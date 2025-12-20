#!/usr/bin/env python3
"""
Make an image square by padding (not cropping).
Preserves transparency and centers the original image on the new canvas.

Usage:
  python make_square.py input.png output.png
"""

import argparse

from PIL import Image


def make_square(input_path: str, output_path: str) -> None:
    img = Image.open(input_path).convert("RGBA")
    w, h = img.size

    side = max(w, h)

    # Create square transparent canvas
    out = Image.new("RGBA", (side, side), (0, 0, 0, 0))

    # Center original image on new canvas
    offset_x = (side - w) // 2
    offset_y = (side - h) // 2

    out.paste(img, (offset_x, offset_y), img)  # use img as mask to keep alpha
    out.save(output_path, format="PNG")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Input PNG path")
    parser.add_argument("output", help="Output PNG path")
    args = parser.parse_args()

    make_square(args.input, args.output)


if __name__ == "__main__":
    main()
