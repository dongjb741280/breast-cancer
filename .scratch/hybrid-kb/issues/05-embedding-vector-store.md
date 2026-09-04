Type: grilling
Status: resolved

## Question

embedding 与向量库选型定稿：embedding 用本地 bge-m3 还是 API（离线 / 成本 / 中文医疗文本质量）；向量库 Chroma vs pgvector。

默认：本地 bge-m3 + Chroma（全内存原型）。有 infra 约束在此敲定。

## Answer

**选型定稿**
- **embedding = 本地 bge-m3**：离线、多语言（中文医疗）、自带 dense+sparse+lexical 三路，契合「混合检索」目标；M2 Pro MPS 加速。
- **向量库 = Chroma**：嵌入式、全内存、零部署。
- **离线边界 = 构建侧全离线、评测侧可连 API**：知识库构建/检索（embedding + BM25 + 检索）全本地，数据不出本机；07 的 LLM-as-judge 用 API 换判分质量。

**事实**：本机无任何 API key（OpenAI/Anthropic/通义/智谱/DeepSeek 均未配置）。跑评测前需配一个（OPENAI 或同档）。
