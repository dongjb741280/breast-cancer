# PDF → Markdown 方案对比（data_cleaning）

对《2026 CSCO 乳腺癌诊疗指南》（扫描版 PDF，258 页）做 OCR 转 Markdown，代码里沉淀了三种处理方式。本文对比三种方式的操作、原理与产物，供后续选型参考。

## 一、三种方式一览

| | 方式一 | 方式二 | 方式三 |
|---|---|---|---|
| 名称 | macOS Vision（Swift 原生） | PaddleOCR（PP-OCRv5） | PP-StructureV3（PaddleX） |
| 代码位置 | `process/ocr.swift` + `run.sh` + `postprocess.py` | `process_ocr/ocr.py` | `process_ocr/ocr_structure.py` |
| 语言/框架 | Swift + macOS Vision/AppKit | Python + PaddleOCR | Python + PaddleX |
| 模型 | 系统内置，无下载 | PP-OCRv5 det/rec | 布局 + 表格结构 + OCR 多模型 |
| 版面分析 | ✗ | ✗ | ✓ |
| 表格识别 | 启发式列聚类 | 启发式列聚类 | SLANet 真实结构识别 |
| 标题层级 | ✗（纯文本） | ✗（纯文本） | ✓（`##` 标题） |
| 产物 | `2026CSCO乳腺癌诊疗指南.md`（328 KB） | `test_ocr.md`（部分测试） | `guide.md`（289 KB，258 页全量） |

## 二、逐方式说明与操作

### 方式一：macOS Vision（Swift 原生）

调用系统 Vision 框架的 `VNRecognizeTextRequest`，`recognitionLevel = .accurate`，识别语言 `zh-Hans + en-US`，开启 `usesLanguageCorrection`。不下载任何模型，Apple 芯片本机加速。

**操作（`process/run.sh`，共 4 步）：**

```bash
cd Data_Cleaning/process

# 1. 渲染 PDF → PNG（300 dpi 灰度）
pdftoppm -r 300 -gray -png ../2026CSCO乳腺癌诊疗指南.pdf pages/pg

# 2. 编译 OCR 工具
swiftc -O ocr.swift -o ocr

# 3. OCR 成原始文本
./ocr pages/ raw_ocr.txt

# 4. 后处理写 Markdown
python3 postprocess.py raw_ocr.txt ./output/2026CSCO乳腺癌诊疗指南.md
```

表格：连续多 fragment 行 → `minX` 列聚类，拼成 Markdown 表格（启发式，无真实表格结构识别）。含罗马数字归一化（Ⅰ/Ⅱ/Ⅲ）、页码/水印剔除。

- 优点：最快、零模型下载、免费离线、内存占用低。
- 缺点：无版面/表格结构识别；封面等复杂版式噪声多（如 ISBN 条码被误拼成表格、`ISBN` 误读为 `TSRN`）。

### 方式二：PaddleOCR（PP-OCRv5）

开源 PaddleOCR，`lang="ch"`，默认 PP-OCRv5 server 检测 + 识别。检测文本框 → 识别 → 按行分组（`midY` 容差）→ 列聚类 → 输出 Markdown 表格。

**操作：**

```bash
cd Data_Cleaning/process_ocr

# 全量（不带 --limit）
.venv/bin/python ocr.py pages output/guide.md

# 先跑前 N 页试跑
.venv/bin/python ocr.py pages output/test_ocr.md --limit 20
```

表格：与方式一同源的启发式列聚类（Python/numpy 移植），同样含罗马数字归一化与页码剔除。

- 优点：中文识别强于 Vision、跨平台、可调参。
- 缺点：无版面/表格结构识别（表格仍靠启发式）；需 paddle 环境；CPU 上慢。

### 方式三：PP-StructureV3（PaddleX）

PP-StructureV3 多模型管线：版面分析（`PP-DocLayout_plus-L` / `PP-DocBlockLayout`）+ 表格结构识别（`SLANeXt`/`SLANet_plus` + `RT-DETR` 单元格检测）+ OCR（PP-OCRv5 server）。`use_table_recognition=True`。

**操作：**

```bash
cd Data_Cleaning/process_ocr

# 全量 258 页（后台跑，约 7 小时）
.venv/bin/python ocr_structure.py pages output/guide.md
```

流程：版面分析 → 标题/正文/表格分类 → 标题加 `##`、页眉页脚页码丢弃 → 表格输出 HTML → `pandas.read_html` 转 Markdown 表格。大图先降采样（长边上限 2500）避免多模型推理 OOM。

- 优点：真实版面 + 表格结构识别，结构化最好，表格转 Markdown 干净，标题层级可用。
- 缺点：模型多、内存大（16 GB 机器需降采样防 OOM）、最慢；封面等装饰页仍会误读。

## 三、对比表

| 维度 | 方式一 Vision | 方式二 PaddleOCR | 方式三 PP-StructureV3 |
|---|---|---|---|
| 依赖 | 仅 macOS + poppler | paddle 环境 | paddlex 环境 |
| 模型下载 | 无 | PP-OCRv5 | 多模型（布局+表格+OCR） |
| 中文识别 | 中 | 强 | 强 |
| 版面分析 | ✗ | ✗ | ✓ |
| 表格识别 | 启发式列聚类 | 启发式列聚类 | SLANet 结构识别 |
| 标题层级 | ✗ | ✗ | ✓（`##`） |
| 速度 | 最快 | 慢 | 最慢（~7h/258 页） |
| 内存 | 低 | 中 | 高 |
| 离线 | ✓ | ✓ | ✓ |

## 四、结论与推荐

- **正文最终产物用方式三（PP-StructureV3）**：结构化最好，表格转 Markdown 干净，标题层级可直接用于后续清洗。产物为 `process_ocr/output/guide.md`。
- **快速试跑 / 无 paddle 环境**：用方式一（Vision），秒级出结果做粗检。
- **方式二**：作为 PaddleOCR 基线，介于两者之间；若不需要版面分析、只想换识别引擎时用它。

三者的共同短板：封面、目录、版权页等装饰性版面（含条码/二维码/多栏）都会产生噪声，正文部分的表格与标题才是决定质量的区域。
