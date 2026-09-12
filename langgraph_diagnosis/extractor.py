"""确定性字段抽取：把 patient_data JSON 里带临床信号的字段抽成原始证据文本。

对应 skill 第三步的「字段→特征映射」：结构化为权威、叙事兜底。
这里只做「抽取」（把文本从异构字段里捞出来），不做「判断」（判断交给 LLM）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from schemas import PatientFeatures

# 叙事文书里要跳过的模板（知情同意/授权委托等），skill 第三步明确排除
_SKIP_ITEMS = {
    "授权委托书", "患者告知书", "患者住院须知", "患者基本信息登记确认表",
    "住院病人基本信息确认卡", "入院48小时知情告知书", "分级诊疗政策知情告知书",
    "电子结肠镜检查知情同意书", "电子胃镜检查知情同意书", "特殊检查/治疗知情同意书",
    "化疗知情同意书", "肿瘤内科化疗知情同意书", "授权同意类", "入院登记处",
}

# 叙事文书里要保留的临床文档类型关键词
_KEEP_TYPES = ("入院记录", "首次病程", "病程记录", "出院", "查房", "会诊", "诊断")


def load_patient(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["patient_data"]


def _first(items: list[Any], *keys: str) -> Any:
    for it in items:
        for k in keys:
            if k in it and it[k] not in (None, "", [], {}):
                return it[k]
    return None


def extract_features(pd: dict[str, Any]) -> PatientFeatures:
    f = PatientFeatures()

    # 性别（standard_patient）
    sp = pd.get("standard_patient", {})
    f.gender = sp.get("standard_gender") or sp.get("original_gender")

    # 诊断列表 + 年龄（diagnosis[]）
    diag = pd.get("diagnosis", [])
    names: list[str] = []
    for d in diag:
        name = d.get("standard_name") or d.get("original_diagnosis_name")
        if name and name not in names:
            names.append(name)
    f.diagnoses = names
    f.age = _first(diag, "standard_age", "original_age")

    # 病理（standard_pathology_reports[]）——分子分型最权威来源
    path = pd.get("standard_pathology_reports", [])
    if path:
        parts = []
        for p in path:
            pd_ = p.get("pathology_diagnosis") or ""
            desc = p.get("pathology_description") or ""
            site = p.get("specimen_site") or ""
            if pd_:
                parts.append(f"[{site}] {pd_}")
            if desc:
                parts.append(desc)
        f.pathology_text = "\n".join(x for x in parts if x)

    # 手术（standard_final_operation_records[]）
    op = pd.get("standard_final_operation_records", [])
    if op:
        f.tnm_text += "\n" + str(_first(op, "operation_description", "pathology_result", "record_text") or "")

    # 影像（examine_items[]）
    exam = pd.get("examine_items", [])
    if exam:
        rows = []
        for e in exam:
            item = e.get("standard_item_name") or e.get("original_item_name") or ""
            res = e.get("original_result") or e.get("original_description") or ""
            if item or res:
                rows.append(f"{item}：{res}")
        f.imaging_text = "\n".join(rows)

    # 检验（laboratories[]）——只保留异常/关键项
    labs = pd.get("laboratories", [])
    if labs:
        rows = []
        for l in labs:
            name = l.get("original_laboratory_name") or l.get("standard_laboratory_name")
            res = l.get("original_result")
            ref = l.get("original_reference")
            abn = l.get("original_abnormal_indicator")
            if name and (res is not None or abn):
                rows.append(f"{name}: {res} (参考 {ref}){' [异常:'+str(abn)+']' if abn else ''}")
        f.labs_text = "\n".join(rows)

    # 叙事文书（standard_inpatient_documentations[]）——兜底
    docs = pd.get("standard_inpatient_documentations", [])
    kept: list[str] = []
    for d in docs:
        item = d.get("record_item_name") or d.get("standard_record_item_name") or ""
        dtype = str(d.get("documentary_type") or d.get("standard_documentary_type_list") or "")
        # 跳过模板
        if any(s in item or s in dtype for s in _SKIP_ITEMS):
            continue
        txt = d.get("record_text") or d.get("record_text_edit") or d.get("original_record_text") or ""
        if txt:
            kept.append(f"【{item or dtype}】{txt}")
    f.narrative_text = "\n\n".join(kept)

    # 治疗时间轴线索：从叙事 + 诊断 + 医嘱里捞「当前/既往」关键词句
    f.treatment_text = _extract_treatment(pd)

    # TNM 线索：诊断名 + 叙事里带 pT/cT/期 的片段
    f.tnm_text = (_extract_tnm(names, f.narrative_text) + f.tnm_text).strip()

    return f


def _extract_treatment(pd: dict[str, Any]) -> str:
    """粗略捞出治疗方案片段（当前 vs 既往的精确区分交给 LLM）。"""
    chunks: list[str] = []
    for d in pd.get("diagnosis", []):
        name = d.get("standard_name") or d.get("original_diagnosis_name") or ""
        if any(k in name for k in ("靶向治疗", "内分泌治疗", "化疗", "支持治疗", "中医治疗")):
            chunks.append(f"[诊断-治疗] {name}")
    meds = pd.get("recipe_medicines", [])
    for m in meds:
        name = m.get("standard_drug_name") or m.get("drug_name") or m.get("medicine_name")
        if name:
            chunks.append(f"[医嘱] {name}")
    return "\n".join(chunks)


def _extract_tnm(diag_names: list[str], narrative: str) -> str:
    """从诊断名和叙事里捞 TNM/分期相关片段。"""
    out: list[str] = []
    for n in diag_names:
        if any(k in n for k in ("继发", "转移", "恶性肿瘤")) and any(k in n for k in ("期", "M1")):
            out.append(n)
    # 叙事里的分期片段
    import re
    for m in re.findall(r"[cpy]?T\w*N\w*M[01x]+\s*[ⅠⅡⅢⅣ]*期?", narrative):
        out.append(m)
    return " ".join(out)
