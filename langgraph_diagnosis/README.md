# LangGraph 诊疗诊断流程

把 `.claude/skills/diagnosis-report` 的诊疗场景，用 **LangGraph（图编排）+ LlamaIndex（指南 RAG）+ 结构化输出 + 人机协同** 重写为可运行的 Python 流水线。

> 目的不是替换 skill，而是给同一场景一个「可批量、可评测、可生产化」的工程形态。skill 里 80% 的价值——领域红线与证据锚定的 prompt 规则——在这里被原样搬进 prompt，其余「确定性抽取」下沉为代码。

## 与 skill 的步骤映射

| skill 步骤 | 这里的实现 | 类型 |
|---|---|---|
| 第一步 定位读取病历 | `config.resolve_patient_path` + `extractor.load_patient` | 确定性代码 |
| 第二步 读指南章节 | `guide_rag.GuideRetriever`（LlamaIndex 按标题切块 + 语义/关键词检索） | RAG |
| 第三步 抽取特征 | `extractor.extract_features`（字段映射，权威字段 + 叙事兜底） | 确定性代码 |
| 第三步 分子分型/分期/红线判断 | `nodes.judge_subtype / judge_staging / check_red_lines` | LLM 结构化输出 |
| 第四步 诊断报告 | `nodes.write_report`（9 节模板 → `DiagnosisReport`） | LLM 结构化输出 |
| 第五步 决策链 A→U | `nodes.trace_chain`（逐节点回溯 + 证据） | LLM 结构化输出 |
| 红线 + 人机协同 | `graph.route_after_red_lines` 条件边 + `human_review`/`human_approve` 的 `interrupt` | 图编排 + HITL |

## 图结构

```
START → load_patient → extract_features → retrieve_guide
      → judge_subtype → judge_staging → check_red_lines
      → 〔条件边〕 命中红线 → human_review(interrupt) → trace_chain
                  无红线        → trace_chain
      → write_report → human_approve(interrupt) → END
```

- **条件边** = 决策链的关键岔口：红线→人工（`route_after_red_lines`）。M0/M1、pCR/non-pCR、脑实质/脑膜等更细分支，可在 `trace_chain` 内由 LLM 产出完整 A→U 路径，或按需再拆成显式节点/边。
- **结构化输出**：`schemas.py` 里 6 个 Pydantic 模型，LLM 用 `with_structured_output` 生成，下游可校验、可对照金标准评测。
- **人机协同**：`interrupt()` 在两处暂停——红线复核、报告终审。`main.run` 用 `Command(resume=...)` 恢复。

## 安装与运行

```bash
cd langgraph_diagnosis
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填入 ANTHROPIC_API_KEY；OPENAI_API_KEY 可选
```

运行一例（交互式，遇红线/终审会暂停等你输入）：

```bash
python main.py REAL-006
```

一次性结构化输出（自动 approve，跳过人工，便于批跑/评测）：

```bash
python main.py REAL-006 --json
```

## 关键设计取舍

1. **确定性 vs LLM 的分工**：JSON 解析、字段抽取、TNM 线索是确定性代码（可单测）；分子分型、分期判断、红线触发、A→U 走链、报告是 LLM（`temperature=0` + 结构化输出）。
2. **RAG 降级**：没配 embedding key 时，`GuideRetriever` 自动退回 `BM25Retriever`（关键词，无需 embedding），保证可立即跑通；配了 `OPENAI_API_KEY` 则用 `VectorStoreIndex` 语义检索。
3. **成本控制**：不把 270KB 指南全塞进 prompt，只喂检索到的 top-k 章节；也不把 880KB JSON 全塞，只喂 `extract_features` 抽出的证据文本。
4. **评测入口**：`--json` 输出与 `Data_Cleaning/doc/系统输入/7例真实病例-患者基本情况与诊疗金标准.md` 可直接做字段级对照。

## 文件

| 文件 | 职责 |
|---|---|
| `config.py` | 路径、病例映射、模型/检索配置（环境变量覆盖） |
| `schemas.py` | Pydantic：结构化输出模型 + 图状态 |
| `extractor.py` | 确定性字段抽取（字段映射） |
| `guide_rag.py` | LlamaIndex 指南检索（向量/BM25 降级） |
| `nodes.py` | 图节点：确定性节点 + LLM 判断节点 + interrupt 节点 |
| `graph.py` | StateGraph 组装 + 条件边 + HITL |
| `main.py` | CLI 入口（交互 / JSON 输出 / resume） |

## 已知边界（相对 skill 尚未覆盖）

- **mermaid 决策链图**：skill 会渲染高亮图；这里未接 `mmdc`，`chain_path` 结构化后可按需再渲染（可在 `write_report` 后加一个节点）。
- **红线多例输出**：`check_red_lines` 用「循环单例」方式收集，生产建议改成 list 输出的 Pydantic 模型（一次调用返回全部红线）。
- **检索器缓存**：`guide_rag` 每次构建会重建索引，`nodes` 里用模块级单例兜底；生产建议在 `build_graph` 时注入构建好的 retriever。
