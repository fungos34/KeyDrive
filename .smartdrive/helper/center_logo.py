#!/usr/bin/env python3
"""
Center a logo in a PNG by moving the centroid of all non-transparent pixels
to the center of the image canvas.
"""

import argparse

from PIL import Image


def center_logo(input_path: str, output_path: str) -> None:
    img = Image.open(input_path).convert("RGBA")
    w, h = img.size
    px = img.load()

    # Compute centroid of all non-transparent pixels
    sum_x = 0
    sum_y = 0
    count = 0

    for y in range(h):
        for x in range(w):
            if px[x, y][3] > 0:  # alpha > 0
                sum_x += x
                sum_y += y
                count += 1

    if count == 0:
        raise ValueError("No non-transparent pixels found (empty logo).")

    cx_logo = sum_x / count
    cy_logo = sum_y / count

    # Image center
    cx_img = (w - 1) / 2
    cy_img = (h - 1) / 2

    dx = int(round(cx_img - cx_logo))
    dy = int(round(cy_img - cy_logo))

    # Create new transparent image
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out_px = out.load()

    # Move pixels
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue

            nx = x + dx
            ny = y + dy

            if 0 <= nx < w and 0 <= ny < h:
                out_px[nx, ny] = (r, g, b, a)

    out.save(output_path, format="PNG")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Input PNG path")
    parser.add_argument("output", help="Output PNG path")
    args = parser.parse_args()

    center_logo(args.input, args.output)


if __name__ == "__main__":
    main()
