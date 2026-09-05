"""网关 bge-m3 嵌入（OpenAI 兼容 /v1/embeddings）。key 经环境变量注入，不落盘。"""
import os

import requests

EMBED_URL = os.environ.get("HH_EMBED_URL", "https://ai-route.huihaohealth.com/v1/embeddings")
API_KEY = os.environ.get("HH_API_KEY", "")
MODEL = os.environ.get("HH_EMBED_MODEL", "bge-m3")


def embed(texts, batch=32):
    out = []
    for i in range(0, len(texts), batch):
        r = requests.post(EMBED_URL, headers={"Authorization": f"Bearer {API_KEY}"},
                          json={"model": MODEL, "input": texts[i:i + batch]}, timeout=180,
                          proxies={"http": None, "https": None})
        r.raise_for_status()
        out.extend(d["embedding"] for d in r.json()["data"])
    return out
