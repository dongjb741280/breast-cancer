"""冒烟测试：验证确定性层（配置/抽取/RAG/图构建）无运行时错误，不调 LLM。

用法：.venv/bin/python smoke_test.py
"""
from __future__ import annotations


def main() -> None:
    # 1. 配置（含 .env 加载）
    import config
    print(f"[1] config  model={config.ANTHROPIC_MODEL}  base_url={config.ANTHROPIC_BASE_URL or '默认'}")

    # 2. 确定性抽取
    from extractor import extract_features, load_patient
    path = config.resolve_patient_path("REAL-003")
    pd = load_patient(path)
    f = extract_features(pd)
    print(f"[2] extractor  gender={f.gender} age={f.age} diagnoses={len(f.diagnoses)}")
    print(f"    病理={f.pathology_text[:100]!r}")
    print(f"    TNM={f.tnm_text[:100]!r}")
    print(f"    narrative={len(f.narrative_text)}字 imaging={len(f.imaging_text)}字 labs={len(f.labs_text)}字")

    # 3. 指南 RAG（无 OPENAI_API_KEY → BM25 降级）
    from guide_rag import GuideRetriever, build_query
    r = GuideRetriever()
    print(f"[3] RAG  mode={r.mode}  chunks={len(r.nodes)}")
    q = build_query(f)
    secs = r.retrieve(q)
    print(f"    query={q[:80]!r}")
    print(f"    命中 {len(secs)} 段，首段={secs[0][:80]!r}" if secs else "    （无命中）")

    # 4. 图构建（只编译，不 invoke）
    from graph import build_graph
    g = build_graph()
    nodes = list(g.get_graph().nodes.keys())
    print(f"[4] graph  编译 OK，节点={nodes}")

    print("\n=== SMOKE TEST PASSED ===")


if __name__ == "__main__":
    main()
