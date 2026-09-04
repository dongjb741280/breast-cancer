"""LLM-as-judge：判断知识库检索到的方案是否与金标准「治疗建议」一致（需 API key）。

对 7 例 REAL 病例，用每例的真实人群/阶段/线次作查询跑检索，
再让 LLM 对照金标准「治疗建议」打 pass/fail，并给理由。

用法：HH_API_KEY=... python knowledge_base/judge.py
"""
import json
import os
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from retrieve import Retriever

API_URL = os.environ.get("HH_API_URL", "https://ai-route.huihaohealth.com/v1/chat/completions")
API_KEY = os.environ.get("HH_API_KEY", "")
MODEL = os.environ.get("HH_MODEL", "qwen3.8-max")

REAL_MD = Path("Data_Cleaning/doc/系统输入/7例真实病例-患者基本情况与诊疗金标准.md")

# 每例的查询（人工映射，代表 agent 应产出的正确查询；agent 本身未建）
QUERIES = {
    "REAL-001": ("辅助", "HR+", None),
    "REAL-002": ("晚期解救", "HER2+", "曲妥珠单抗敏感"),
    "REAL-003": ("晚期解救", "HER2低表达", None),
    "REAL-004": ("辅助", "HER2+", None),
    "REAL-005": ("晚期解救", "HR+", None),
    "REAL-006": ("晚期解救", "HER2+", "曲妥珠单抗失败"),
    "REAL-007": ("晚期解救", "HER2+", None),
}


def parse_cases(md):
    text = md.read_text(encoding="utf-8")
    parts = re.split(r"\n## (REAL-\d+)\n", text)
    return [(parts[i], parts[i + 1]) for i in range(1, len(parts), 2)]


def judge_case(case_id, body, answer):
    prompt = f"""你是乳腺癌诊疗知识库的评测专家。判断「知识库检索到的方案」是否与「病例金标准的治疗建议」一致。

【病例金标准】
{body}

【知识库检索到的方案（方案 / 推荐等级 / 证据类别）】
{json.dumps(answer, ensure_ascii=False, indent=1)}

只输出一个 JSON：{{"结果":"pass" 或 "fail","理由":"一句话，说明一致或哪里不一致"}}"""

    r = requests.post(API_URL, headers={"Authorization": f"Bearer {API_KEY}"}, json={
        "model": MODEL, "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }, timeout=120)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", content, re.S)
    return json.loads(m.group(0)) if m else {}


def main():
    if not API_KEY:
        print("缺 HH_API_KEY 环境变量", file=sys.stderr)
        sys.exit(1)
    retriever = Retriever()
    cases = parse_cases(REAL_MD)
    print(f"judge model={MODEL} cases={len(cases)}\n")

    n_pass = 0
    for cid, body in cases:
        stage, pop, strat = QUERIES[cid]
        out = retriever.query(stage, pop, strat)
        answer = out["答案层"][:5]
        v = judge_case(cid, body, answer)
        verdict = v.get("结果")
        ok = verdict == "pass"
        n_pass += ok
        print(f"{cid} ({stage}/{pop}/{strat}): {verdict} — {v.get('理由', '')}")
    print(f"\npass {n_pass}/{len(cases)} = {n_pass/len(cases):.2f}")


if __name__ == "__main__":
    main()
