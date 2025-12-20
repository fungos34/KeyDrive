#!/usr/bin/env python3
"""
Remove exact white pixels by making them transparent.
Keep exact black pixels.
Turn everything else into black.
"""

import argparse

from PIL import Image

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)


def clean_logo(input_path: str, output_path: str) -> None:
    img = Image.open(input_path)

    # Force RGBA so we can control transparency
    rgba = img.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size

    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]

            # already transparent → keep
            if a == 0:
                continue

            # exact white → transparent
            if (r, g, b) == WHITE:
                px[x, y] = (0, 0, 0, 0)
                continue

            # exact black → keep
            if (r, g, b) == BLACK:
                continue

            # everything else → black, opaque
            px[x, y] = (0, 0, 0, 255)

    rgba.save(output_path, format="PNG")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Input PNG path")
    parser.add_argument("output", help="Output PNG path")
    args = parser.parse_args()

    clean_logo(args.input, args.output)


if __name__ == "__main__":
    main()
