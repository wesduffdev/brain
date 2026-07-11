"""Embedders — text → fixed-dimension vector behind the `EmbedderPort` seam
(reading R3, ADR 0038).

The DEFAULT is `HashingEmbedder`: a pure, deterministic, OFFLINE bag-of-words
hashing embedder. It tokenizes text, hashes each token to a bucket in a
fixed-dimension vector, and counts occurrences — so passages that share
vocabulary land close under cosine similarity, with NO model download, NO
network, and NO heavy dependency. It uses a stable content hash (blake2b), never
Python's per-process-salted `hash()`, so the same text always embeds to the same
vector across processes and runs — the property the retrieval tests rest on.

`SentenceTransformerEmbedder` is the real, semantic embedder (bge-small /
all-MiniLM). It is a config-selected, LAZILY-imported option: `sentence_transformers`
is never imported at module load, `available()` reports whether the host has it
(without importing it), and constructing/using it without the library refuses
LOUDLY — mirroring the MLX / torch / espeak availability gates elsewhere. It
never fakes an embedding.

`build_embedder(policy)` selects between them from a `KnowledgeRetrievalPolicy`,
defaulting to the offline hashing embedder.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
from typing import Tuple

from app.policies import KnowledgeRetrievalPolicy

_TOKEN = re.compile(r"[a-z0-9]+")

# A compact English stopword set. Bag-of-words retrieval is sensitive to function
# words ("a", "and", "the", "about"...): they carry no topical signal but would
# otherwise dominate the cosine of a natural-language query. Dropping them (and
# one-character tokens) leaves the CONTENT words that actually distinguish one
# passage from another. This is an intrinsic part of the embedder's tokenization,
# not a tuning knob — like the token regex — so it lives in code, not config.
_STOPWORDS = frozenset(
    """a an and are as at be but by for from has have he her his i in is it its me
    my of on or our she that the their them they this to was we were what when
    which who will with you your about over into onto""".split()
)

# The single explanation of what a host needs for the real embedder — used by the
# constructor's guard so the requirement is stated in one place.
_ST_REQUIREMENT = (
    "the sentence-transformers embedder needs `sentence-transformers` installed "
    "(pip install sentence-transformers) to download and run a local embedding "
    "model (e.g. bge-small-en-v1.5 / all-MiniLM-L6-v2). The default `hashing` "
    "embedder is fully offline and needs nothing — select it in "
    "config/language.yaml (retrieval.embedder) to run without the library."
)


def _tokens(text: str) -> list:
    """The CONTENT tokens of `text`: lowercased alphanumeric runs, with stopwords
    and single-character tokens dropped so only topical words are embedded."""
    return [
        token
        for token in _TOKEN.findall(text.lower())
        if len(token) > 1 and token not in _STOPWORDS
    ]


class HashingEmbedder:
    """A deterministic, offline bag-of-words hashing embedder (the default). Each
    token is hashed (blake2b, content-stable) into one of `dim` buckets and
    counted, so the vector is a fixed-dimension term-frequency signature. Pure: no
    model, no network, no randomness — identical text always yields an identical
    vector."""

    def __init__(self, dim: int = 256) -> None:
        if dim <= 0:
            raise ValueError(f"embedding dim must be positive, got {dim}")
        self._dim = int(dim)

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> Tuple[float, ...]:
        vector = [0.0] * self._dim
        for token in _tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest, "big") % self._dim
            vector[bucket] += 1.0
        return tuple(vector)


class SentenceTransformerEmbedder:
    """The real, semantic embedder behind the same port — GATED and lazily
    imported. `sentence_transformers` is imported only when the model is first
    needed; constructing this without the library installed refuses loudly
    (naming what the host needs) rather than faking an embedding."""

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5") -> None:
        if not self.available():
            raise RuntimeError("cannot build the sentence-transformers embedder: " + _ST_REQUIREMENT)
        self._model_name = model
        self._model = None  # loaded lazily on first embed

    @staticmethod
    def available() -> bool:
        """True when `sentence_transformers` is importable — checked WITHOUT
        importing it (find_spec only), so the gate never pulls in the optional
        dependency."""
        return importlib.util.find_spec("sentence_transformers") is not None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415 — lazy, gated

            self._model = SentenceTransformer(self._model_name)
        return self._model

    @property
    def dim(self) -> int:
        return int(self._load().get_sentence_embedding_dimension())

    def embed(self, text: str) -> Tuple[float, ...]:
        vector = self._load().encode(text, normalize_embeddings=False)
        return tuple(float(x) for x in vector)


def build_embedder(policy: KnowledgeRetrievalPolicy):
    """The embedder a `KnowledgeRetrievalPolicy` selects — the deterministic
    offline `HashingEmbedder` by default, or the gated `SentenceTransformerEmbedder`
    when `policy.embedder == "sentence-transformers"`. Selecting the embedder is a
    config change only (config/language.yaml `retrieval.embedder`)."""
    kind = (policy.embedder or "hashing").lower()
    if kind in ("hashing", "hash", "bow", "deterministic"):
        return HashingEmbedder(dim=policy.dim)
    if kind in ("sentence-transformers", "sentence_transformers", "st"):
        return SentenceTransformerEmbedder(model=policy.model)
    raise ValueError(
        f"unknown retrieval embedder {policy.embedder!r}; "
        f"known: 'hashing' (offline default), 'sentence-transformers' (gated)"
    )
