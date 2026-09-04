"""检索层评测：recall@3 / precision@3（离线）。

ground truth = 金标准文本里出现的方案名（模糊匹配）。
注意：金标准是叙事性的（六项评测），方案名多为「既往治疗」上下文而非「答案」，
故 recall@3 是弱代理；真正的端到端评测是 LLM-as-judge（需 API key，见 07 票）。
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from retrieve import Retriever

REAL_MD = Path("Data_Cleaning/doc/系统输入/7例真实病例-患者基本情况与诊疗金标准.md")
RECORDS = Path("knowledge_base/records.json")


def load_vocab():
    return sorted({r["方案"] for r in json.loads(RECORDS.read_text(encoding="utf-8"))}, key=len, reverse=True)


def extract_mentions(text, vocab):
    t = text.replace(" ", "")
    return {v for v in vocab if v.replace(" ", "") in t}


def parse_cases(md):
    text = md.read_text(encoding="utf-8")
    parts = re.split(r"\n## (REAL-\d+)\n", text)
    return [(parts[i], parts[i + 1]) for i in range(1, len(parts), 2)]


def derive_query(body):
    stage = pop = line = None
    if "晚期" in body or "转移" in body:
        stage = "晚期解救"
    elif "新辅助" in body:
        stage = "新辅助"
    elif "辅助" in body:
        stage = "辅助"
    if "三阴性" in body:
        pop = "三阴性"
    elif "HER2" in body:
        pop = "HER2+"
    elif "激素受体阳性" in body or "HR阳性" in body:
        pop = "HR+"
    if "一线" in body:
        line = "一线"
    elif "二线" in body:
        line = "二线"
    return stage, pop, line


def main():
    vocab = load_vocab()
    r = Retriever()
    cases = parse_cases(REAL_MD)
    print(f"cases={len(cases)} vocab={len(vocab)}\n")

    recall_sum = prec_sum = n = 0
    for cid, body in cases:
        mentions = extract_mentions(body, vocab)
        stage, pop, line = derive_query(body)
        print(f"{cid}: 阶段={stage} 人群={pop} 线={line} 提到方案={sorted(mentions)}")
        if mentions and stage and pop:
            out = r.query(stage, pop, line or "")
            top3 = [a["方案"] for a in out["答案层"][:3]]
            hit = len(set(mentions) & set(top3))
            rec, prec = hit / len(mentions), hit / 3
            recall_sum += rec
            prec_sum += prec
            n += 1
            print(f"    top3={top3} -> recall@3={rec:.2f} precision@3={prec:.2f}")
    print(f"\n可评测 case 数={n}/{len(cases)}")
    if n:
        print(f"avg recall@3={recall_sum/n:.3f}  avg precision@3={prec_sum/n:.3f}")


if __name__ == "__main__":
    main()
