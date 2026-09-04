Type: prototype
Status: resolved

Blocked by: 03, 07

## Question

最小原型 I/O 契约：输入（分期 + 分层，结构化字段还是自然语言）+ 输出（方案 + 推荐等级 + 证据类别 + 来源页码）的 concrete example，作为「端到端跑通」的验收切片。

## Answer

**I/O 契约定稿**（concrete example 见 asset `prototype-io-contract.md`，基于 guide.md L634 真实决策表）。

- **输入 = 结构化 3 字段** `{治疗阶段, 人群, 分层条件}`；自然语言解析交给前置 agent，原型不做。
- **输出 = 三件套** `{命中, 答案层, 证据层}`：答案层 = 推荐决策记录（方案/推荐等级/证据类别/来源页码），按 Ⅰ>Ⅱ>Ⅲ 排序；证据层 = 正文 chunk，不挂载到方案下。
- `命中:false` 时答案层空、证据层正文兜底、附「未命中结构化决策」标记。
