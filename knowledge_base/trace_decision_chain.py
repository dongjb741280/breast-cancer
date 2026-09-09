"""确定性决策链追踪：病历 JSON → 抽取特征 → 逐节点走通诊疗决策链。

不依赖 LLM，纯规则。输入为「系统输入」目录下的标准病历 JSON，
输出一条 A→U 的决策链路径（节点 + 病历证据 + 分支选择），
并可（--diagram）生成高亮该病例实际路径的 mermaid 源文件。

用法：
    python trace_decision_chain.py REAL-002
    python trace_decision_chain.py REAL-002 --diagram
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_case import CASE_JSON

# ---- 决策链结构（与 diagrams/*.mmd 保持一致） ----
NODES = {
    "A": "初诊乳腺癌",
    "B": "影像 + 病理 + 分子标志物",
    "C": "TNM分期与风险分层",
    "D": "M分期：有无远处转移?",
    "E": "是否适合新辅助治疗?",
    "F": "按分子亚型选择新辅助方案",
    "G": "直接手术与腋窝评估",
    "H": "手术 + 病理反应评估",
    "I": "pCR还是残余病灶?",
    "J": "按风险完成术后辅助治疗",
    "K": "强化辅助（HER2+/三阴）<br/>T-DM1 / 卡培他滨 / 奥拉帕利<br/>HR+：按风险辅助",
    "L": "放疗 / 内分泌 / 抗HER2 / 免疫等",
    "M": "转移灶再活检与再分型",
    "N": "评估既往治疗、耐药、疾病速度与患者状态",
    "O": "按分子亚型序贯全身治疗<br/>HER2阳性 / HER2低表达<br/>三阴性 / HR阳性",
    "P": "特殊转移部位?",
    "Q": "骨改良药 + 局部放疗/手术评估",
    "R": "脑部局部治疗 + 全身治疗评估",
    "S": "继续系统治疗与疗效评估",
    "T": "疗效评估、毒性管理、营养/心理支持、生活质量与MDT",
    "U": "长期随访、复发监测与临床研究/真实世界证据更新",
}
DIAMOND = {"D", "E", "I", "P"}

# 边按 mermaid 中的定义顺序排列（linkStyle 用 0 基下标）
EDGES = [
    ("A", "B", ""), ("B", "C", ""), ("C", "D", ""),
    ("D", "E", "否：M0 早期/局部进展期"),
    ("E", "F", "是"), ("E", "G", "否"),
    ("F", "H", ""), ("G", "H", ""),
    ("H", "I", ""),
    ("I", "J", "pCR"), ("I", "K", "non-pCR"),
    ("J", "L", ""), ("K", "L", ""),
    ("D", "M", "是：M1 复发/转移期"),
    ("M", "N", ""), ("N", "O", ""), ("O", "P", ""),
    ("P", "Q", "骨转移"), ("P", "R", "脑转移"), ("P", "S", "其他内脏/软组织转移"),
    ("L", "T", ""), ("Q", "T", ""), ("R", "T", ""), ("S", "T", ""),
    ("T", "U", ""),
]


def load_case(case_id):
    if case_id not in CASE_JSON:
        sys.exit(f"未知病例 {case_id}，可选：{', '.join(CASE_JSON)}")
    return json.load(open(CASE_JSON[case_id], encoding="utf-8"))["patient_data"]


def _narrative(pd):
    """拼接叙事文本，优先入院/出院/首次病程记录。"""
    docs = pd.get("standard_inpatient_documentations", [])
    picked = []
    for doc in docs:
        name = doc.get("standard_record_item_name") or doc.get("record_item_name") or ""
        rt = doc.get("record_text") or doc.get("original_record_text") or ""
        if rt and any(k in name for k in ("入院记录", "首次病程", "出院记录", "出院小结")):
            picked.append(rt)
    return "\n".join(picked)


def _diagnoses(pd):
    names = []
    for x in pd.get("diagnosis", []):
        n = x.get("standard_name") or x.get("original_diagnosis_name")
        if n and n not in names:
            names.append(n)
    return names


def extract(pd):
    sp = pd.get("standard_patient") or {}
    gender = sp.get("standard_gender", "")
    age = next((x.get("standard_age") or x.get("original_age")
                for x in pd.get("diagnosis", []) if x.get("standard_age") is not None), "")

    text = _narrative(pd)
    diags = _diagnoses(pd)

    # TNM + 分期
    m = re.search(r"[cpa]?T(\d)N(\d)M(\d)", text) or re.search(r"T(\d)N(\d)M(\d)", text)
    tnm = m.group(0) if m else ""
    stage = ""
    sm = re.search(r"(IV|Ⅲ|III|Ⅱ|II|Ⅰ|I)A?B?期", text)
    if sm:
        stage = sm.group(0)

    # 分子标志物（原始 IHC 证据）
    def _find(p):
        mm = re.search(p, text)
        return mm.group(0) if mm else ""

    er = _find(r"ER\s*\([^)]*\)") or _find(r"ER[（(][^）)]*[）)]")
    pr = _find(r"PR\s*\([^)]*\)") or _find(r"PR[（(][^）)]*[）)]")
    her2 = _find(r"HER-?2\s*\([^)]*\)")
    ki67 = _find(r"[Kk]i-?67\s*\([^)]*\)")
    fish = ""
    if re.search(r"FISH[^。；]*扩增\s*阴性|FISH[^。；]*阴性", text):
        fish = "FISH扩增阴性"
    elif re.search(r"FISH[^。；]*扩增\s*阳性|ISH\s*阳性", text):
        fish = "FISH扩增阳性"

    # 分子分型（优先读诊断结论，其次按 IHC 规则判读）
    def _pos(s):
        m = re.search(r"(\d+)", s or "")
        return bool(m) and int(m.group(1)) >= 1

    subtype = ""
    for kw, label in (("HER2阳性型", "HER2阳性型"), ("HER2低表达", "HER2低表达型"),
                      ("三阴性", "三阴性"), ("三阴型", "三阴性")):
        if kw in text:
            subtype = label
            break
    if not subtype:
        h = re.search(r"HER-?2\s*[（(](\d)\+[）)]", text)
        if h:
            ihc = h.group(1)
            if ihc == "3":
                subtype = "HER2阳性型"
            elif ihc == "2":
                subtype = "HER2阳性型" if "扩增阳性" in fish else ("HER2低表达型" if "阴性" in fish else "HER2待核验(IHC2+)")
            elif ihc == "1":
                subtype = "HER2低表达型"
            else:  # IHC 0
                subtype = "三阴性" if not (_pos(er) or _pos(pr)) else "HR阳性/HER2阴性"
        else:  # HER2 阴性（“-”/“阴性”/“0分”等）
            subtype = "三阴性" if not (_pos(er) or _pos(pr)) else "HR阳性/HER2阴性"

    # 转移部位：只在「X继发恶性肿瘤 / X转移」语境下命中，避免误伤体检/正常描述
    sites = []
    blob = " ".join(diags) + " " + text
    for kw, site in (("肝", "肝"), ("骨", "骨"), ("脑", "脑"), ("颅内", "脑"),
                     ("肺", "肺"), ("肾上腺", "肾上腺"), ("胸膜", "胸膜")):
        if re.search(kw + r"\s*(继发恶性肿瘤|转移瘤|转移灶|转移)", blob) and site not in sites:
            sites.append(site)

    m1 = "M1" in tnm or stage.startswith("IV") or "Ⅳ" in stage or bool(sites)

    # 治疗
    tx = []
    if re.search(r"曲妥珠单抗|帕妥珠单抗|T-DM1|T-DXd|吡咯替尼|恩美曲妥珠", text):
        tx.append("抗HER2靶向")
    if re.search(r"阿那曲唑|来曲唑|他莫昔芬|内分泌", text):
        tx.append("内分泌")
    if re.search(r"多西他赛|紫杉|卡培他滨|化疗", text):
        tx.append("化疗")
    if re.search(r"放疗", text):
        tx.append("放疗")
    if re.search(r"唑来膦酸|地舒单抗|骨改良", text):
        tx.append("骨改良药")

    return {
        "gender": gender, "age": age, "tnm": tnm, "stage": stage,
        "subtype": subtype, "er": er, "pr": pr, "her2": her2, "ki67": ki67, "fish": fish,
        "sites": sites, "m1": m1, "tx": tx, "diags": diags, "text": text,
    }


def trace(f):
    """返回 (steps, path_nodes, path_edges)。step = (node, evidence, branch)。"""
    steps = []
    steps.append(("A", "右乳/腋下肿块，穿刺确诊浸润性癌", ""))
    steps.append(("B", f"彩超/CT/MR/ECT + 穿刺病理 + IHC（{f['her2'] or '见病历'}）", ""))
    steps.append(("C", f"{f['tnm']} {f['stage']}".strip(), ""))

    path = ["A", "B", "C"]
    if f["m1"]:
        steps.append(("D", "存在远处转移", f"是：M1（{ '、'.join(f['sites']) or '见病历' }）"))
        steps.append(("M", "转移灶/原发灶再活检 + 再分型", ""))
        steps.append(("N", "评估既往治疗、耐药、疾病速度、患者状态", ""))
        steps.append(("O", f"主导病灶 = {f['subtype']}", f['subtype']))
        path += ["D", "M", "N", "O"]
        steps.append(("P", f"转移部位：{ '、'.join(f['sites']) or '无特殊' }", ""))
        path.append("P")
        if "骨" in f["sites"]:
            steps.append(("Q", "骨转移 → 骨改良药 + 局部放疗/手术", "骨转移"))
            path.append("Q")
        if "脑" in f["sites"]:
            steps.append(("R", "脑转移 → 局部治疗 + 全身治疗", "脑转移"))
            path.append("R")
        if any(s in f["sites"] for s in ("肝", "肺")) or not f["sites"]:
            steps.append(("S", "其他内脏/软组织转移 → 继续系统治疗", "其他内脏转移"))
            path.append("S")
    else:
        steps.append(("D", "无远处转移", "否：M0 早期/局部进展期"))
        steps.append(("E", "是否适合新辅助治疗（肿块大/LN+/HER2+/三阴/保乳意愿）", ""))
        # 早期路径无法仅凭结构化字段确定，给出分支提示即可
        path += ["D", "E"]

    steps.append(("T", "疗效评估、毒性管理、营养/心理支持、MDT", ""))
    steps.append(("U", "长期随访、复发监测", ""))
    path += ["T", "U"]

    # 由 path_nodes 推导走的边（按 EDGES 顺序匹配相邻节点）
    edges = []
    for i, (a, b, _) in enumerate(EDGES):
        if a in path and b in path:
            edges.append(i)
    return steps, path, edges


def render_walkthrough(case_id, f, steps):
    lines = [f"病例 {case_id}：{f['gender']} {f['age']}岁",
             f"诊断：{'、'.join(f['diags'])}",
             f"TNM/分期：{f['tnm']} {f['stage']}".strip(),
             f"分子分型：{f['subtype'] or '未知'}   ER {f['er'] or '-'}  PR {f['pr'] or '-'}  HER2 {f['her2'] or '-'}  Ki67 {f['ki67'] or '-'}  {f['fish']}",
             f"转移部位：{'、'.join(f['sites']) or '无'}",
             f"治疗：{' + '.join(f['tx']) or '未提取到'}",
             "", "决策链路径："]
    for node, ev, branch in steps:
        label = NODES[node].replace("<br/>", " / ")
        line = f"  [{node}] {label}"
        if branch:
            line += f"  ← {branch}"
        lines.append(line)
        if ev:
            lines.append(f"         ↳ {ev}")
    return "\n".join(lines)


def render_mermaid(f, path, edges):
    """生成高亮该病例路径的 mermaid 源。"""
    lines = ["%% 乳腺癌诊疗决策链（高亮病例实际路径）", "graph TD"]
    for nid in NODES:
        label = NODES[nid]
        shape = "{" if nid in DIAMOND else "["
        close = "}" if nid in DIAMOND else "]"
        lines.append(f"    {nid}{shape}{label}{close}")
    for a, b, lab in EDGES:
        if lab:
            lines.append(f"    {a} -->|{lab}| {b}")
        else:
            lines.append(f"    {a} --> {b}")
    lines += [
        "    classDef path fill:#fca5a5,stroke:#dc2626,color:#7f1d1d,stroke-width:3px;",
        "    classDef dim fill:#f3f4f6,stroke:#d1d5db,color:#9ca3af,stroke-width:1px;",
    ]
    path_set = set(path)
    for nid in NODES:
        cls = "path" if nid in path_set else "dim"
        lines.append(f"    class {nid} {cls};")
    for i in range(len(EDGES)):
        style = "stroke:#dc2626,stroke-width:3px" if i in edges else "stroke:#d1d5db,stroke-width:1px"
        lines.append(f"    linkStyle {i} {style};")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case", help="病例编号，如 REAL-002")
    ap.add_argument("--diagram", action="store_true", help="额外生成高亮 mermaid 图")
    ap.add_argument("--out", default=None, help="mermaid 输出路径（默认 diagrams/decision-chain-<case>.mmd）")
    args = ap.parse_args()

    f = extract(load_case(args.case))
    steps, path, edges = trace(f)
    print(render_walkthrough(args.case, f, steps))

    if args.diagram:
        out = args.out or f"diagrams/decision-chain-{args.case}.mmd"
        Path(out).write_text(render_mermaid(f, path, edges), encoding="utf-8")
        print(f"\n高亮图已写：{out}")


if __name__ == "__main__":
    main()
