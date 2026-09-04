## Destination

一份 spec + 一个端到端可跑的最小原型：把清洗后的 CSCO `guide.md`（HER2+ 乳腺癌）建成「混合型」医疗诊疗知识库 —— 结构化决策层（分层 → 方案 → 推荐等级 → 证据类别）+ 轻量知识图谱 + BM25/向量分路合并检索，作为 LLM agent 回答诊疗问题的 RAG 底料，并对齐 `系统输入` 病例 + 诊疗金标准做评测。

## Notes

- 数据源：`Data_Cleaning/process_ocr/output/guide.md`（PP-StructureV3 OCR 全量 258 页产物）；评测对照 `Data_Cleaning/doc/系统输入/`（BC-*/REAL-* 病例 + 金标准）。
- 范围：仅 HER2+ 乳腺癌、仅 CSCO 指南。多指南/多癌种 out of scope。
- 每 session consult：`grilling` + `domain-modeling`（结构化/KG schema 需术语定稿，术语落到 `CONTEXT.md`）。
- 技术默认（已拍）：Python + 全内存轻量（Chroma 或 pgvector 向量 + NetworkX 图 + 本地 bge-m3 或 API embedding），原型不碰 Neo4j/重型服务。
- 原型终点：给定「分期 + 分层」→ 返回「方案 + 推荐等级 + 证据类别 + 来源页码」，能对上金标准。
- 数据前提：`guide.md` 存在 Ⅰ/Ⅱ/Ⅲ 与证据类别的 OCR 噪声，需先归一化（见 02）。

## Decisions so far

- [guide.md 推荐等级/证据类别噪声清单及归一化规则](issues/02-guide-normalization.md)：噪声=Ⅰ→`级推荐`/`1级`/`I级`、Ⅱ→`ⅡI`、Ⅲ→`川`；证据=`[2A`/`1B]3` 缺括号、`1类证据`丢A。判别口诀「`级推荐`＝等级、`类证据`/`[X]`＝证据」。
- [系统输入 schema 与金标准结构摸底](issues/01-system-input-schema.md)：27 JSON 同构标准化 EMR，无机器可读等级字段；金标准是**自由文本**（BC=4 文书含 MDT 结论/阶段小结「考察点」；REAL=「统一六项评测金标准」散文），无 Ⅰ/Ⅱ/Ⅲ 等级码。
- [结构化决策记录 schema 定稿](issues/03-structured-schema.md)：一条推荐决策 = 一个(分层, 方案)；7 字段 = 治疗阶段/人群/分层条件/方案/推荐等级(ⅠⅡⅢ)/证据类别(1A..3)/来源页码；更新要点排除、给药表归 04 图谱。
- [知识图谱节点/边 schema 定稿](issues/04-graph-schema.md)：6 节点（推荐决策/方案/药物/分层/推荐等级/证据类别）5 边；每条记录 reify 成「推荐决策」hub 节点；分层单节点；`组成于` 多对多、剂量不进图。
- [评测协议](issues/07-eval-protocol.md)：两层——端到端 LLM-as-judge（REAL 六项/BC 考察点，逐项 pass/fail 取均值）+ 检索层 recall@3/precision@3；不做等级 exact-match；全量 27 分 REAL/BC 档。
- [embedding 与向量库选型](issues/05-embedding-vector-store.md)：本地 bge-m3 + Chroma（全内存）；构建侧全离线，评测 judge 用 API（需配 key，本机现无）。
- [检索分路合并算法](issues/06-fusion-algorithm.md)：分层融合——结构化决策记录(答案层，按Ⅰ>Ⅱ>Ⅲ) + 正文 chunk(证据层，BM25+向量 RRF 合成)；结构化精确优先、无命中正文兜底+显式标记。
- [最小原型 I/O 契约](issues/08-prototype-io-contract.md)：输入=结构化3字段(治疗阶段/人群/分层条件)；输出={命中,答案层[方案/等级/证据/页码],证据层}；NL 解析交前置 agent。concrete example 见 `prototype-io-contract.md`。

## Not yet specified

- 结构化层是否需要人工标注/审核闭环：待原型跑通、看抽取质量后再议。

## Out of scope

- 多指南（NCCN / ESO-ESMO / ASCO-SNO…）与多癌种：本次只做 CSCO + HER2+ 乳腺癌。
- 真实图数据库（Neo4j 等）与重型检索服务：原型阶段不引入。
- 确定性规则引擎 / 直接给医生开处方：本库是 LLM agent 的检索底料，不替代临床决策。
- 知识库如何喂给 LLM agent（prompt 模板 / tool 接口）：agent 侧消费，属后续 effort；本 map 只交付 KB 及其 I/O 契约。
