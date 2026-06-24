import os
from openai import OpenAI

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client

def embed(texts: list[str]) -> list[list[float]]:
    resp = _get_client().embeddings.create(
        model="text-embedding-3-small",
        input=texts,
        dimensions=768,
    )
    return [e.embedding for e in resp.data]

def embed_one(text: str) -> list[float]:
    return embed([text])[0]
