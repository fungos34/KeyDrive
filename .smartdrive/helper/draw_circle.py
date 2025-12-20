#!/usr/bin/env python3
"""
Draw an inscribed circle into a square PNG.
The circle touches all four sides of the image and is concentric.
Color and stroke width are configured inside this file.
"""

import argparse

from PIL import Image, ImageDraw

# =========================
# CONFIGURATION
# =========================
CIRCLE_COLOR = "black"  # "black" or "white"
CIRCLE_WIDTH = 1  # stroke width in pixels
# =========================


BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)


def draw_inscribed_circle(input_path: str, output_path: str) -> None:
    img = Image.open(input_path).convert("RGBA")
    w, h = img.size

    if w != h:
        raise ValueError(f"Image must be square, got {w}x{h}")

    if CIRCLE_COLOR.lower() == "black":
        stroke = BLACK
    elif CIRCLE_COLOR.lower() == "white":
        stroke = WHITE
    else:
        raise ValueError("CIRCLE_COLOR must be 'black' or 'white'")

    draw = ImageDraw.Draw(img)

    # Bounding box for inscribed circle
    # If you want the OUTER edge of the stroke to touch the image border exactly,
    # shrink by half the stroke width.
    inset = CIRCLE_WIDTH // 2
    bbox = (inset, inset, w - 1 - inset, h - 1 - inset)

    draw.ellipse(bbox, outline=stroke, width=CIRCLE_WIDTH)

    img.save(output_path, format="PNG")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Input square PNG")
    parser.add_argument("output", help="Output PNG")
    args = parser.parse_args()

    draw_inscribed_circle(args.input, args.output)


if __name__ == "__main__":
    main()
