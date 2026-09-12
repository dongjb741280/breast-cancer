"""图节点：确定性节点（读文件/抽取）+ LLM 判断节点（结构化输出）。

每个 LLM 节点 = 一段 prompt（内嵌 skill 里的判读规则/红线/报告模板）+ with_structured_output。
"""
from __future__ import annotations

import json
from typing import Any

from langchain_anthropic import ChatAnthropic

import config
from extractor import extract_features, load_patient
from schemas import (
    DecisionChainStep,
    DiagnosisReport,
    MolecularSubtype,
    RedLineFlag,
    Staging,
)

# ---------- 工具 ----------

def _llm():
    kwargs = {
        "model": config.ANTHROPIC_MODEL,
        "temperature": 0,
        "thinking": {"type": "disabled"},  # 网关模型默认扩展思考，会与强制 tool_choice（结构化输出）冲突
    }
    if config.ANTHROPIC_BASE_URL:
        kwargs["base_url"] = config.ANTHROPIC_BASE_URL
    return ChatAnthropic(**kwargs)


def _features_block(f) -> str:
    return "\n".join(
        x for x in [
            f"性别：{f.gender or '未记录'}",
            f"年龄：{f.age or '未记录'}",
            f"诊断：{'、'.join(f.diagnoses) if f.diagnoses else '未记录'}",
            f"病理：\n{f.pathology_text or '（未记录）'}",
            f"TNM/分期线索：{f.tnm_text or '（未记录）'}",
            f"治疗：\n{f.treatment_text or '（未记录）'}",
            f"影像：\n{f.imaging_text or '（未记录）'}",
            f"检验：\n{f.labs_text or '（未记录）'}",
            f"叙事：\n{f.narrative_text or '（未记录）'}",
        ]
    )


def _guide_block(sections: list[str]) -> str:
    return "\n\n---\n\n".join(sections) if sections else "（指南未检索到）"


# ---------- 确定性节点 ----------

def load_patient_node(state: dict[str, Any]) -> dict[str, Any]:
    path = state["patient_path"]
    pd = load_patient(path)
    case_id = pd.get("standard_patient", {}).get("patient_id") or state.get("case_id", "unknown")
    return {"case_id": case_id, "patient_data": pd}


def extract_features_node(state: dict[str, Any]) -> dict[str, Any]:
    return {"features": extract_features(state["patient_data"])}


def retrieve_guide_node(state: dict[str, Any]) -> dict[str, Any]:
    from guide_rag import GuideRetriever, build_query
    # 轻量缓存：把 retriever 挂到 state 不合适，这里每次构建（节点内闭包会重复建索引）
    # 生产建议：构建一次，注入节点；demo 用模块级单例
    global _RETRIEVER
    if _RETRIEVER is None:
        _RETRIEVER = GuideRetriever()
    q = build_query(state["features"])
    sections = _RETRIEVER.retrieve(q)
    return {"guide_sections": sections}


_RETRIEVER = None  # 模块级缓存（避免重复建索引）


# ---------- LLM 判断节点（结构化输出） ----------

def judge_subtype_node(state: dict[str, Any]) -> dict[str, Any]:
    f = state["features"]
    prompt = f"""你是乳腺癌分子分型判读助手。依据病历证据 + 指南片段，判读分子分型。

判读规则（务必遵守）：
- HER2 IHC 3+ 或 FISH/ISH 扩增 → HER2 阳性型（IHC 3+ 优先于 FISH：FISH 阴性但 IHC 3+ 仍判阳性）
- HER2 IHC 1+，或 IHC 2+ 且 FISH 阴性 → HER2 低表达型
- HER2 IHC 0 但 ≤10% 浸润癌细胞不完整微弱膜染色 → HER2 超低表达（≠简单阴性）
- ER/PR ≥1% → HR 阳性；ER- PR- HER2- → 三阴；写 Luminal → HR 阳性(Luminal)
- Luminal A：HER2-、ER+、PR 高表达、Ki-67<14%；Luminal B(HER2-)：ER+、PR 低或-、Ki-67 高；Luminal B(HER2+)：HER2+、ER+
- 双侧乳腺 / 原发 vs 转移灶受体不一致时，分开说明，以主导病灶为准
- 未提供 ≠ 阴性：没写就留空/说明「未记录」，绝不默认判阴性

【病历证据】
{_features_block(f)}

【指南片段】
{_guide_block(state.get("guide_sections", []))}
"""
    return {"subtype": _llm().with_structured_output(MolecularSubtype).invoke(prompt)}


def judge_staging_node(state: dict[str, Any]) -> dict[str, Any]:
    f = state["features"]
    prompt = f"""你是乳腺癌分期助手。区分初始 vs 当前分期，判 M 状态。

规则：
- 初始 = 最早记录；当前 = 最近（复发/转移后常 M1/Ⅳ期）
- OCR 的 MO → M0；术后病理用 ypT/N（如 ypT2N1a）
- 疑似转移但无活检/PET 确认 → m_status=待核实（不要硬定 M0/M1）

【病历证据】
{_features_block(f)}
"""
    return {"staging": _llm().with_structured_output(Staging).invoke(prompt)}


def check_red_lines_node(state: dict[str, Any]) -> dict[str, Any]:
    f = state["features"]
    subtype = state.get("subtype")
    staging = state.get("staging")
    prompt = f"""你是安全红线检查助手。逐条对照下列红线，命中才输出（没命中返回空列表）。

红线清单：
1. M 分期可疑未确诊（疑似转移但无活检/PET 确认）
2. 下颌/颌骨病变（骨改良药使用者，需鉴别骨转移 vs 药物相关颌骨坏死 vs 感染）
3. 严重骨髓抑制（重度血象下降、粒细胞缺乏、血小板显著降低）
4. 脑膜转移（「脑膜转移/软脑膜/鞘内」）
5. 内脏危象（快速进展的肝/肺等内脏转移伴器官功能受损）

【已判结果】分型={subtype.subtype if subtype else '未判'}；M={staging.m_status if staging else '未判'}
【病历证据】
{_features_block(f)}
"""
    llm = _llm().with_structured_output(RedLineFlag)
    # 用多次调用收集红线（简化：单次结构化输出一个 flag，循环直到空）
    # 生产建议用 list 输出；这里用「分多次」的明确写法便于演示
    flags = []
    for _ in range(4):
        flag = llm.invoke(prompt + "\n\n只输出当前仍存在的最高优先级红线；若已无红线，输出 description='__NONE__'。")
        if not flag or flag.description.strip() == "__NONE__":
            break
        flags.append(flag)
        prompt += f"\n（已记录红线：{flag.kind}，继续找下一条）"
    return {"red_lines": flags}


def trace_chain_node(state: dict[str, Any]) -> dict[str, Any]:
    f = state["features"]
    subtype = state.get("subtype")
    staging = state.get("staging")
    prompt = f"""你是 CSCO 乳腺癌决策链（A→U）追踪助手。只走该病例实际命中的节点，
每个节点给：节点标签 + 走的分支（分支节点才有）+ 病历证据（一句原文/指标）。

决策链节点：A 初诊乳腺癌 / B 影像+病理+分子标志物 / C TNM分期+分子分型 / D M分期有无远处转移 /
E 是否适合新辅助 / F 新辅助方案 / G 直接手术 / H 手术+病理反应 / I pCR还是残余 / J 术后辅助 /
K 强化辅助 / L 放疗+内分泌+抗HER2+免疫 / M 转移灶再活检 / N 评估既往治疗+治疗线+安全性 /
O 序贯全身治疗 / P 特殊转移部位 / Q 骨改良药+局部 / R 脑实质or脑膜 / R1 脑实质局部治疗 /
R2 脑膜治疗 / S 继续系统治疗 / T 疗效评估+毒性+MDT / U 长期随访。

【已判结果】分型={subtype.subtype if subtype else '未判'}；M={staging.m_status if staging else '未判'}
【病历证据】
{_features_block(f)}
"""
    llm = _llm().with_structured_output(DecisionChainStep)
    # 逐节点生成，直到 LLM 返回空（node='__END__'）
    path: list[DecisionChainStep] = []
    seen: set[str] = set()
    for _ in range(24):
        step = llm.invoke(prompt + f"\n\n已走节点：{list(seen)}。给出下一步命中的节点；若已到 U 则 node='__END__'。")
        if not step or step.node == "__END__":
            break
        if step.node in seen:
            break
        seen.add(step.node)
        path.append(step)
    return {"chain_path": path}


def write_report_node(state: dict[str, Any]) -> dict[str, Any]:
    f = state["features"]
    subtype = state.get("subtype")
    staging = state.get("staging")
    chain = state.get("chain_path", [])
    chain_txt = "\n".join(f"[{s.node}] {s.branch or ''} → {s.evidence}" for s in chain)
    prompt = f"""你是乳腺肿瘤科医生助手，产出一份 9 节综合诊断报告（结构化字段）。

【已判结果】
分型={subtype.subtype if subtype else '未判'}；M={staging.m_status if staging else '未判'}
决策链：\n{chain_txt}

【病历证据】
{_features_block(f)}

【指南片段】
{_guide_block(state.get("guide_sections", []))}

要求：推荐等级写 Ⅰ/Ⅱ/Ⅲ 级，证据类别写 1A/1B/2A/2B/3；治疗评价用 ✓/△/⚠；不替未记录环节脑补。
"""
    return {"report": _llm().with_structured_output(DiagnosisReport).invoke(prompt)}


# ---------- 人机协同节点（interrupt） ----------

def human_review_node(state: dict[str, Any]) -> dict[str, Any]:
    """红线复核：命中红线时暂停，人工决定 proceed(继续并备注) / stop / revise。"""
    from langgraph.types import interrupt
    decision = interrupt({
        "type": "red_line_review",
        "red_lines": [f.model_dump() for f in state.get("red_lines", [])],
        "hint": "红线命中，请人工复核：proceed=继续但已人工评估 / stop=终止 / revise=补充信息后重跑",
    })
    return {"human_decision": json.dumps(decision, ensure_ascii=False)}


def human_approve_node(state: dict[str, Any]) -> dict[str, Any]:
    """报告终审：报告生成后暂停，人工 approve / revise。"""
    from langgraph.types import interrupt
    decision = interrupt({
        "type": "report_approval",
        "report": state.get("report").model_dump() if state.get("report") else {},
    })
    return {"human_decision": json.dumps(decision, ensure_ascii=False)}
