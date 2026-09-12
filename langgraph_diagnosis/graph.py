"""LangGraph 图编排：把诊断流程组装成状态图，含条件边 + 人机协同 interrupt。

流程：
  START → load_patient → extract_features → retrieve_guide
        → judge_subtype → judge_staging → check_red_lines
        → [条件边] 有红线 → human_review（interrupt）；无红线 → trace_chain
        → trace_chain → write_report → human_approve（interrupt）→ END
"""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from nodes import (
    check_red_lines_node,
    extract_features_node,
    human_approve_node,
    human_review_node,
    judge_staging_node,
    judge_subtype_node,
    load_patient_node,
    retrieve_guide_node,
    trace_chain_node,
    write_report_node,
)
from schemas import DiagnosisState


def route_after_red_lines(state: DiagnosisState) -> str:
    """条件边：命中红线 → 转人工复核；否则继续走链。"""
    if state.get("red_lines"):
        return "escalate"
    return "proceed"


def build_graph():
    g = StateGraph(DiagnosisState)

    g.add_node("load_patient", load_patient_node)
    g.add_node("extract_features", extract_features_node)
    g.add_node("retrieve_guide", retrieve_guide_node)
    g.add_node("judge_subtype", judge_subtype_node)
    g.add_node("judge_staging", judge_staging_node)
    g.add_node("check_red_lines", check_red_lines_node)
    g.add_node("human_review", human_review_node)
    g.add_node("trace_chain", trace_chain_node)
    g.add_node("write_report", write_report_node)
    g.add_node("human_approve", human_approve_node)

    g.add_edge(START, "load_patient")
    g.add_edge("load_patient", "extract_features")
    g.add_edge("extract_features", "retrieve_guide")
    g.add_edge("retrieve_guide", "judge_subtype")
    g.add_edge("judge_subtype", "judge_staging")
    g.add_edge("judge_staging", "check_red_lines")

    g.add_conditional_edges(
        "check_red_lines",
        route_after_red_lines,
        {"escalate": "human_review", "proceed": "trace_chain"},
    )
    g.add_edge("human_review", "trace_chain")

    g.add_edge("trace_chain", "write_report")
    g.add_edge("write_report", "human_approve")
    g.add_edge("human_approve", END)

    return g.compile(checkpointer=MemorySaver())


def get_graph():
    """模块级单例，避免重复建图。"""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


_GRAPH = None
