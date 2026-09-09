---
name: decision-chain
description: 根据一份乳腺癌病历（REAL-XXX 编号 / JSON 路径 / 粘贴文本）走通 CSCO 诊疗决策链（节点 A→U），逐节点给出该病例走的分支 + 病历原文证据，并生成高亮 mermaid 图。当用户说「走决策链 / 走通决策链 / trace decision chain / 生成决策链图」时使用。
---

# 乳腺癌诊疗决策链追踪

把一份患者病历映射到 CSCO 乳腺癌诊疗决策链（节点 A→U），在**每个分支节点**给出「该病例走了哪条分支 + 病历原文证据」，最后输出一条高亮的实际路径。

这是**追踪/回溯**任务，不是开方：目标是说清「这例走到了决策树哪个节点、凭什么」，不是替患者推荐方案。

全程由 Claude 直接读病历、自行判断，**不依赖任何外部脚本**（生成图时用 `mmdc` 渲染，见「生成高亮 mermaid 图」）。

## 第一步：定位并读取病历

三种输入，按优先级取：

1. **`REAL-XXX` 编号** → 查下表拿 JSON 路径（用 Read 读文件，取 `data["patient_data"]`）：

   | 编号 | 路径 |
   |---|---|
   | REAL-001 | `Data_Cleaning/doc/系统输入/REAL-001-严格标准版.json` |
   | REAL-002 | `Data_Cleaning/doc/系统输入/REAL-002-严格标准版.json` |
   | REAL-003 | `Data_Cleaning/doc/系统输入/REAL-003-大悟县首程-脱敏映射.json` |
   | REAL-004 | `Data_Cleaning/doc/系统输入/REAL-004-首程2-脱敏映射.json` |
   | REAL-005 | `Data_Cleaning/doc/系统输入/REAL-005-首程3-脱敏映射.json` |
   | REAL-006 | `Data_Cleaning/doc/系统输入/REAL-006-深圳南山入院-严格标准版.json` |
   | REAL-007 | `Data_Cleaning/doc/系统输入/REAL-007-深圳南山入院-严格标准版.json` |

2. **JSON 文件路径** → 直接读，取 `data["patient_data"]`。
3. **粘贴的自由文本**（住院志/病程/出院记录等）→ 直接当作病历摘要用。

**读 JSON 时，把 `patient_data` 里所有带临床信号的字段都读一遍，不要只读叙事文书**。各字段与「第二步要抽的特征」的对应关系（结构化为权威、叙事兜底）：

| 字段 | 装的是什么 | 喂给哪些特征 |
|---|---|---|
| `standard_patient` | 性别；其余多为脱敏 PII | 性别（年龄在 `diagnosis`） |
| `diagnosis[]` | 诊断名 + 年龄 | 诊断列表、年龄、TNM/分期（诊断名常带分期/转移） |
| `standard_pathology_reports[]` | 病理诊断 + IHC/分子（`pathology_diagnosis` + `pathology_description` 等文本字段） | **分子分型、ER/PR/HER2/Ki67/FISH、TNM、pCR/RCB（最权威）** |
| `standard_final_operation_records[]` | 术式、术后病理 ypTNM、RCB | 是否手术、pCR/non-pCR |
| `examine_items[]` | 影像（CT/MR/ECT/超声），`report_name` + 所见 | 转移部位、分期（原发灶/淋巴结/远处） |
| `laboratories[]` | 检验（血常规/生化等） | 骨髓抑制、脏器毒性信号 |
| `recipe_medicines[]` | 医嘱用药 | 治疗（当前/既往）的结构化来源 |
| `standard_physical_sign_records[]` | 体格检查 | 肿块大小、淋巴结体征 |
| `standard_inpatient_documentations[]` | 叙事文书（入院/首次病程/病程摘要/出院） | 兜底：分期、治疗时间轴、手术、pCR |
| `standard_outpatient_medical_records[]` / `standard_out_patient_visits[]` / `standard_in_patient_records[]` | 门诊/住院就诊记录 | 就诊时间轴、补充治疗 |

注意：
- 各字段的正文字段名不统一，先扫一眼该字段第一个元素的 key，找到承载文本/诊断/结论的字段再读（如病理用 `pathology_diagnosis`+`pathology_description`，文书用 `record_text`，检验/影像找 `report_name`+所见文本）。
- 叙事文书里跳过知情同意/授权委托/信息确认等模板；`standard_patient` 里的 PII（身份证/手机号等）不读不输出。

## 第二步：抽取决策关键特征

逐条从病历提取，**优先用第一步映射里的权威字段，叙事文本兜底；每条都要能指回原文，抽不到就留空/写「未记录」，绝不编造**：

- **性别 / 年龄**：`standard_patient` 与 `diagnosis[]`。
- **诊断列表**：`diagnosis[]` 的所有诊断名，去重。
- **TNM / 分期（区分初始 vs 当前）**：初始 = 最早一次记录；当前 = 最近一次（复发/转移后常为 M1 / Ⅳ期）。注意 `MO`→`M0` 的 OCR 误写；术后病理可用 `ypT/N`（如 ypT2N1a）表示新辅助后分期。
- **分子分型**（按指南判读）：
  - HER2 **IHC 3+** 或 **FISH/ISH 扩增** → HER2 阳性型（**IHC 3+ 优先于 FISH 结果**：FISH 扩增阴性但 HER-2(3+) 仍判 HER2 阳性）
  - HER2 IHC 1+，或 IHC 2+ 且 FISH 阴性 → HER2 低表达型
  - ER/PR ≥1% → HR 阳性；ER- PR- HER2- → 三阴性；诊断结论写 Luminal → HR 阳性(Luminal)
- **转移部位**：只在「X 继发恶性肿瘤 / X 转移 / 转移瘤 / 转移灶」语境下命中（肝/骨/脑/肺/肾上腺/胸膜），避免把体检正常描述误当转移。
- **治疗（区分当前 vs 既往）**：当前 = 至今/维持/继续/目前/现给予；既往 = 术后/序贯/曾予/外院/带年份的过去事件。知情同意书里的备选方案、随访模板不算。
- **是否手术**：切除术/根治术/保乳术/前哨淋巴结活检/腋窝清扫/全乳切除。
- **是否新辅助**：术前已给药（时间线在手术前 + 化疗/靶向），或原文出现「新辅助」。
- **pCR / non-pCR**：pCR / 病理学完全缓解 / MP 5 级 / RCB 0 → pCR；non-pCR / 未达 pCR / 残余病灶 / RCB I–III（含 RCB-II 这类带连字符写法）→ non-pCR。

## 决策链结构（A→U）

节点标签（与 `diagrams/*.mmd` 一致）：

| 节点 | 含义 | 类型 |
|---|---|---|
| A | 初诊乳腺癌 | |
| B | 影像 + 病理 + 分子标志物 | |
| C | TNM 分期与风险分层 | |
| D | M 分期：有无远处转移？ | 菱形分支 |
| E | 是否适合新辅助治疗？ | 菱形分支 |
| F | 按分子亚型选择新辅助方案 | |
| G | 直接手术与腋窝评估 | |
| H | 手术 + 病理反应评估 | |
| I | pCR 还是残余病灶？ | 菱形分支 |
| J | 按风险完成术后辅助治疗 | |
| K | 强化辅助（HER2+/三阴）T-DM1 / 卡培他滨 / 奥拉帕利；HR+ 按风险辅助 | |
| L | 放疗 / 内分泌 / 抗HER2 / 免疫等 | |
| M | 转移灶再活检与再分型 | |
| N | 评估既往治疗、耐药、疾病速度与患者状态 | |
| O | 按分子亚型序贯全身治疗（HER2阳性 / HER2低表达 / 三阴性 / HR阳性） | |
| P | 特殊转移部位？ | 菱形分支 |
| Q | 骨改良药 + 局部放疗/手术评估 | |
| R | 脑部局部治疗 + 全身治疗评估 | |
| S | 继续系统治疗与疗效评估 | |
| T | 疗效评估、毒性管理、营养/心理支持、生活质量与 MDT | |
| U | 长期随访、复发监测与临床研究/真实世界证据更新 | |

分支规则：

- **D**：有远处转移 → 是（M1 复发/转移期）→ M；M 分期可疑但未确诊 → 待核实（停，见红线）；否则 → 否（M0 早期/局部进展期）→ E
- **E**：适合新辅助（肿块大 / LN+ / HER2+ / 三阴 / 保乳意愿，或术前已给药）→ 是 → F；否则 → 否 → G
- **F → H → I**；**I**：pCR → J；non-pCR → K；病理反应未记录 → 停在 I（需 MP/RCB/ypTNM）
- **G → J → L**
- M1 支：**M → N → O → P**；**P**：骨转移 → Q；脑转移 → R；其他内脏/软组织（肝/肺等）或无特殊部位 → S
- 汇合：L / Q / R / S → **T → U**

## 第三步：逐节点走链

1. 抽取上一步字段。
2. 从 A 开始逐节点走，**只走该病例实际命中的节点**。
3. 每个节点给三样东西：节点标签、走的分支（分支节点才有）、病历证据（一句原文/指标）。
4. 走到「待核实」或「证据缺失」节点就停下，不要硬往下编。
5. 若病历是「边疑边治」（如肺结节疑似转移但按局部进展期继续根治性治疗），如实呈现这种并存，不要替它把 M 定为 0 或 1。

## 输出格式

```text
病例 <ID>：<性别> <年龄>岁
诊断：<诊断列表>
TNM/分期：<初始 → 当前>（或 "临床 cTNM 未记录 / 术后病理 ypT2N1a" 等）
分子分型：<subtype>   ER <证据或->  PR <证据或->  HER2 <证据或->  Ki67 <证据或->  FISH <结果或->
转移部位：<部位列表 或 无明确>
治疗：当前：<类别…>；既往：<类别…>

决策链路径：
  [A] 初诊乳腺癌
       ↳ <证据>
  [D] M分期：有无远处转移？  ← 是：M1（肝、骨）
       ↳ <证据>
  ...

卡点/待核实：
  - <未记录/需补充的点>
```

## 生成高亮 mermaid 图（走链的一部分，始终生成）

走链完成后，把高亮 `.mmd` 写到 `diagrams/decision-chain-<case>.mmd`，并渲染 `.png` / `.svg`（与仓库 `diagrams/` 现有约定一致）：

```bash
mmdc -i diagrams/decision-chain-<case>.mmd -o diagrams/decision-chain-<case>.svg -b white
mmdc -i diagrams/decision-chain-<case>.mmd -o diagrams/decision-chain-<case>.png -b white -s 2
```

命名：REAL-XXX → `decision-chain-REAL-<NNN>.mmd`；自由文本/其他 → 用病例编号或自定短 slug 替换 `<case>`。

节点全画、用**完整标签**（K/O 带 `<br/>` 多行，与 `diagrams/breast-cancer-treatment-decision-chain.mmd` 一致）。菱形用 `{…}`、其余 `[…]`；菱形 = D/E/I/P：

```
A[初诊乳腺癌]
B[影像 + 病理 + 分子标志物]
C[TNM分期与风险分层]
D{M分期：有无远处转移?}
E{是否适合新辅助治疗?}
F[按分子亚型选择新辅助方案]
G[直接手术与腋窝评估]
H[手术 + 病理反应评估]
I{pCR还是残余病灶?}
J[按风险完成术后辅助治疗]
K[强化辅助（HER2+/三阴）<br/>T-DM1 / 卡培他滨 / 奥拉帕利<br/>HR+：按风险辅助]
L[放疗 / 内分泌 / 抗HER2 / 免疫等]
M[转移灶再活检与再分型]
N[评估既往治疗、耐药、疾病速度与患者状态]
O[按分子亚型序贯全身治疗<br/>HER2阳性 / HER2低表达<br/>三阴性 / HR阳性]
P{特殊转移部位?}
Q[骨改良药 + 局部放疗/手术评估]
R[脑部局部治疗 + 全身治疗评估]
S[继续系统治疗与疗效评估]
T[疗效评估、毒性管理、营养/心理支持、生活质量与MDT]
U[长期随访、复发监测与临床研究/真实世界证据更新]
```

边按下面顺序书写；`linkStyle` 下标 = 各边在列表中的位置（0 起）：

```
A --> B
B --> C
C --> D
D -->|否：M0 早期/局部进展期| E
E -->|是| F
E -->|否| G
F --> H
G --> J
H --> I
I -->|pCR| J
I -->|non-pCR| K
J --> L
K --> L
D -->|是：M1 复发/转移期| M
M --> N
N --> O
O --> P
P -->|骨转移| Q
P -->|脑转移| R
P -->|其他内脏/软组织转移| S
L --> T
Q --> T
R --> T
S --> T
T --> U
```

高亮样式（照抄）：命中节点 `class path`、其余 `class dim`；走过的边 `linkStyle` 红、其余灰：

```
classDef path fill:#fca5a5,stroke:#dc2626,color:#7f1d1d,stroke-width:3px;
classDef dim fill:#f3f4f6,stroke:#d1d5db,color:#9ca3af,stroke-width:1px;
class A path;   class G dim;   ...
linkStyle 0 stroke:#dc2626,stroke-width:3px;
linkStyle 5 stroke:#d1d5db,stroke-width:1px;
```

顶部加一个**标题节点**承载病例摘要（不要用 `%%` 注释——注释不渲染进图，图里看不到）：

```
TITLE["<病例>：<分型/关键分支>"]
```

- 隐形边 `TITLE ~~~ A` 把标题置顶，**声明在所有边之后**（这样 A→U 的 25 条边仍占 `linkStyle` 0-24，高亮不错位）。
- 标题样式：`classDef caption fill:#fff,stroke:none,color:#111827,font-weight:bold;` + `class TITLE caption;`。

## 不确定性与红线（务必遵守）

走链途中遇到以下情况，**停下并明确标出，不要当作已确定继续**：

- **未提供 ≠ 阴性**：病历没写受体/分期/病理反应，就写「未记录/待补充」，不能默认判为阴性或正常。
- **混淆双侧/多病灶受体**：双侧乳腺或原发灶 vs 转移灶受体不一致时，分别说明（如「右侧 HER2+、左侧 FISH 未扩增」），以驱动治疗的主导病灶为准。
- **M 分期可疑未确诊**：疑似转移但无活检/PET 确认 → 在 D 标「M 分期待核实」，停。
- **活动性脑转移**：走到 R 时，若脑转移活动/有症状，提示先转 CNS MDT 局部处理，而非直接全身序贯。
- **严重骨髓抑制 / 内脏危象**：不要机械套标准方案，标注需先处理/转人工评估。

术语用 `CONTEXT.md` 的词汇（人群 / 治疗阶段 / 方案 / 药物 / 推荐等级 / 证据类别 / 分层条件 / 金标准），不要漂移成同义词。
