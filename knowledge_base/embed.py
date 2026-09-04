"""guide.md -> 分页 chunk，bge-m3 向量 + Chroma + BM25 索引（证据层）。"""
import json
import pickle
import re
from pathlib import Path

import chromadb
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

GUIDE = Path("Data_Cleaning/process_ocr/output/guide.md")
CHROMA_DIR = Path("knowledge_base/chroma")
BM25_PATH = Path("knowledge_base/bm25.pkl")
CHUNKS_PATH = Path("knowledge_base/chunks.json")


def tokenize(text):
    # 中文按单字、英文/数字按词
    return re.findall(r"[一-鿿]|[A-Za-z0-9]+", text.lower())


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
    print(f"chunks={len(texts)}")

    print("loading bge-m3 ...")
    model = SentenceTransformer("BAAI/bge-m3")
    emb = model.encode(texts, normalize_embeddings=True, show_progress_bar=True)

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    col = client.get_or_create_collection("guide")
    col.add(
        ids=[str(i) for i in range(len(texts))],
        documents=texts,
        embeddings=emb.tolist(),
        metadatas=[{"页码": c["页码"]} for c in chunks],
    )

    bm = BM25Okapi([tokenize(t) for t in texts])
    with open(BM25_PATH, "wb") as f:
        pickle.dump(bm, f)
    CHUNKS_PATH.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")

    print(f"done: chroma={len(texts)} bm25={len(texts)}")


if __name__ == "__main__":
    main()
