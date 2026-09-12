"""路径、病例映射、模型配置。所有可覆盖项走环境变量（见 .env.example）。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
GUIDE_PATH = REPO_ROOT / "Data_Cleaning" / "process_ocr" / "output" / "guide.md"
PATIENT_DIR = REPO_ROOT / "Data_Cleaning" / "doc" / "系统输入"
GOLD_STANDARD_PATH = PATIENT_DIR / "7例真实病例-患者基本情况与诊疗金标准.md"

# 病例编号 → 文件名（与 skill 第一步的映射表一致）
CASES: dict[str, str] = {
    "REAL-001": "REAL-001-严格标准版.json",
    "REAL-002": "REAL-002-严格标准版.json",
    "REAL-003": "REAL-003-大悟县首程-脱敏映射.json",
    "REAL-004": "REAL-004-首程2-脱敏映射.json",
    "REAL-005": "REAL-005-首程3-脱敏映射.json",
    "REAL-006": "REAL-006-深圳南山入院-严格标准版.json",
    "REAL-007": "REAL-007-深圳南山入院-严格标准版.json",
}

# LLM
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL")  # None = 默认 Anthropic 端点

# RAG
GUIDE_RETRIEVER = os.getenv("GUIDE_RETRIEVER", "auto")  # auto | vector | bm25
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
GUIDE_TOP_K = int(os.getenv("GUIDE_TOP_K", "6"))


def resolve_patient_path(case: str | Path) -> Path:
    """支持 REAL-XXX 编号或直接文件路径。"""
    p = Path(case)
    if p.exists():
        return p
    if case in CASES:
        return PATIENT_DIR / CASES[case]
    raise FileNotFoundError(f"未找到病例：{case}")
