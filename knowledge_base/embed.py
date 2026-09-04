"""guide.md -> 分页 chunk，网关 bge-m3 向量 + Chroma 索引（证据层）。

用法：HH_API_KEY=... python knowledge_base/embed.py
"""
import json
import re
from pathlib import Path

import chromadb

from embed_api import embed

GUIDE = Path("Data_Cleaning/process_ocr/output/guide.md")
CHROMA_DIR = Path("knowledge_base/chroma")
CHUNKS_PATH = Path("knowledge_base/chunks.json")


def chunk_pages():
    chunks, cur_page, cur_lines = [], None, []
    for line in GUIDE.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"<!-- ===== Page (\d+) ===== -->", line.strip())
        if m:
            if cur_page is not None:
                chunks.append({"页码": cur_page, "text": "\n".join(cur_lines).strip()})
            cur_page, cur_lines = int(m.group(1)), []
        else:
            cur_lines.append(line)
    if cur_page is not None:
        chunks.append({"页码": cur_page, "text": "\n".join(cur_lines).strip()})
    return [c for c in chunks if c["text"]]


def main():
    chunks = chunk_pages()
    texts = [c["text"] for c in chunks]
    print(f"chunks={len(texts)}, embedding via gateway ...")
    emb = embed(texts)

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    col = client.get_or_create_collection("guide", metadata={"hnsw:space": "cosine"})
    col.add(
        ids=[str(i) for i in range(len(texts))],
        documents=texts,
        embeddings=emb,
        metadatas=[{"页码": c["页码"]} for c in chunks],
    )
    CHUNKS_PATH.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    print(f"done: chroma={len(texts)} -> {CHROMA_DIR}")


if __name__ == "__main__":
    main()
