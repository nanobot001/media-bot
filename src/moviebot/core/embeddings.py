import struct
import os
import hashlib
import random
import httpx
from typing import List
from moviebot.config import settings

def encode_vector(vector: List[float]) -> bytes:
    """Pack a list of 768 floats into a binary BLOB (3072 bytes)."""
    if len(vector) != 768:
        raise ValueError(f"Vector must be exactly 768 dimensions, got {len(vector)}")
    return struct.pack('f' * 768, *vector)

def decode_vector(blob: bytes) -> List[float]:
    """Unpack binary BLOB bytes back into a list of 768 floats."""
    if not blob:
        return []
    if len(blob) != 768 * 4:
        raise ValueError(f"BLOB size must be exactly {768 * 4} bytes, got {len(blob)}")
    return list(struct.unpack('f' * 768, blob))

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Calculate cosine similarity between two float vectors using pure Python."""
    if len(v1) != len(v2) or not v1:
        return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_a = sum(a * a for a in v1) ** 0.5
    norm_b = sum(b * b for b in v2) ** 0.5
    if not norm_a or not norm_b:
        return 0.0
    return dot_product / (norm_a * norm_b)

def get_mock_embedding(text: str) -> List[float]:
    """Generate a deterministic, L2-normalized 768-dimensional mock vector for testing/offline fallback."""
    if not text:
        return [0.0] * 768
    h = hashlib.sha256(text.encode("utf-8")).digest()
    rng = random.Random(h)
    vector = [rng.uniform(-1.0, 1.0) for _ in range(768)]
    # L2 normalize
    norm = sum(x * x for x in vector) ** 0.5
    if norm > 0:
        vector = [x / norm for x in vector]
    return vector

def get_configured_model() -> str:
    """Return the name of the configured embedding model based on settings."""
    gemini_key = settings.gemini_api_key or os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        return "text-embedding-004"
    return settings.ollama_model or "nomic-embed-text"

async def get_embedding(text: str) -> List[float]:
    """Retrieve embedding vector for target text. Falls back to Ollama or Mock if unavailable."""
    if not text:
        return [0.0] * 768

    # 1. Try Google Gemini if API Key is present
    gemini_key = settings.gemini_api_key or os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={gemini_key}"
        payload = {
            "content": {
                "parts": [{"text": text}]
            }
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    values = data.get("embedding", {}).get("values")
                    if values and len(values) == 768:
                        return values
        except Exception:
            pass

    # 2. Try Local Ollama if configured
    ollama_url = settings.ollama_url or "http://localhost:11434"
    ollama_model = settings.ollama_model or "nomic-embed-text"
    if ollama_url:
        url = f"{ollama_url.rstrip('/')}/api/embeddings"
        payload = {
            "model": ollama_model,
            "prompt": text
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    embedding = data.get("embedding")
                    if not embedding and "embeddings" in data:
                        embedding = data["embeddings"][0]
                    if embedding and len(embedding) == 768:
                        return embedding
        except Exception:
            pass

    # 3. Fallback to deterministic L2 normalized mock vector
    return get_mock_embedding(text)
