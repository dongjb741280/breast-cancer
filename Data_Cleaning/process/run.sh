#!/bin/bash
# Full pipeline: scanned PDF -> Markdown (OCR via macOS Vision).
# Usage: ./run.sh
set -euo pipefail

cd "$(dirname "$0")"
PDF="../2026CSCO乳腺癌诊疗指南.pdf"
OUT="../2026CSCO乳腺癌诊疗指南.md"

echo "==> 1/4 render pages to PNG (300 dpi grayscale)"
mkdir -p pages
pdftoppm -r 300 -gray -png "$PDF" pages/pg

echo "==> 2/4 compile OCR tool"
swiftc -O ocr.swift -o ocr

echo "==> 3/4 OCR pages into raw text"
./ocr pages/ raw_ocr.txt

echo "==> 4/4 post-process into Markdown"
python3 postprocess.py raw_ocr.txt "$OUT"

echo "done -> $OUT"
