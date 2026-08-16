#!/usr/bin/env bash
# Convert the STIX Two OTFs shipped with TeX Live into web fonts.
#
# The results are committed to assets/fonts/, so neither CI nor a normal build
# needs to run this. Re-run it only to change which faces the site ships:
#
#     bash build/make-fonts.sh
#
# STIX Two is the pairing this site is built on: STIXTwoText for prose, and
# STIXTwoMath as a full OpenType MATH font so browsers typeset MathML at
# something close to PDF quality instead of falling back to a default.
#
# The text faces are subset to Latin + punctuation + common symbols, which cuts
# them by roughly two thirds. The math face is NOT subset: its MATH table and
# glyph-variant chains reference glyphs that no coverage list predicts, and
# dropping the wrong one silently breaks stretchy brackets and big operators.
set -euo pipefail

SRC=/usr/share/texlive/texmf-dist/fonts/opentype/public/stix2-otf
OUT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/assets/fonts"

command -v pyftsubset >/dev/null || {
  echo "pyftsubset not found -- pip install 'fonttools[woff]'" >&2; exit 1; }
[ -d "$SRC" ] || { echo "STIX Two not found at $SRC" >&2; exit 1; }

mkdir -p "$OUT"

# U+0000-00FF  Latin-1     U+0131 dotless i   U+0152-0153 OE
# U+02BB-02BC  turned comma  U+2000-206F general punctuation
# U+2070-209F  super/subscripts   U+20A0-20BF currency
# U+2122 trademark  U+2190-21FF arrows  U+2200-22FF math operators
UNICODES='U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+2070-209F,U+20A0-20BF,U+2122,U+2190-21FF,U+2200-22FF,U+2212,U+2215,U+FEFF,U+FFFD'

for face in Regular Italic Bold BoldItalic; do
  echo "  subsetting STIXTwoText-$face"
  pyftsubset "$SRC/STIXTwoText-$face.otf" \
    --unicodes="$UNICODES" \
    --layout-features='kern,liga,clig,calt,onum,pnum,frac,sups,subs' \
    --flavor=woff2 \
    --output-file="$OUT/STIXTwoText-$face.woff2"
done

echo "  converting STIXTwoMath-Regular (no subsetting)"
pyftsubset "$SRC/STIXTwoMath-Regular.otf" \
  --unicodes='*' --glyphs='*' --layout-features='*' --notdef-outline \
  --drop-tables= --flavor=woff2 \
  --output-file="$OUT/STIXTwoMath-Regular.woff2"

echo
ls -la "$OUT"
