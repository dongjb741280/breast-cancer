"""决策链追踪：病历 JSON → 抽取特征 → 逐节点走通诊疗决策链。

特征抽取优先走 LLM（见 llm.py，需 HH_API_KEY），LLM 不可用时回退正则兜底。
输入为「系统输入」目录下的标准病历 JSON，
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
    ("F", "H", ""), ("G", "J", ""),
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
    """拼接叙事文本（入院/病程/出院/摘要等），排除知情同意类模板。"""
    docs = pd.get("standard_inpatient_documentations", [])
    picked = []
    for doc in docs:
        name = doc.get("standard_record_item_name") or doc.get("record_item_name") or ""
        rt = doc.get("record_text") or doc.get("original_record_text") or ""
        if not rt:
            continue
        if any(k in name for k in ("知情", "告知", "同意", "委托", "授权", "确认", "证明", "首页")):
            continue
        picked.append(rt)
    return "\n".join(picked)


def _diagnoses(pd):
    names = []
    for x in pd.get("diagnosis", []):
        n = x.get("standard_name") or x.get("original_diagnosis_name")
        if n and n not in names:
            names.append(n)
    return names


def _extract_tx(text):
    """按给药语境提取治疗，区分当前/既往，排除知情同意/方案模板。"""
    CATS = [
        ("抗HER2靶向", r"曲妥珠单抗|帕妥珠单抗|吡咯替尼|拉帕替尼|图卡替尼|奈拉替尼|抗HER-?2靶向|抗Her-?2靶向"),
        ("内分泌", r"阿那曲唑|来曲唑|他莫昔芬|依西美坦|托瑞米芬|氟维司群|戈舍瑞林|内分泌治疗"),
        ("化疗", r"多西他赛|多西他塞|紫杉|卡培他滨|表柔比星|环磷酰胺|吉西他滨|长春瑞滨|艾立布林|卡铂|顺铂|化疗"),
        ("放疗", r"放疗"),
        ("骨改良药", r"唑来膦酸|地舒单抗|骨改良|骨保护"),
    ]
    CUR = r"至今|当前|目前|现在|维持|继续|正在|长期|规律|定期|\d+天/次"
    PAST = r"既往|曾予|曾行|已予|已完成|术后|序贯|后行|外院|此前|当时|至\s*20\d\d|至\d{4}年"

    cur, past = set(), set()
    for s in re.split(r"[。；;\n]", text):
        if re.search(r"上述方案|方案中|知情|告知|委托|授权|同意书", s):
            continue
        is_cur = bool(re.search(CUR, s)) and not re.search(r"至\s*(20\d\d|\d{4}年)", s)
        is_past = bool(re.search(PAST, s)) or (re.search(r"于\s*20\d\d", s) and not is_cur)
        for name, pat in CATS:
            if re.search(pat, s):
                if is_cur:
                    cur.add(name)
                elif is_past:
                    past.add(name)
    return {"当前": sorted(cur), "既往": sorted(past - cur)}


LLM_SCHEMA = """{
  "分子分型": "HER2阳性型 | HER2低表达型 | 三阴性 | HR阳性/HER2阴性 | HR阳性(Luminal) | 未知",
  "ER": "原文证据，如 ER(90%,3+) / ER/PR约85%阳性 / ER(-)，缺省给 -",
  "PR": "原文证据，如 PR(40%,2+) / PR小灶(+) / PR约85%阳性，缺省给 -",
  "HER2": "原文证据，如 HER-2(3+) / HER2 IHC 1+ / CerbB-2(+) / HER2阴性，缺省给 -",
  "Ki67": "原文证据，如 Ki67(30%) / Ki67约20%，缺省给 -",
  "FISH": "FISH扩增阳性 | FISH扩增阴性 | -",
  "初始TNM": "最早一次 TNM，如 cT2N2M1 / pT2N1M0，缺省空字符串",
  "初始分期": "最早一次分期，如 Ⅳ期 / IIB期，缺省空字符串",
  "当前TNM": "最近一次 TNM（复发/转移后常为 M1），缺省空字符串",
  "当前分期": "最近一次分期，缺省空字符串",
  "转移部位": ["肝","骨","脑","肺","肾上腺","胸膜"]，无转移给空数组",
  "是否远处转移": true,
  "M分期待核实": false,
  "是否新辅助": false,
  "是否手术": true,
  "pCR": null,
  "non_pCR": null,
  "当前治疗": ["抗HER2靶向","内分泌","化疗","放疗","骨改良药"]，无给空数组",
  "既往治疗": ["抗HER2靶向","内分泌","化疗","放疗","骨改良药"]，无给空数组"
}"""


def _normalize_llm(d):
    """把 LLM 返回的字段规整成内部结构，容忍缺省/类型差异。"""
    def s(k):
        v = d.get(k)
        return v if isinstance(v, str) else ("" if v is None else str(v))

    def b(k):
        v = d.get(k)
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("true", "是", "yes", "1", "阳性", "有")
        return bool(v)

    def lst(k):
        v = d.get(k)
        if isinstance(v, list):
            return [str(x) for x in v]
        if isinstance(v, str) and v.strip():
            return [v.strip()]
        return []

    sites = lst("转移部位")
    return {
        "subtype": s("分子分型") or "未知",
        "er": s("ER"), "pr": s("PR"), "her2": s("HER2"), "ki67": s("Ki67"), "fish": s("FISH"),
        "tnm": s("初始TNM"), "stage": s("初始分期"),
        "tnm_latest": s("当前TNM"), "stage_latest": s("当前分期"),
        "sites": sites,
        "m1": b("是否远处转移") or bool(sites),
        "m_uncertain": b("M分期待核实"),
        "neoadjuvant": b("是否新辅助"), "surgery": b("是否手术"),
        "pcr": b("pCR"), "non_pcr": b("non_pCR"),
        "tx": {"当前": lst("当前治疗"), "既往": lst("既往治疗")},
    }


def _extract_llm(text):
    """LLM 抽取结构化特征（优先，替代正则）。"""
    from llm import chat  # 懒加载：无 requests/HH_API_KEY 时由正则兜底
    prompt = f"""你是乳腺癌诊疗决策链的特征抽取器。从病历摘要中提取结构化字段，只输出一个 JSON 对象（不要解释、不要 markdown 代码块）。

病历摘要：
{text}

字段（严格按此结构；缺省给 null 或空）：
{LLM_SCHEMA}

判定要点：
- 分子分型按指南：HER2 IHC 3+ 或 FISH/ISH 扩增→HER2阳性型；IHC 1+ 或 2+/FISH阴性→HER2低表达型；ER/PR≥1%→HR阳性；ER- PR- HER2阴性→三阴性；诊断结论写 Luminal 则→HR阳性(Luminal)。
- 双侧乳腺或原发灶/转移灶受体不一致时，以驱动治疗的主导病灶为准，并在 ER/PR/HER2 证据里注明「原发…/转移灶…」。
- 初始TNM/分期=最早记录；当前TNM/分期=最近记录（复发/转移后常为 M1/IV期）。
- 治疗分当前/既往：当前=至今/维持/继续/目前/现给予；既往=术后/序贯/年份/曾/外院。知情同意书里的备选方案、随访模板文字不算。
- 不要编造，病历未提及就留空或给 null。"""
    return _normalize_llm(chat(prompt))


def _extract_regex(text, diags):
    """正则兜底的特征抽取（LLM 不可用时）。"""
    # TNM + 分期（区分初始/当前）；MO→M0 纠正 OCR 误写
    tnms = [t.replace("MO", "M0") for t in re.findall(r"[cpay]?T[0-9xXO]N[0-9xXO]M[0-9xXO]", text)]
    stages = re.findall(r"(?:IV|Ⅳ|Ⅲ|III|Ⅱ|II|Ⅰ|I)A?B?C?期", text)
    tnm = tnms[0] if tnms else ""           # 初始 TNM
    stage = stages[0] if stages else ""      # 初始分期
    tnm_latest = tnms[-1] if tnms else ""
    stage_latest = stages[-1] if stages else ""

    # 分子标志物（原始 IHC 证据，兼容括号/加号/自由文本）
    def _find_any(patterns):
        for p in patterns:
            mm = re.search(p, text)
            if mm:
                return mm.group(0)
        return ""

    er = _find_any([
        r"(?<!H)ER[^，。;；()（）]{0,3}[（(][^）)]*[）)]",   # ER(90%) / ER(++)
        r"(?<!H)ER\s*/\s*PR[^。；，;]{0,8}(阳性|强阳)",    # ER/PR约85%阳性
        r"(?<!H)ER[^。；，;]{0,6}(阳性|强阳)",              # ER阳性
    ])
    pr = _find_any([
        r"PR[^，。;；()（）]{0,3}[（(][^）)]*[）)]",        # PR(80%) / PR小灶(+)
        r"PR[^。；，;]{0,8}(阳性|强阳)",                     # PR约85%阳性
    ])
    her2 = _find_any([
        r"HER-?2\s*[（(][^）)]*[）)]",                      # HER2(3+)
        r"CerbB-?2\s*[（(][^）)]*[）)]",                     # CerbB-2(+)
        r"HER-?2\s*(?:IHC\s*)?\d\+",                        # HER2 IHC 1+
        r"HER-?2\s*(阴性|阳性)",                             # HER2阴性
    ])
    ki67 = _find_any([
        r"[Kk]i-?67\s*[（(][^）)]*[）)]",                  # Ki67(30%)
        r"[Kk]i-?67\s*约?\s*\d+\s*%",                       # Ki67 30% / Ki67约20%
    ])
    fish = ""
    if re.search(r"FISH[^。；]*扩增\s*阴性|FISH[^。；]*阴性", text):
        fish = "FISH扩增阴性"
    elif re.search(r"FISH[^。；]*扩增\s*阳性|ISH\s*阳性", text):
        fish = "FISH扩增阳性"

    # 分子分型（优先读诊断结论，其次按 IHC 规则判读）
    def _pos(s):
        # ER/PR 阳性：含 + 号，或数字 ≥1（% / 分）
        if not s:
            return False
        if "+" in s:
            return True
        m = re.search(r"(\d+)", s)
        return bool(m) and int(m.group(1)) >= 1

    def _her2_level(s):
        # +++/3+ → 3；++/2+ → 2；+/1+ → 1；-/0 → 0
        if not s:
            return None
        raw = re.search(r"[（(]([^）)]*)[）)]", s)
        raw = raw.group(1) if raw else s
        if re.search(r"\+\+\+", raw) or re.search(r"3\+", raw):
            return 3
        if re.search(r"\+\+", raw) or re.search(r"2\+", raw):
            return 2
        if re.search(r"\+", raw) or re.search(r"1\+", raw):
            return 1
        return 0

    # 自由文本 HER2 等级（"HER2 IHC 1+" / "HER2阴性"）
    def _her2_free():
        m = re.search(r"HER-?2\s*(?:IHC\s*)?(\d)\+", text)
        if m:
            return int(m.group(1))
        if re.search(r"HER-?2\s*阴性|HER-?2\s*[（(]?\s*[-0]", text):
            return 0
        return None

    # 自由文本 HR 阳性（"ER/PR约85%阳性" / "HR阳性" 等）
    def _hr_free():
        if re.search(r"HR\s*阳性|Luminal|Lumianl|管腔", text):
            return True
        if re.search(r"(?<!H)(?:ER|PR)[^。；，;]{0,10}(阳性|强阳)", text):
            return True
        if re.search(r"ER\s*/\s*PR[^。；，;]{0,6}\d+\s*%", text):
            return True
        return False

    subtype = ""
    for kw, label in (("HER2阳性型", "HER2阳性型"), ("HER2低表达", "HER2低表达型"),
                      ("三阴性", "三阴性"), ("三阴型", "三阴性"),
                      ("Luminal", "HR阳性(Luminal)"), ("Lumianl", "HR阳性(Luminal)"),
                      ("管腔", "HR阳性(管腔)")):
        if kw in text:
            subtype = label
            break
    if not subtype:
        if "扩增阳性" in fish or "ISH阳性" in fish:
            subtype = "HER2阳性型"
        else:
            hr_pos = _pos(er) or _pos(pr) or _hr_free()
            lv = _her2_level(her2)
            if lv is None:
                lv = _her2_free()
            if lv == 3:
                subtype = "HER2阳性型"
            elif lv == 2:
                subtype = "HER2阳性型" if "扩增阳性" in fish else ("HER2低表达型" if "阴性" in fish else "HER2待核验(IHC2+)")
            elif lv == 1:
                subtype = "HR阳性/HER2低表达" if hr_pos else "HER2低表达型"
            else:  # HER2 阴性（- / 0 / 0分）
                subtype = "三阴性" if not hr_pos else "HR阳性/HER2阴性"

    # 转移部位：只在「X继发恶性肿瘤 / X转移」语境下命中，避免误伤体检/正常描述
    sites = []
    blob = " ".join(diags) + " " + text
    for kw, site in (("肝", "肝"), ("骨", "骨"), ("脑", "脑"), ("颅内", "脑"),
                     ("肺", "肺"), ("肾上腺", "肾上腺"), ("胸膜", "胸膜")):
        if re.search(kw + r"\s*(继发恶性肿瘤|转移瘤|转移灶|转移)", blob) and site not in sites:
            sites.append(site)

    m1 = bool(sites) or any("M1" in t for t in tnms) or any(s.startswith(("IV", "Ⅳ")) for s in stages)
    m_uncertain = (not m1) and bool(re.search(r"疑似转移|转移[^。；，)]{0,6}待", blob))

    # 早期阶段处理方式
    neoadjuvant = bool(re.search(r"新辅助", text))
    surgery = bool(re.search(r"切除术|根治术|保乳术|前哨淋巴结活检|腋窝淋巴结清扫|全乳切除", text))
    pcr = bool(re.search(r"pCR|病理学完全缓解|MP\s*5\s*级|RCB\s*0", text))
    non_pcr = bool(re.search(r"non-?pCR|非pCR|未达pCR|未达病理学完全缓解|残余病灶|RCB\s*[IⅡⅢ]", text))

    # 治疗（区分当前/既往）
    tx = _extract_tx(text)

    return {
        "tnm": tnm, "stage": stage, "tnm_latest": tnm_latest, "stage_latest": stage_latest,
        "subtype": subtype, "er": er, "pr": pr, "her2": her2, "ki67": ki67, "fish": fish,
        "sites": sites, "m1": m1, "m_uncertain": m_uncertain, "tx": tx,
        "neoadjuvant": neoadjuvant, "surgery": surgery, "pcr": pcr, "non_pcr": non_pcr,
    }


def extract(pd):
    """结构化字段（性别/年龄/诊断）+ 叙事特征（LLM 优先，正则兜底）。"""
    sp = pd.get("standard_patient") or {}
    gender = sp.get("standard_gender", "")
    age = next((x.get("standard_age") or x.get("original_age")
                for x in pd.get("diagnosis", []) if x.get("standard_age") is not None), "")
    text = _narrative(pd)
    diags = _diagnoses(pd)

    try:
        feat = _extract_llm(text)
    except Exception:
        feat = _extract_regex(text, diags)

    return {"gender": gender, "age": age, "diags": diags, "text": text, **feat}


def _staging(f):
    """格式化分期显示：区分初始 vs 当前（复发/转移后 M1）。"""
    init = f"{f['tnm']} {f['stage']}".strip()
    latest = f"{f['tnm_latest']} {f['stage_latest']}".strip()
    if not init:
        return "M1（多发转移）" if f["m1"] else ""
    if latest and latest != init:
        return f"{init} → {latest}"
    if f["m1"] and "M1" not in init:
        return f"{init} → M1（复发/转移）"
    return init


def trace(f):
    """返回 (steps, path_nodes, path_edges)。step = (node, evidence, branch)。"""
    steps = []
    steps.append(("A", "右乳/腋下肿块，穿刺确诊浸润性癌", ""))
    steps.append(("B", f"彩超/CT/MR/ECT + 穿刺病理 + IHC（{f['her2'] or '见病历'}）", ""))
    steps.append(("C", _staging(f), ""))

    path = ["A", "B", "C"]
    resolved = True
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
    elif f.get("m_uncertain"):
        steps.append(("D", "M分期待核实（疑似转移，需活检/PET确认）", "待核实"))
        path.append("D")
        resolved = False
    else:
        steps.append(("D", "无远处转移", "否：M0 早期/局部进展期"))
        steps.append(("E", "是否适合新辅助治疗（肿块大/LN+/HER2+/三阴/保乳意愿）", ""))
        path += ["D", "E"]
        if f["neoadjuvant"]:
            steps.append(("F", "按分子亚型选择新辅助方案", "是"))
            steps.append(("H", "手术 + 病理反应评估", ""))
            path += ["F", "H"]
            if f["pcr"]:
                steps.append(("I", "达到病理学完全缓解", "pCR"))
                steps.append(("J", "按风险完成术后辅助治疗", ""))
                path += ["I", "J"]
            elif f["non_pcr"]:
                steps.append(("I", "残余病灶", "non-pCR"))
                steps.append(("K", "强化辅助（HER2+/三阴）", ""))
                path += ["I", "K"]
            else:
                steps.append(("I", "pCR/non-pCR 需病理反应记录（MP/RCB/ypTNM）", ""))
                path.append("I")
            steps.append(("L", "放疗 / 内分泌 / 抗HER2 / 免疫等", ""))
            path.append("L")
        elif f["surgery"]:
            steps.append(("G", "直接手术 + 腋窝评估", "否"))
            steps.append(("J", "按风险完成术后辅助治疗", ""))
            steps.append(("L", "放疗 / 内分泌 / 抗HER2 / 免疫等", ""))
            path += ["G", "J", "L"]
        else:
            resolved = False

    if resolved:
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
             f"TNM/分期：{_staging(f)}",
             f"分子分型：{f['subtype'] or '未知'}   ER {f['er'] or '-'}  PR {f['pr'] or '-'}  HER2 {f['her2'] or '-'}  Ki67 {f['ki67'] or '-'}  {f['fish']}",
             f"转移部位：{'、'.join(f['sites']) or '无'}",
             "治疗：" + ("；".join(f"{k}：{' + '.join(v)}" for k, v in f['tx'].items() if v) or "未提取到"),
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
