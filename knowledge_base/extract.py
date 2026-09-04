"""guide.md -> 推荐决策 records.

抽取 CSCO 指南 OCR 产物里的「决策表」，产出结构化决策记录（7 字段）。
只做结构抽取 + 归一化；不做图谱/检索/评测。
"""
import json
import re
from pathlib import Path

GUIDE = Path("Data_Cleaning/process_ocr/output/guide.md")
OUT = Path("knowledge_base/records.json")

# 证据类别：至少带一个方括号，容忍 OCR 丢半边（[2A、2A]、1B]）
EVID = re.compile(r"\[[123][AB]?\]?|[123][AB]?\]")

# 推荐列数 -> 从左到右的等级（CSCO 列恒为 Ⅰ→Ⅱ→Ⅲ 有序）
LEVEL_BY_COUNT = {1: ["Ⅰ"], 2: ["Ⅰ", "Ⅱ"], 3: ["Ⅰ", "Ⅱ", "Ⅲ"]}


def clean(s):
    return re.sub(r"\s+", " ", s).strip()


def section_title(line):
    """识别节标题：`## X` 或丢失 `##` 的 `（X）X`（中文数字）行。"""
    s = line.strip()
    if s.startswith("## "):
        return clean(s[3:])
    if re.match(r"^[（(][一二三四五六七八九十]+[）)]", s):
        return clean(s)
    return None


def classify_header(title):
    """从标题识别 治疗阶段 + 人群。"""
    stage = pop = None
    if "新辅助" in title:
        stage = "新辅助"
    elif "解救" in title or "晚期" in title:
        stage = "晚期解救"
    elif "辅助" in title:
        stage = "辅助"

    if "低表达" in title:
        pop = "HER2低表达"
    elif "HER-2" in title or "HER2" in title:
        pop = "HER2+"
    elif "三阴性" in title:
        pop = "三阴性"
    elif "激素受体阳性" in title or "HR" in title:
        pop = "HR+"
    return stage, pop


def strip_prefix(seg):
    """去掉 方案名 前的编号（1. 2.）、脚注上标、OCR 残渣。"""
    seg = clean(seg)
    seg = seg.lstrip("⁰¹²³⁴⁵⁶⁷⁸⁹²³° ")
    seg = re.sub(r"^[⁰¹²³⁴⁵⁶⁷⁸⁹²³°0-9]+\s*[\.、．]\s*", "", seg)
    seg = seg.lstrip("⁰¹²³⁴⁵⁶⁷⁸⁹²³° ")
    return seg.strip(" .·")


def clean_name(name):
    """去掉方案名尾部紧跟中文的脚注号/上标（如 卡培他滨1、TCbHP²），不动 T-DM1 这类拉丁尾缀。"""
    name = clean(name)
    name = re.sub(r"(?<=[一-鿿）)])\s*[⁰¹²³⁴⁵⁶⁷⁸⁹0-9]+\s*[°²³⁴]*$", "", name)
    return name.strip()


def parse_cell(cell):
    """单元格 -> [(方案, 证据类别), ...]。"""
    cell = clean(cell)
    if not cell:
        return []
    matches = list(EVID.finditer(cell))
    if not matches:
        m2 = re.search(r"([123][AB])$", cell)
        if m2:
            name = clean_name(strip_prefix(cell[:m2.start()]))
            return [(name, m2.group(1))] if name else []
        name = clean_name(strip_prefix(cell))
        return [(name, None)] if name else []
    items = []
    prev = 0
    for m in matches:
        seg = cell[prev:m.start()]
        ev = re.sub(r"[^123AB]", "", m.group(0)) or None
        name = clean_name(strip_prefix(seg))
        if name:
            items.append((name, ev))
        prev = m.end()
    return items


def split_row(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_separator(cells):
    return all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c != "")


def parse_table(tbl, stage, pop, subtitle, page):
    header = split_row(tbl[0])
    if not is_separator(split_row(tbl[1])):
        return []
    rec_cols = [i for i, c in enumerate(header) if "级推荐" in c]
    if not rec_cols:
        return []
    strat_col = 0 if "级推荐" not in header[0] else None
    levels = LEVEL_BY_COUNT.get(len(rec_cols), ["Ⅰ"] * len(rec_cols))

    recs = []
    for row in tbl[2:]:
        cells = split_row(row)
        if not cells:
            continue
        strat = cells[strat_col] if strat_col is not None else subtitle
        if strat_col is not None and not cells[strat_col].strip():
            strat = subtitle
        for k, ci in enumerate(rec_cols):
            cell = cells[ci] if ci < len(cells) else ""
            for name, ev in parse_cell(cell):
                recs.append({
                    "治疗阶段": stage, "人群": pop, "分层条件": clean(strat),
                    "方案": name, "推荐等级": levels[k], "证据类别": ev,
                    "来源页码": page,
                })
    return recs


def main():
    lines = GUIDE.read_text(encoding="utf-8").split("\n")
    page = None
    stage = pop = None
    subtitle = None
    records = []

    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"<!-- ===== Page (\d+) ===== -->", line.strip())
        if m:
            page = int(m.group(1))
            i += 1
            continue
        title = section_title(line)
        if title:
            s, p = classify_header(title)
            if s:
                stage = s
            if p:
                pop = p
            subtitle = title
            i += 1
            continue
        if line.lstrip().startswith("|"):
            j = i
            tbl = []
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                tbl.append(lines[j])
                j += 1
            if len(tbl) >= 2:
                records.extend(parse_table(tbl, stage, pop, subtitle, page))
            i = j
            continue
        i += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(records)} records -> {OUT}")

    # 统计
    by_level = {}
    by_stage = {}
    no_ev = 0
    for r in records:
        by_level[r["推荐等级"]] = by_level.get(r["推荐等级"], 0) + 1
        by_stage[r["治疗阶段"]] = by_stage.get(r["治疗阶段"], 0) + 1
        if not r["证据类别"]:
            no_ev += 1
    print("推荐等级:", by_level)
    print("治疗阶段:", by_stage)
    print("无证据类别:", no_ev)


if __name__ == "__main__":
    main()
