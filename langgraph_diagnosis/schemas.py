"""Pydantic 模型：结构化输出（LLM 判断结果）＋ 图状态。

结构化输出 = 把 skill 里的「判读规则/红线/报告模板」变成强类型字段，
LLM 用 with_structured_output 生成，下游可校验、可对照金标准评测。
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


# ---------- 结构化输出 ----------

class MolecularSubtype(BaseModel):
    """分子分型判读（skill 第三步的 HER2/ER/PR/Ki67 判读规则）。"""
    er: str | None = Field(None, description="ER 原始证据，如 '98%+' / '阴性'；未记录为 None")
    pr: str | None = Field(None, description="PR 原始证据")
    her2: str | None = Field(None, description="HER2 IHC/FISH 原始值，如 'IHC 3+' / 'FISH 扩增' / 'IHC 1+'")
    ki67: str | None = Field(None, description="Ki-67 原始值，如 '30%'")
    fish: str | None = Field(None, description="FISH/ISH 结果，如 '扩增阳性' / '阴性' / None")
    subtype: str = Field(..., description="HER2阳性型 / 三阴型 / Luminal A / Luminal B(HER2-) / Luminal B(HER2+) / HER2低表达")
    is_her2_low: bool = Field(False, description="是否 HER2 低表达（IHC 1+，或 IHC 2+ 且 FISH 阴性）")
    rationale: str = Field(..., description="判读理由，须指回原文证据；未提供≠阴性")


class Staging(BaseModel):
    """TNM/分期（区分初始 vs 当前）。"""
    initial_tnm: str | None = Field(None, description="初始分期，如 'cT4N3M0 ⅡIC期' / 'pT2N1M0 ⅡB期'")
    current_tnm: str | None = Field(None, description="当前分期（复发/转移后常 M1/Ⅳ期）")
    m_status: Literal["M0", "M1", "待核实"] = "M0"
    note: str = Field("", description="M 分期可疑未确诊时说明")


class RedLineFlag(BaseModel):
    """安全红线（skill「不确定性与红线」）。命中则转人工，不机械往下走。"""
    kind: Literal["M待核实", "下颌病变", "骨髓抑制", "脑膜转移", "内脏危象", "其他"] = "其他"
    description: str = Field(..., description="红线描述 + 病历证据")
    action: str = Field(..., description="应如何处理（先处理安全性 / 转 CNS MDT / 补活检 / 停）")


class DecisionChainStep(BaseModel):
    """A→U 决策链一步（skill 第五步）。"""
    node: str = Field(..., description="节点 A..U")
    branch: str | None = Field(None, description="分支（分支节点才有），如 '是：M1（肝、骨）'")
    evidence: str = Field(..., description="病历原文证据")


class DiagnosisReport(BaseModel):
    """9 节诊断报告（skill 第四步模板）。"""
    patient_info: str = Field(..., description="患者信息一行")
    main_diagnosis: list[str] = Field(..., description="主要诊断，按主次")
    molecular_table: str = Field(..., description="病理与分子分型依据（markdown 表格）")
    tnm_staging: str = Field(..., description="TNM 分期：初始 → 当前")
    treatment_timeline: str = Field(..., description="诊疗经过时间轴（markdown 表格）")
    treatment_evaluation: str = Field(..., description="治疗评价对照指南（markdown 表格，带证据等级）")
    recommendations: list[str] = Field(..., description="后续建议，每条尽量带指南依据")
    blockers: list[str] = Field(..., description="卡点/待核实")
    disclaimer: str = Field("依据病历与 CSCO 指南整理，属临床辅助，最终以主诊医师/MDT 决策为准。")


# ---------- 确定性抽取（代码产出，非 LLM） ----------

class PatientFeatures(BaseModel):
    """从 JSON 确定性抽取的原始证据（skill 第三步字段映射），供 LLM 判断。"""
    gender: str | None = None
    age: int | None = None
    diagnoses: list[str] = Field(default_factory=list)
    pathology_text: str = ""
    tnm_text: str = ""
    treatment_text: str = ""
    imaging_text: str = ""
    labs_text: str = ""
    narrative_text: str = ""


# ---------- 图状态 ----------

class DiagnosisState(TypedDict, total=False):
    case_id: str
    patient_path: str
    patient_data: dict[str, Any]
    features: PatientFeatures
    guide_sections: list[str]
    subtype: MolecularSubtype
    staging: Staging
    red_lines: list[RedLineFlag]
    chain_path: list[DecisionChainStep]
    report: DiagnosisReport
    human_decision: str | None
