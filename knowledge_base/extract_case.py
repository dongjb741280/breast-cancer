"""从病历 JSON 抽病例文本（供 agent 判断）。7 例 REAL 全覆盖。"""
import json

CASE_JSON = {
    "REAL-001": "Data_Cleaning/doc/系统输入/REAL-001-严格标准版.json",
    "REAL-002": "Data_Cleaning/doc/系统输入/REAL-002-严格标准版.json",
    "REAL-003": "Data_Cleaning/doc/系统输入/REAL-003-大悟县首程-脱敏映射.json",
    "REAL-004": "Data_Cleaning/doc/系统输入/REAL-004-首程2-脱敏映射.json",
    "REAL-005": "Data_Cleaning/doc/系统输入/REAL-005-首程3-脱敏映射.json",
    "REAL-006": "Data_Cleaning/doc/系统输入/REAL-006-深圳南山入院-严格标准版.json",
    "REAL-007": "Data_Cleaning/doc/系统输入/REAL-007-深圳南山入院-严格标准版.json",
}


def extract_case_text(path):
    pd = json.load(open(path, encoding="utf-8"))["patient_data"]
    parts = []
    sp = pd.get("standard_patient") or {}
    gender = sp.get("standard_gender", "")
    age = ""
    for x in pd.get("diagnosis", []):
        if x.get("standard_age") is not None or x.get("original_age") is not None:
            age = x.get("standard_age") or x.get("original_age")
            break
    parts.append(f"性别:{gender} 年龄:{age}")

    diags = []
    for x in pd.get("diagnosis", []):
        n = x.get("standard_name") or x.get("original_diagnosis_name")
        if n:
            diags.append(n)
    parts.append("诊断: " + "、".join(dict.fromkeys(diags)))

    taken = {}
    for doc in pd.get("standard_inpatient_documentations", []):
        n = doc.get("documentary_type") or doc.get("record_item_name") or doc.get("standard_record_item_name") or ""
        kind = None
        if "入院记录" in n:
            kind = "入院记录"
        elif "首次病程" in n or "首程记录" in n or "首程" in n:
            kind = "首程/首次病程"
        elif "出院记录" in n or "出院小结" in n:
            kind = "出院"
        if kind and kind not in taken:
            rt = doc.get("record_text") or ""
            taken[kind] = f"[{n}]\n{rt[:2000]}"

    for kind in ("入院记录", "首程/首次病程", "出院"):
        if kind in taken:
            parts.append(taken[kind])

    return "\n\n".join(parts)
