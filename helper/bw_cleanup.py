#!/usr/bin/env python3
"""
Keep only exact plain black pixels.
Every other pixel becomes fully transparent.
"""

import argparse

from PIL import Image

BLACK = (0, 0, 0)


def keep_black_only(input_path: str, output_path: str) -> None:
    img = Image.open(input_path)

    # Force RGBA so we can control transparency
    rgba = img.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size

    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]

            # Exact black AND non-transparent → keep
            if a != 0 and (r, g, b) == BLACK:
                px[x, y] = (0, 0, 0, 255)
            else:
                # EVERYTHING else → transparent
                px[x, y] = (0, 0, 0, 0)

    rgba.save(output_path, format="PNG")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Input PNG path")
    parser.add_argument("output", help="Output PNG path")
    args = parser.parse_args()

    keep_black_only(args.input, args.output)


if __name__ == "__main__":
    main()
