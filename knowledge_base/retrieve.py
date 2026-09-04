"""查询接口：结构化精确匹配（答案层）+ BM25 + 向量 RRF（证据层）→ {命中,答案层,证据层}。

向量走网关 bge-m3（HH_API_KEY），无 key 时退化为 BM25 单路。
"""
import json
import os
import pickle
import re
from pathlib import Path

import chromadb
from rank_bm25 import BM25Okapi

from embed_api import embed

RECORDS = Path("knowledge_base/records.json")
CHUNKS = Path("knowledge_base/chunks.json")
BM25 = Path("knowledge_base/bm25.pkl")
CHROMA_DIR = Path("knowledge_base/chroma")

LEVEL_ORDER = {"Ⅰ": 0, "Ⅱ": 1, "Ⅲ": 2}


def tokenize(text):
    return re.findall(r"[一-鿿]|[A-Za-z0-9]+", text.lower())


class Retriever:
    def __init__(self):
        self.records = json.loads(RECORDS.read_text(encoding="utf-8"))
        self.chunks = json.loads(CHUNKS.read_text(encoding="utf-8"))
        with open(BM25, "rb") as f:
            self.bm = pickle.load(f)
        self.col = None
        if os.environ.get("HH_API_KEY") and CHROMA_DIR.exists():
            self.col = chromadb.PersistentClient(path=str(CHROMA_DIR)).get_collection("guide")

    def strat_match(self, query, cond):
        q = query.lower().replace(" ", "")
        c = cond.lower().replace(" ", "")
        qt = set(re.findall(r"[a-z0-9]+", q))
        ct = set(re.findall(r"[a-z0-9]+", c))
        if qt and ct and (qt & ct):
            return True
        qb = set(re.findall(r"[一-鿿]{2}", q))
        cb = set(re.findall(r"[一-鿿]{2}", c))
        if qb and cb:
            return len(qb & cb) / len(qb) >= 0.4
        return q in c or c in q

    def structured(self, stage, pop, strat):
        base = [r for r in self.records if r["治疗阶段"] == stage and r["人群"] == pop]
        if strat:
            sub = [r for r in base if self.strat_match(strat, r["分层条件"])]
            matched, hit = (sub, True) if sub else (base, False)
        else:
            matched, hit = base, bool(base)
        matched.sort(key=lambda r: LEVEL_ORDER.get(r["推荐等级"], 9))
        return matched, hit

    def narrative(self, query_text, k=3):
        scores = self.bm.get_scores(tokenize(query_text))
        bm_ranked = sorted(range(len(scores)), key=lambda i: -scores[i])[: k * 3]

        rrf = {}
        for rank, i in enumerate(bm_ranked):
            rrf[i] = rrf.get(i, 0) + 1 / (60 + rank + 1)

        if self.col:
            try:
                vec = embed([query_text])[0]
                res = self.col.query(query_embeddings=[vec], n_results=k * 3)
                for rank, i in enumerate(int(x) for x in res["ids"][0]):
                    rrf[i] = rrf.get(i, 0) + 1 / (60 + rank + 1)
            except Exception:
                pass

        top = sorted(rrf, key=lambda i: -rrf[i])[:k]
        return [{"页码": self.chunks[i]["页码"], "text": self.chunks[i]["text"][:200]} for i in top]

    def query(self, stage, pop, strat):
        matched, hit = self.structured(stage, pop, strat)
        answer = [{
            "方案": r["方案"], "推荐等级": r["推荐等级"],
            "证据类别": r["证据类别"], "来源页码": r["来源页码"],
        } for r in matched]
        evidence = self.narrative(f"{stage} {pop} {strat or ''}".strip())
        return {"命中": hit, "答案层": answer, "证据层": evidence}


if __name__ == "__main__":
    r = Retriever()
    out = r.query("辅助", "HER2+", "新辅助治疗后未达pCR")
    print(json.dumps(out, ensure_ascii=False, indent=2))
