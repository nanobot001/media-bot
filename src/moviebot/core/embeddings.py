import struct
import os
import hashlib
import random
import httpx
from dataclasses import dataclass
from typing import List
from moviebot.config import settings

MOCK_EMBEDDING_MODEL = "mock-hash-v1"
DEFAULT_EMBEDDING_DIM = 768


def _normalize_gemini_model(model: str) -> str:
    m = model or "gemini-embedding-001"
    if m.startswith("models/"):
        return m[len("models/"):]
    return m


@dataclass(frozen=True)
class EmbeddingResult:
    vector: List[float]
    model: str
    dim: int
    source: str
    fallback: bool = False


def encode_vector(vector: List[float]) -> bytes:
    """Pack a list of 768 floats into a binary BLOB (3072 bytes)."""
    if len(vector) != DEFAULT_EMBEDDING_DIM:
        raise ValueError(f"Vector must be exactly {DEFAULT_EMBEDDING_DIM} dimensions, got {len(vector)}")
    return struct.pack('f' * DEFAULT_EMBEDDING_DIM, *vector)

def decode_vector(blob: bytes) -> List[float]:
    """Unpack binary BLOB bytes back into a list of 768 floats."""
    if not blob:
        return []
    expected_size = DEFAULT_EMBEDDING_DIM * 4
    if len(blob) != expected_size:
        raise ValueError(f"BLOB size must be exactly {expected_size} bytes, got {len(blob)}")
    return list(struct.unpack('f' * DEFAULT_EMBEDDING_DIM, blob))

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
        return [0.0] * DEFAULT_EMBEDDING_DIM
    h = hashlib.sha256(text.encode("utf-8")).digest()
    rng = random.Random(h)
    vector = [rng.uniform(-1.0, 1.0) for _ in range(DEFAULT_EMBEDDING_DIM)]
    # L2 normalize
    norm = sum(x * x for x in vector) ** 0.5
    if norm > 0:
        vector = [x / norm for x in vector]
    return vector

def get_configured_model() -> str:
    """Return the name of the configured embedding model based on settings."""
    gemini_key = settings.gemini_api_key or os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        return _normalize_gemini_model(settings.gemini_embedding_model)
    return settings.ollama_model or "nomic-embed-text"

async def get_embedding(text: str) -> List[float]:
    """Retrieve embedding vector for target text. Falls back to Ollama or Mock if unavailable."""
    result = await get_embedding_result(text)
    return result.vector


async def get_embedding_result(text: str) -> EmbeddingResult:
    """Retrieve embedding vector plus the actual provider/model used."""
    if not text:
        return EmbeddingResult([0.0] * DEFAULT_EMBEDDING_DIM, MOCK_EMBEDDING_MODEL, DEFAULT_EMBEDDING_DIM, "mock", fallback=True)

    # 1. Try Google Gemini if API Key is present
    gemini_key = settings.gemini_api_key or os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        gemini_model = _normalize_gemini_model(settings.gemini_embedding_model)
        dim = settings.embedding_dim or DEFAULT_EMBEDDING_DIM
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:embedContent"
        payload = {
            "content": {
                "parts": [{"text": text}]
            },
            "output_dimensionality": dim,
            "task_type": "SEMANTIC_SIMILARITY"
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, headers={"x-goog-api-key": gemini_key}, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    values = data.get("embedding", {}).get("values")
                    if values and len(values) == dim:
                        return EmbeddingResult(values, gemini_model, dim, "gemini", fallback=False)
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
                    if embedding and len(embedding) == DEFAULT_EMBEDDING_DIM:
                        return EmbeddingResult(embedding, ollama_model, DEFAULT_EMBEDDING_DIM, "ollama", fallback=bool(gemini_key))
        except Exception:
            pass

    # 3. Fallback to deterministic L2 normalized mock vector
    return EmbeddingResult(get_mock_embedding(text), MOCK_EMBEDDING_MODEL, DEFAULT_EMBEDDING_DIM, "mock", fallback=True)


def build_composite_document(
    title: str,
    year: int | None,
    genres: list | str | None,
    tones: list | str | None,
    themes: list | str | None,
    synopsis: str | None
) -> str:
    """Constructs a composite search document from movie metadata."""
    import json
    
    def parse_list(val) -> str:
        if not val:
            return ""
        if isinstance(val, list):
            return ", ".join(str(x) for x in val)
        if isinstance(val, str):
            val_stripped = val.strip()
            if not val_stripped:
                return ""
            if val_stripped.startswith("[") and val_stripped.endswith("]"):
                try:
                    parsed = json.loads(val_stripped)
                    if isinstance(parsed, list):
                        return ", ".join(str(x) for x in parsed)
                except Exception:
                    pass
            return val_stripped
        return str(val)

    genres_str = parse_list(genres)
    tones_str = parse_list(tones)
    themes_str = parse_list(themes)
    syn_str = synopsis or ""

    return (
        f"Title: {title} ({year or ''})\n"
        f"Genres: {genres_str}\n"
        f"Tones: {tones_str}\n"
        f"Themes: {themes_str}\n"
        f"Synopsis: {syn_str}"
    )


def get_composite_document_hash(doc_text: str) -> str:
    """Generates a SHA256 hex digest of the composite document."""
    return hashlib.sha256(doc_text.encode("utf-8")).hexdigest()

