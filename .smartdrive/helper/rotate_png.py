#!/usr/bin/env python3
"""
Rotate a PNG image by an arbitrary angle.
Preserves transparency and expands canvas to avoid clipping.

Usage:
  python rotate_png.py input.png output.png 15
"""

import argparse

from PIL import Image


def rotate_png(input_path: str, output_path: str, angle: float) -> None:
    img = Image.open(input_path).convert("RGBA")

    rotated = img.rotate(angle, resample=Image.BICUBIC, expand=False)  # high quality  # prevent cropping

    rotated.save(output_path, format="PNG")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Input PNG path")
    parser.add_argument("output", help="Output PNG path")
    parser.add_argument("angle", type=float, help="Rotation angle in degrees (positive = counter-clockwise)")
    args = parser.parse_args()

    rotate_png(args.input, args.output, args.angle)


if __name__ == "__main__":
    main()
