"""最小 agent 层：病例 → 推导（人群/阶段/线次/资料充足/风险）+ 检索。

LLM 先判断「资料是否充足、该进哪个人群/阶段」，充足才调知识库检索方案，
不足则停手并列出需补充信息——对应金标准里「资料不足时停止确定性推荐」。
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from retrieve import Retriever

CHAT_URL = os.environ.get("HH_API_URL", "https://ai-route.huihaohealth.com/v1/chat/completions")
API_KEY = os.environ.get("HH_API_KEY", "")
MODEL = os.environ.get("HH_MODEL", "claude-opus-4-7-cc")

SCHEMA = """{
  "人群": "HER2+ 或 HR+ 或 三阴性 或 HER2低表达 或 未知",
  "治疗阶段": "新辅助 或 辅助 或 晚期解救 或 未知",
  "分层条件": "曲妥珠单抗敏感/失败、一线/二线、pCR/non-pCR 等，未知则留空字符串",
  "资料充足": true 或 false,
  "需补充": ["缺的检查/病理/分期/治疗时间轴等"],
  "风险提示": ["高龄、合并症、受体不一致等"]
}"""


class Agent:
    def __init__(self):
        self.retriever = Retriever()

    def derive(self, case_text):
        prompt = f"""你是乳腺癌诊疗决策 agent 的入口。根据患者病历摘要，提取判断信息。

患者病历摘要：
{case_text}

只输出一个 JSON，字段如下：
{SCHEMA}

「资料充足」= 是否已具备进入 HER2+ 乳腺癌决策树所需的关键信息（病理受体、分期、既往治疗时间轴）。
信息不足时，「人群/治疗阶段」给「未知」，且「资料充足」为 false。"""

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

    def run(self, case_text):
        d = self.derive(case_text)
        pop = d.get("人群")
        stage = d.get("治疗阶段")
        strat = d.get("分层条件") or None
        if d.get("资料充足") and pop in ("HER2+", "HR+", "三阴性", "HER2低表达") and stage:
            out = self.retriever.query(stage, pop, strat)
            d["方案"] = out["答案层"][:5]
        else:
            d["方案"] = []
        return d


if __name__ == "__main__":
    if not API_KEY:
        sys.exit("缺 HH_API_KEY")
    a = Agent()
    print(json.dumps(a.run("女，63岁，右乳HER2阳性、HR阴性，肝骨多发转移，IV期。"), ensure_ascii=False, indent=2))
