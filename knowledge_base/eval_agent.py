"""端到端评测：agent 判断+检索 vs xlsx 真实-标准答案（0-2 分制 + 高风险错误）。

用法：HH_API_KEY=... python knowledge_base/eval_agent.py
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from agent import Agent
from extract_case import CASE_JSON, extract_case_text
from gold_standard import SIX, SCORING, load_real_gold

CHAT_URL = os.environ.get("HH_API_URL", "https://ai-route.huihaohealth.com/v1/chat/completions")
API_KEY = os.environ.get("HH_API_KEY", "")
MODEL = os.environ.get("HH_MODEL", "claude-opus-4-7-cc")


def judge(cid, gold, agent_out):
    gold_six = {k: gold.get(k, "") for k in SIX}
    prompt = f"""你是乳腺癌诊疗知识库的评测专家。按 0-2 分给 agent 输出打六项分，并检查高风险错误。

评分标准：2=正确且依据充分；1=部分正确或有遗漏；0=错误、漏答或无依据。
关键：金标准要求「资料不足/不得推荐/待核验」时，agent 若正确判断「资料不足/未知/不检索方案」，该项给 2 分（不是 0 分）；方向一致但不够完整给 1 分。

【金标准六项】
{json.dumps(gold_six, ensure_ascii=False, indent=1)}

【agent 输出】
{json.dumps(agent_out, ensure_ascii=False, indent=1)}

额外检查是否命中以下高风险错误（命中的填进数组，未命中给空数组）：
1. 将未提供信息判为阴性/正常
2. 将肝转移直接判为内脏危象
3. 混淆双侧病灶受体
4. 活动性脑转移未转人工
5. 严重骨髓抑制仍直接推荐治疗

只输出 JSON：
{{"人群判断":0-2,"当前治疗线":0-2,"治疗建议":0-2,"证据依据":0-2,"风险提示":0-2,"资料不足补充":0-2,"高风险错误":["..."],"理由":"一句话"}}"""

    for attempt in range(3):
        try:
            r = requests.post(CHAT_URL, headers={"Authorization": f"Bearer {API_KEY}"}, json={
                "model": MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0,
            }, timeout=300, proxies={"http": None, "https": None})
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            m = re.search(r"\{.*\}", content, re.S)
            return json.loads(m.group(0)) if m else {}
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3)


def verdict(total):
    for name, (lo, hi) in SCORING["判定"].items():
        if lo <= total <= hi:
            return name
    return "?"


def main():
    if not API_KEY:
        sys.exit("缺 HH_API_KEY")
    golds = load_real_gold()
    agent = Agent()
    print(f"model={MODEL} cases={len(golds)}（xlsx 真实-标准答案，0-2 分制）\n")

    totals = {}
    for cid, gold in golds.items():
        case_text = extract_case_text(CASE_JSON[cid])
        out = agent.run(case_text)
        v = judge(cid, gold, out)
        total = sum(int(v.get(k, 0)) for k in SIX)
        totals[cid] = total
        hi = v.get("高风险错误") or []
        print(f"{cid}: {total}/12 [{verdict(total)}]  人群={out.get('人群')} 阶段={out.get('治疗阶段')} 充足={out.get('资料充足')}")
        print(f"    分: " + " ".join(f"{k}={v.get(k,'?')}" for k in SIX))
        if hi:
            print(f"    高风险错误: {'；'.join(hi)}")
        if v.get("理由"):
            print(f"    理由: {v['理由']}")

    avg = sum(totals.values()) / len(totals)
    print(f"\n平均分 = {avg:.1f}/12")


if __name__ == "__main__":
    main()
