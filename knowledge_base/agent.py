"""最小 agent 层：病例 → 推导（人群/阶段/线次/资料充足/风险）+ 检索。

LLM 先判断「资料是否充足、该进哪个人群/阶段」，充足才调知识库检索方案，
不足则停手并列出需补充信息——对应金标准里「资料不足时停止确定性推荐」。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from llm import chat
from retrieve import Retriever

SCHEMA = """{
  "人群": "HER2+ 或 HR+ 或 三阴性 或 HER2低表达 或 未知（检索用的粗标签）",
  "人群判断": "符合/不符合/部分符合/待核验 + 一句依据（受体状态、双侧病灶、原发灶vs转移灶），如「符合HER2+（右侧）；左侧FISH未扩增不混用」或「不符合：HER2 IHC 1+属低表达非阳性」",
  "治疗阶段": "新辅助 或 辅助 或 晚期解救 或 未知",
  "分层条件": "曲妥珠单抗敏感/失败、一线/二线、pCR/non-pCR 等，未知则留空字符串",
  "资料充足": true 或 false,
  "治疗建议": "一句话临床判断（能推荐则给方向+依据；活动性脑转移→先转CNS MDT局部治疗；严重骨髓抑制→先处理再评估；资料不足→不推荐确定方案）",
  "高风险": ["命中的高风险错误，如「活动性脑转移未转人工」「严重骨髓抑制仍直接推荐」「混淆双侧病灶受体」「将肝转移直接判为内脏危象」「将未提供信息判为阴性」，未命中给空数组"],
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

关键判定规则：
- 「人群判断」要给出明确结论（符合/不符合/部分符合/待核验）+ 一句依据。
- HER2 IHC 1+ 属「低表达」、IHC 2+ 未做 FISH 属「待核验」，都不能判为 HER2+；只有 IHC 3+ 或 FISH 扩增才是 HER2+。
- 双侧乳腺或多病灶受体不一致时，分别说明、不能混用（如「右侧 HER2+、左侧 FISH 未扩增」）。
- 原发灶与转移灶受体可能不一致，需区分。
- 「治疗建议」给的是**临床判断**，不是机械罗列方案：多线/脑转移/严重骨髓抑制/内脏危象时，宁可说「先转 MDT / 先处理 / 暂缓」，也不直接套用标准一线方案。
- 「高风险」只填命中的那几类；没命中给空数组。
- 「资料充足」= 是否已具备进入 HER2+ 乳腺癌决策树所需的关键信息（病理受体、分期、既往治疗时间轴）。信息不足时「人群/治疗阶段」给「未知」、「资料充足」false。"""

        return chat(prompt)

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
