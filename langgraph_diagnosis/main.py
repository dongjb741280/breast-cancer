"""CLI 入口：跑一例（含人机协同暂停/恢复），或输出结构化 JSON。

用法：
  python main.py REAL-006                     # 跑一例，遇红线/报告终审时暂停
  python main.py REAL-006 --json              # 一次性输出（自动 approve，跳过人工）
  python main.py REAL-006 --thread t1         # 指定 thread_id，便于 resume
"""
from __future__ import annotations

import argparse
import json

from langgraph.types import Command

import config
from graph import get_graph


def run(case: str, thread_id: str, auto_approve: bool = False) -> dict:
    graph = get_graph()
    path = config.resolve_patient_path(case)
    cfg = {"configurable": {"thread_id": thread_id}}

    state = {"case_id": case, "patient_path": str(path)}
    result = graph.invoke(state, cfg)

    # 处理人机协同暂停点（interrupt）
    while result.get("__interrupt__"):
        inter = result["__interrupt__"][0]
        kind = inter.value.get("type")
        if kind == "red_line_review":
            print("\n[红线复核] 命中红线：")
            for r in inter.value.get("red_lines", []):
                print(f"  - {r.get('kind')}: {r.get('description')} → {r.get('action')}")
            if auto_approve:
                decision = {"decision": "proceed", "note": "auto-approve"}
            else:
                d = input("人工决策 [proceed/stop/revise]，默认 proceed：").strip() or "proceed"
                decision = {"decision": d}
        elif kind == "report_approval":
            if auto_approve:
                decision = {"decision": "approve"}
            else:
                d = input("报告终审 [approve/revise]，默认 approve：").strip() or "approve"
                decision = {"decision": d}
        else:
            decision = {"decision": "approve"}
        result = graph.invoke(Command(resume=decision), cfg)

    return result


def _dump(result: dict) -> str:
    out = {
        "case_id": result.get("case_id"),
        "subtype": result.get("subtype").model_dump() if result.get("subtype") else None,
        "staging": result.get("staging").model_dump() if result.get("staging") else None,
        "red_lines": [r.model_dump() for r in result.get("red_lines", [])],
        "chain_path": [s.model_dump() for s in result.get("chain_path", [])],
        "report": result.get("report").model_dump() if result.get("report") else None,
    }
    return json.dumps(out, ensure_ascii=False, indent=2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("case", help="REAL-XXX 编号或 JSON 路径")
    ap.add_argument("--json", action="store_true", help="结构化 JSON 输出（自动 approve）")
    ap.add_argument("--thread", default=None, help="thread_id（用于 resume）")
    args = ap.parse_args()

    thread = args.thread or f"{args.case}-run"
    result = run(args.case, thread, auto_approve=args.json)

    if args.json:
        print(_dump(result))
    else:
        report = result.get("report")
        if report:
            print("\n# 乳腺癌综合诊断报告\n")
            print(f"**患者**：{report.patient_info}\n")
            print("## 主要诊断\n" + "\n".join(f"{i}. {d}" for i, d in enumerate(report.main_diagnosis, 1)))
            print("\n## 病理与分子分型依据\n" + report.molecular_table)
            print("\n## TNM 分期\n" + report.tnm_staging)
            print("\n## 诊疗经过\n" + report.treatment_timeline)
            print("\n## 治疗评价\n" + report.treatment_evaluation)
            print("\n## 后续建议\n" + "\n".join(f"{i}. {r}" for i, r in enumerate(report.recommendations, 1)))
            print("\n## 卡点/待核实\n" + "\n".join(f"- {b}" for b in report.blockers))
            print("\n> " + report.disclaimer)


if __name__ == "__main__":
    main()
