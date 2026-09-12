"""指南 RAG（LlamaIndex）：把 guide.md 按标题切块，按病例特征检索相关章节。

默认 GUIDE_RETRIEVER=auto：
- 装了 llama-index-embeddings-huggingface → 本地中文向量（BAAI/bge-m3）语义检索
- 没装 → BM25Retriever（关键词检索，无需 embedding，可立即跑通）
"""
from __future__ import annotations

from pathlib import Path

from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.node_parser import MarkdownNodeParser
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.core.schema import Document

import config


def _build_nodes(guide_path: Path) -> list:
    text = guide_path.read_text(encoding="utf-8")
    parser = MarkdownNodeParser()
    return parser.get_nodes_from_documents([Document(text=text)])


class GuideRetriever:
    def __init__(self, guide_path: Path | None = None, top_k: int | None = None):
        self.guide_path = guide_path or config.GUIDE_PATH
        self.top_k = top_k or config.GUIDE_TOP_K
        self.nodes = _build_nodes(self.guide_path)
        self._mode = self._resolve_mode()
        self._index = None
        self._retriever = None
        self._build()

    def _resolve_mode(self) -> str:
        mode = config.GUIDE_RETRIEVER
        if mode != "auto":
            return mode
        # auto：优先本地中文向量；装不了则退回 BM25
        try:
            import llama_index.embeddings.huggingface  # noqa: F401
            return "vector"
        except ImportError:
            return "bm25"

    def _resolve_model_path(self) -> str:
        """优先用 ModelScope 本地缓存（国内可下大文件），失败则退回 HF 模型名。"""
        try:
            from modelscope import snapshot_download
            return snapshot_download(config.EMBEDDING_MODEL)
        except Exception:
            return config.EMBEDDING_MODEL

    def _build(self) -> None:
        if self._mode == "vector":
            try:
                from llama_index.embeddings.huggingface import HuggingFaceEmbedding
                Settings.embed_model = HuggingFaceEmbedding(model_name=self._resolve_model_path())
                self._index = VectorStoreIndex(self.nodes)
                self._retriever = self._index.as_retriever(similarity_top_k=self.top_k)
                return
            except Exception as e:  # 模型加载失败（网络受限）等 → 退回 BM25
                print(f"[RAG] 向量模型加载失败，退回 BM25：{e}")
                self._mode = "bm25"
        self._retriever = BM25Retriever.from_defaults(nodes=self.nodes, similarity_top_k=self.top_k)

    @property
    def mode(self) -> str:
        return self._mode

    def retrieve(self, query: str) -> list[str]:
        """返回 top-k 指南片段文本，供判断节点使用。"""
        nodes = self._retriever.retrieve(query)
        return [n.get_content() for n in nodes]


def build_query(features) -> str:
    """按病例特征构造检索 query（分子分型 + 分期 + 转移部位 + 治疗阶段）。"""
    parts = ["乳腺癌诊疗指南", "分子分型 HER2 ER PR Ki-67 判读"]
    d = ";".join(features.diagnoses or [])
    if d:
        parts.append(f"诊断：{d}")
    if features.pathology_text:
        parts.append(f"病理：{features.pathology_text[:200]}")
    # 转移部位决定要检索骨转移/脑转移章节
    blob = (features.tnm_text + features.imaging_text + features.narrative_text).lower()
    if any(k in blob for k in ("脑转移", "脑继发", "小脑", "脑膜")):
        parts.append("脑转移")
    if any(k in blob for k in ("骨转移", "骨继发", "肋骨", "椎体")):
        parts.append("骨转移")
    if "M1" in features.tnm_text or "Ⅳ期" in features.tnm_text or "IV期" in features.tnm_text:
        parts.append("晚期解救治疗")
    else:
        parts.append("新辅助治疗 辅助治疗")
    return " ".join(parts)
