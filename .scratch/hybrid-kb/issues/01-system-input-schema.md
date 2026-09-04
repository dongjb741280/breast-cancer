Type: research
Status: resolved

## Question

摸清 `Data_Cleaning/doc/系统输入/` 下 20 个 `BC-*.json` + 7 个 `REAL-*.json` + `7例真实病例-患者基本情况与诊疗金标准.md` 的数据结构：每个病例有哪些字段（患者基本情况 / 诊疗金标准 / 分期 / 分层 / 推荐方案 / 推荐等级…），尤其「诊疗金标准」里期望系统输出的形态（是方案名 + 等级，还是更细）。

产出一份 schema 摘要，作为 [03 结构化决策记录 schema 定稿] 和 [07 评测协议] 的对照基准。

## Answer

**字段结构（27 JSON 完全同构）**
- 顶层仅一个键 `patient_data`；其下 12 个固定子字段 = 标准化 EMR：`standard_patient` / `laboratories` / `diagnosis` / `examine_items` / `recipe_medicines` / `standard_inpatient_documentations` / `standard_outpatient_medical_records` / `standard_physical_sign_records` / `standard_pathology_reports` / `standard_final_operation_records` / `standard_out_patient_visits` / `standard_in_patient_records`。
- **无任何机器可读的「分期/分层/推荐方案/推荐等级/证据类别」字段**（全库检索「推荐/等级/gold/recommend」命中 0）。

**金标准形态 = 自由文本（非「方案 + 等级」）**
- BC 系列：金标准嵌在 `standard_inpatient_documentations[].record_text`，固定 4 份文书——入院记录 / 首次病程记录 / **MDT讨论记录**（含 讨论问题/关键信息/关键风险/需补充核验/结论，结论明说「输出带证据来源的建议草案，最终金标准由医学老师核验」）/ **阶段小结**（给「核心问题」，如「初诊 HER2+ HR− 肺肝转移的一线基准病例」）。故是场景描述 + 考察点，非结构化等级。
- REAL 系列：金标准在 `7例真实病例….md`，每例「患者基本情况 + 诊疗金标准」散文 + 「**统一六项评测金标准**」：人群判断 / 当前治疗线 / 治疗建议 / 证据依据 / 风险提示 / 资料不足补充。治疗线为定性词（一线/二线/多线/待核验），无等级码。

**BC vs REAL**
- BC（20）：合成、完全同构，4 文书 + 17 labs + 7 examine + 1 pathology；分两代——001~010 长文本(~580字)、011~020 精简(~380字)。
- REAL（7）：真实、高度异质。003/004/005 是「脱敏映射」小文件（1 份病程摘要）；001/002/006/007 全量病历（文书 13~123 份、diagnosis 3~155、labs 0~980，病理报告均为 0）。

**关键含义**：病例定义是结构化 EMR，金标准是文本需另解析；BC 与 REAL 金标准不在同一文件。
