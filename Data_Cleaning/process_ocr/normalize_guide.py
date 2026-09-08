"""guide.md 归一化：按 issue 02 的映射规则清理 OCR 噪声。

规则（见 .scratch/hybrid-kb/issues/02-guide-normalization.md）：
- 推荐等级：1级推荐 / I级推荐 -> Ⅰ级推荐；ⅡI级推荐 -> Ⅱ级推荐；川级推荐 -> Ⅲ级推荐
- 表头「级推荐」（数字整丢）按列位置补 Ⅰ/Ⅱ/Ⅲ（首列→Ⅰ、末列→Ⅲ）
- 证据类别：[2A / 2A] / 1B]3 补全方括号；1A 类证据 -> 1A类证据；1类证据 -> 1A类证据
"""
import re
from pathlib import Path

GUIDE = Path("Data_Cleaning/process_ocr/output/guide.md")

# 顺序敏感：ⅡI级推荐 必须先于 I级推荐 替换（ⅡI 含 I级推荐 子串）
LEVEL_FIXES = [
    ("ⅡI级推荐", "Ⅱ级推荐"),
    ("1级推荐", "Ⅰ级推荐"),
    ("I级推荐", "Ⅰ级推荐"),
    ("川级推荐", "Ⅲ级推荐"),
]

LEVEL_BY_COUNT = {1: ["Ⅰ"], 2: ["Ⅰ", "Ⅱ"], 3: ["Ⅰ", "Ⅱ", "Ⅲ"]}


def is_separator(line):
    cells = [c for c in line.strip().strip("|").split("|")]
    nonempty = [c for c in cells if c != ""]
    return bool(nonempty) and all(re.fullmatch(r":?-{2,}:?", c) for c in nonempty)


def fix_evidence(text):
    # 只处理 1A/1B/2A/2B，避免误伤 [3] 这类引文编号
    text = re.sub(r"\[([12][AB])(?!\])", r"[\1]", text)   # [2A -> [2A]
    text = re.sub(r"(?<!\[)([12][AB])\]", r"[\1]", text)   # 2A] -> [2A]
    text = text.replace("1A 类证据", "1A类证据")
    text = text.replace("1类证据", "1A类证据")
    return text


def fix_levels(text):
    for a, b in LEVEL_FIXES:
        text = text.replace(a, b)
    return text


def normalize_header(line):
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    rec_cols = [i for i, c in enumerate(cells) if "级推荐" in c]
    levels = LEVEL_BY_COUNT.get(len(rec_cols), ["Ⅰ"] * len(rec_cols))
    for k, ci in enumerate(rec_cols):
        cells[ci] = levels[k] + "级推荐"
    return "| " + " | ".join(cells) + " |"


def main():
    lines = GUIDE.read_text(encoding="utf-8").split("\n")
    out = []
    changed = 0
    for i, line in enumerate(lines):
        new = fix_levels(fix_evidence(line))
        if new.lstrip().startswith("|") and i + 1 < len(lines) and is_separator(lines[i + 1]):
            new = normalize_header(new)
        if new != line:
            changed += 1
        out.append(new)
    GUIDE.write_text("\n".join(out), encoding="utf-8")
    print(f"changed {changed} lines -> {GUIDE}")


if __name__ == "__main__":
    main()
