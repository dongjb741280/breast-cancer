import sys
import os
import re
import tempfile
from io import StringIO

import pandas as pd
from PIL import Image
from paddleocr import PPStructureV3

# 大图先降采样，避免 16GB 机器上多模型推理 OOM（长边上限）
MAX_SIDE = 2500

# 版面标签归类
HEADING_LABELS = {
    "paragraph_title", "title", "doc_title", "chapter_title",
    "section_title", "subtitle",
}
SKIP_LABELS = {"footer", "header", "page_number", "number"}


def clean_text(s):
    return " ".join(line.strip() for line in s.splitlines() if line.strip())


def table_html_to_md(html):
    """把 PP-StructureV3 输出的表格 HTML 转成 markdown 网格。"""
    try:
        dfs = pd.read_html(StringIO(html), header=None)
    except Exception:
        return html  # 兜底：保留原文，不丢数据
    if not dfs:
        return html
    df = dfs[0].fillna("")
    rows = df.astype(str).values.tolist()
    ncol = df.shape[1]

    def esc(c):
        return c.replace("|", "\\|").replace("\n", " ").strip()

    lines = []
    header = [esc(c) for c in rows[0]]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * ncol) + "|")
    for r in rows[1:]:
        cells = [esc(c) for c in r]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def block_to_md(b):
    label = (b.label or "").lower()
    content = b.content or ""
    if not isinstance(content, str):
        content = str(content)

    if label in SKIP_LABELS:
        return ""
    if label == "table":
        md = table_html_to_md(content)
        return md + "\n" if md.strip() else ""
    if label in HEADING_LABELS:
        return "## " + clean_text(content) + "\n"

    text = clean_text(content)
    return text + "\n" if text else ""


def process_page(path, pipe):
    with Image.open(path) as im:
        w, h = im.size
        if max(w, h) > MAX_SIDE:
            ratio = MAX_SIDE / max(w, h)
            nw, nh = int(w * ratio), int(h * ratio)
            im = im.convert("RGB").resize((nw, nh), Image.LANCZOS)
            fd, tmp = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            im.save(tmp)
            use_tmp = True
        else:
            use_tmp = False
    if use_tmp:
        try:
            r = pipe.predict(tmp)[0]
        finally:
            os.remove(tmp)
    else:
        r = pipe.predict(path)[0]
    parts = [block_to_md(b) for b in r["parsing_res_list"]]
    return "\n".join(p for p in parts if p)


def main():
    if len(sys.argv) < 3:
        print("usage: ocr_structure.py <input_dir> <output_file> [--limit N]", file=sys.stderr)
        sys.exit(1)
    indir = sys.argv[1]
    outpath = sys.argv[2]
    limit = None
    if len(sys.argv) >= 5 and sys.argv[3] == "--limit":
        limit = int(sys.argv[4])

    pipe = PPStructureV3(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        use_seal_recognition=False,
        use_formula_recognition=False,
        use_chart_recognition=False,
        use_table_recognition=True,
        lang="ch",
    )

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
        body = process_page(indir + "/" + f, pipe)
        if body:
            output.append(body)
        output.append("")

    raw = "\n".join(output)
    body = re.sub(r"\n{3,}", "\n\n", raw).strip() + "\n"
    title = "# 2026 CSCO 乳腺癌诊疗指南\n\n"
    with open(outpath, "w", encoding="utf-8") as fh:
        fh.write(title + body)
    print(f"wrote {len(pngs)} pages -> {outpath}")


if __name__ == "__main__":
    main()
