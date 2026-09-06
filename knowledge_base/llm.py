"""LLM 调用 + 稳健 JSON 提取（兼容 qwen 的 content / claude 的 reasoning_content）。"""
import json
import os
import re
import time

import requests

CHAT_URL = os.environ.get("HH_API_URL", "https://ai-route.huihaohealth.com/v1/chat/completions")
API_KEY = os.environ.get("HH_API_KEY", "")
MODEL = os.environ.get("HH_MODEL", "qwen3.8-max")


def extract_json(text):
    """从混有思考/注释/散文的文本里，取出最后一个合法 JSON 对象。"""
    text = re.sub(r"//[^\n]*", "", text)  # 去 // 注释
    dec = json.JSONDecoder()
    best = None
    for i in range(len(text)):
        if text[i] == "{":
            try:
                obj, _ = dec.raw_decode(text[i:])
                if isinstance(obj, dict):
                    best = obj
            except Exception:
                continue
    return best or {}


def chat(prompt, timeout=300):
    for attempt in range(3):
        try:
            r = requests.post(CHAT_URL, headers={"Authorization": f"Bearer {API_KEY}"}, json={
                "model": MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0,
            }, timeout=timeout, proxies={"http": None, "https": None})
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            text = (msg.get("content") or "").strip() or (msg.get("reasoning_content") or "")
            return extract_json(text)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3)
    return {}
