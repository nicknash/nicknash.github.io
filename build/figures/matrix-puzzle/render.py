#!/usr/bin/env python3
"""Recreate the lost XOR texture from the matrix post's formula.

Each pixel (column c, row r) has grayscale intensity r XOR c. The original
WordPress export records a 255-by-255 GIF; this is a new rendering of that
formula, not a recovered copy of the original image.
"""

from pathlib import Path

from PIL import Image


def main():
    root = Path(__file__).resolve().parents[3]
    output = root / "assets/matrix-puzzle/xor.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    size = 255
    texture = Image.frombytes(
        "L", (size, size), bytes(r ^ c for r in range(size) for c in range(size))
    )
    texture.save(output)
    print(output)


if __name__ == "__main__":
    main()
