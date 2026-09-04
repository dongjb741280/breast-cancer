"""guide.md -> 分页 chunk + BM25 索引（证据层，无需模型）。"""
import json
import pickle
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

GUIDE = Path("Data_Cleaning/process_ocr/output/guide.md")
BM25_PATH = Path("knowledge_base/bm25.pkl")
CHUNKS_PATH = Path("knowledge_base/chunks.json")


def tokenize(text):
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
    bm = BM25Okapi([tokenize(t) for t in texts])
    with open(BM25_PATH, "wb") as f:
        pickle.dump(bm, f)
    CHUNKS_PATH.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    print(f"done: bm25 over {len(texts)} chunks -> {BM25_PATH}")


if __name__ == "__main__":
    main()
