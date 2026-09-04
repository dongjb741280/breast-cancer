"""查询接口：结构化精确匹配（答案层）+ BM25（证据层）→ {命中,答案层,证据层}。

向量（bge-m3）暂缺：transformers 5.x 与 bge-m3 不兼容，待 pin 版本后补 dense 路。
当前证据层用 BM25 单路；结构化答案层无需模型。
"""
import json
import pickle
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

RECORDS = Path("knowledge_base/records.json")
CHUNKS = Path("knowledge_base/chunks.json")
BM25 = Path("knowledge_base/bm25.pkl")

LEVEL_ORDER = {"Ⅰ": 0, "Ⅱ": 1, "Ⅲ": 2}


def tokenize(text):
    return re.findall(r"[一-鿿]|[A-Za-z0-9]+", text.lower())


class Retriever:
    def __init__(self):
        self.records = json.loads(RECORDS.read_text(encoding="utf-8"))
        self.chunks = json.loads(CHUNKS.read_text(encoding="utf-8"))
        with open(BM25, "rb") as f:
            self.bm = pickle.load(f)

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
        top = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
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
