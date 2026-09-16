"""Embeddings for pattern matching and originality.

Local by default so the unit suite needs no network and no key. sentence-transformers
gives better quality and is used automatically when installed. The hashing embedder is
a real fallback, not a stub: deterministic character n-gram hashing, which is weak at
paraphrase but perfectly serviceable for near-duplicate detection.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

_WORD = re.compile(r"[a-z0-9']+")
DIMS = 384


def tokenize(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


# Keys are apostrophe free on purpose. Apostrophes are stripped BEFORE this map is
# applied, so "don't", "dont" and "don\u2019t" all normalize to the same thing. Without
# that, a near-verbatim copy typed without apostrophes reads as original.
CONTRACTIONS = {
    "dont": "do not", "wont": "will not", "cant": "cannot", "cannot": "cannot",
    "im": "i am", "youre": "you are", "its": "it is", "thats": "that is",
    "didnt": "did not", "doesnt": "does not", "shouldnt": "should not",
    "couldnt": "could not", "wouldnt": "would not", "isnt": "is not",
    "arent": "are not", "wasnt": "was not", "werent": "were not",
    "havent": "have not", "hasnt": "has not", "hadnt": "had not",
    "youve": "you have", "youll": "you will", "youd": "you would",
    "ive": "i have", "ill": "i will", "id": "i would", "theyre": "they are",
    "weve": "we have", "were": "we are", "theres": "there is", "heres": "here is",
    "whats": "what is", "lets": "let us", "aint": "is not",
}


def normalize_text(text: str) -> str:
    out = (text or "").lower()
    out = out.replace("\u2019", "").replace("\u02bc", "").replace("'", "")
    out = re.sub(r"[^\w\s]", " ", out)
    words = out.split()
    words = [CONTRACTIONS.get(w, w) for w in words]
    return re.sub(r"\s+", " ", " ".join(words)).strip()


class Embedder(Protocol):
    name: str
    dims: int

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    name = "hashing"
    dims = DIMS

    def __init__(self, dims: int = DIMS) -> None:
        self.dims = dims

    def _features(self, text: str) -> list[str]:
        words = tokenize(normalize_text(text))
        feats = list(words)
        feats += [f"{a}_{b}" for a, b in zip(words, words[1:])]
        joined = "".join(words)
        feats += [joined[i:i + 5] for i in range(max(0, len(joined) - 4))]
        return feats

    def encode(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dims
            for feature in self._features(text):
                digest = hashlib.sha1(feature.encode()).digest()
                idx = int.from_bytes(digest[:4], "big") % self.dims
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vec[idx] += sign
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class SentenceTransformerEmbedder:
    name = "sentence-transformers"

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self.dims = self._model.get_sentence_embedding_dimension()

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.encode(texts, normalize_embeddings=True)]


def get_embedder(prefer_local_model: bool = True) -> Embedder:
    if prefer_local_model:
        try:
            return SentenceTransformerEmbedder()
        except Exception:  # noqa: BLE001 - optional dependency, fallback is real
            pass
    return HashingEmbedder()


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)
