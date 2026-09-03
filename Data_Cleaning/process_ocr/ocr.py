import sys
from PIL import Image
import numpy as np
from paddleocr import PaddleOCR


# Fix common OCR misreadings of the Roman numerals Ⅰ/Ⅱ/Ⅲ (recommendation
# levels), which the recognizer sometimes reads as "I/II/III", "皿", or "|/||/|||".
def normalize(s: str) -> str:
    t = s
    for a, b in [
        ("||| 级", "Ⅲ级"), ("|| 级", "Ⅱ级"), ("| 级", "Ⅰ级"),
        ("III级", "Ⅲ级"), ("II级", "Ⅱ级"), ("I级", "Ⅰ级"),
        ("皿级", "Ⅲ级"), ("|||级", "Ⅲ级"), ("||级", "Ⅱ级"), ("|级", "Ⅰ级"),
    ]:
        t = t.replace(a, b)
    return t


class Fragment:
    __slots__ = ("text", "left", "top", "right", "bottom")

    def __init__(self, text, left, top, right, bottom):
        self.text = text
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom

    @property
    def minX(self):
        return self.left

    @property
    def maxX(self):
        return self.right

    @property
    def midX(self):
        return (self.left + self.right) / 2

    @property
    def midY(self):
        return (self.top + self.bottom) / 2


class Row:
    def __init__(self, frag):
        self.fragments = [frag]
        self.midY = frag.midY

    @property
    def text(self):
        return normalize(" ".join(f.text for f in sorted(self.fragments, key=lambda f: f.minX)))


def group_rows(frags, tol):
    ordered = sorted(frags, key=lambda f: (f.midY, f.minX))
    rows = []
    for f in ordered:
        idx = None
        for i in range(len(rows) - 1, -1, -1):
            if abs(rows[i].midY - f.midY) <= tol:
                idx = i
                break
        if idx is not None:
            rows[idx].fragments.append(f)
            rows[idx].midY = sum(ff.midY for ff in rows[idx].fragments) / len(rows[idx].fragments)
        else:
            rows.append(Row(f))
    return rows


def is_tabular(row):
    return len(row.fragments) >= 2


# Cluster left-edges into column centers. Single-fragment clusters are dropped
# (usually merged header cells), EXCEPT those anchored by a header-row fragment,
# which keeps sparsely-populated columns (e.g. Ⅲ级推荐).
def column_centers(block, tol, eps):
    xs = sorted(f.minX for row in block for f in row.fragments)
    if not xs:
        return []
    clusters = []
    lo = hi = xs[0]
    count = 1
    for x in xs[1:]:
        if x - hi > tol:
            clusters.append((lo, hi, count))
            lo = hi = x
            count = 1
        else:
            hi = max(hi, x)
            count += 1
    clusters.append((lo, hi, count))
    header_xs = [f.minX for f in block[0].fragments]
    centers = []
    for lo, hi, count in clusters:
        if count >= 2 or any(lo - eps <= hx <= hi + eps for hx in header_xs):
            centers.append((lo + hi) / 2)
    return centers


def assign_cells(row, centers):
    cells = ["" for _ in centers]
    for f in sorted(row.fragments, key=lambda f: f.minX):
        best = 0
        best_d = float("inf")
        for i, c in enumerate(centers):
            d = abs(f.minX - c)
            if d < best_d:
                best_d = d
                best = i
        if cells[best]:
            cells[best] += " "
        cells[best] += f.text
    return [normalize(c) for c in cells]


def escape_cell(s):
    return s.replace("|", "\\|").replace("\n", " ").strip()


def emit_table(block, centers):
    ncol = len(centers)
    if ncol < 2 or len(block) < 2:
        return None
    lines = []
    header = [escape_cell(c) for c in assign_cells(block[0], centers)]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * ncol) + "|")
    for row in block[1:]:
        cells = [escape_cell(c) for c in assign_cells(row, centers)]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return lines


def process_page(path, ocr):
    res = ocr.predict(path)
    r = res[0]
    texts = r["rec_texts"]
    boxes = np.asarray(r["rec_boxes"])
    if boxes.size == 0:
        return ""
    with Image.open(path) as im:
        W, H = im.size

    all_frags = []
    for t, b in zip(texts, boxes):
        if not isinstance(t, str) or not t.strip():
            continue
        all_frags.append(Fragment(t, float(b[0]), float(b[1]), float(b[2]), float(b[3])))

    if not all_frags:
        return ""

    # Drop scan watermark / page number: pure digits in the bottom band of the
    # page (measured relative to the lowest content, not the page edge).
    max_top = max(f.top for f in all_frags)
    frags = [
        f for f in all_frags
        if not (all(c.isdigit() or c.isspace() for c in f.text) and f.top > max_top - 0.05 * H)
    ]
    if not frags:
        return ""

    rows = group_rows(frags, tol=0.012 * H)

    out = []
    i = 0
    while i < len(rows):
        if is_tabular(rows[i]):
            j = i
            while j < len(rows) and is_tabular(rows[j]):
                j += 1
            block = rows[i:j]
            if len(block) >= 2:
                centers = column_centers(block, tol=0.03 * W, eps=0.001 * W)
                if len(centers) >= 2:
                    out.extend(emit_table(block, centers))
                    i = j
                    continue
        out.append(rows[i].text)
        i += 1
    return "\n".join(out)


def main():
    if len(sys.argv) < 3:
        print("usage: ocr.py <input_dir> <output_file> [--limit N]", file=sys.stderr)
        sys.exit(1)
    indir = sys.argv[1]
    outpath = sys.argv[2]
    limit = None
    if len(sys.argv) >= 5 and sys.argv[3] == "--limit":
        limit = int(sys.argv[4])

    ocr = PaddleOCR(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        lang="ch",
    )

    import os
    pngs = sorted(f for f in os.listdir(indir) if f.endswith(".png"))
    if limit is not None:
        pngs = pngs[:limit]

    output = []
    total = len(pngs)
    for i, f in enumerate(pngs, 1):
        page_no = f[3:6]
        print(f"[{i}/{total}] processing {f} (page {page_no})", flush=True)
        output.append(f"<!-- ===== Page {page_no} ===== -->")
        output.append("")
        body = process_page(indir + "/" + f, ocr)
        if body:
            output.append(body)
        output.append("")

    raw = "\n".join(output)
    import re
    body = re.sub(r"\n{3,}", "\n\n", raw).strip() + "\n"
    title = "# 2026 CSCO 乳腺癌诊疗指南\n\n"
    with open(outpath, "w", encoding="utf-8") as fh:
        fh.write(title + body)
    print(f"wrote {len(pngs)} pages -> {outpath}")


if __name__ == "__main__":
    main()
