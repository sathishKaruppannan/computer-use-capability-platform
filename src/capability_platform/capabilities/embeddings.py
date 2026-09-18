"""Optional real embedding provider for CapabilityRegistry's retrieval step -- an opt-in upgrade
over the dependency-free hashing trick (registry.py::_embedding), wired in by runtime.py only
when OPENAI_API_KEY is configured; falls back to the hashing trick automatically otherwise. See
registry.py::_embedding's docstring for the full reasoning on why a real provider isn't the
default.

Deliberately NOT a vector database: a vector DB solves persistent storage and approximate
nearest-neighbor search at scale, neither of which this project's handful of capabilities need
(a brute-force cosine scan over ~6 vectors is microseconds, and capabilities are cheap to
re-embed from the artifact store on startup). The actual cost a real, network-calling provider
introduces is re-embedding the same unchanged text on every request, since
runtime.py::capability_registry() rebuilds CapabilityRegistry from scratch on every call --
cached_embedding_fn() below is the right-sized fix for that specific problem: a plain
content-hash-keyed cache, not a database.
"""

from __future__ import annotations

import hashlib

from openai import OpenAI

from capability_platform.capabilities.registry import EmbeddingFn


def openai_embedding_fn(api_key: str, model: str = "text-embedding-3-small") -> EmbeddingFn:
    """Wraps OpenAI's embeddings endpoint as an EmbeddingFn. Uses the SYNC OpenAI client
    deliberately, not AsyncOpenAI: CapabilityRegistry/build_registry's embed_fn contract is a
    plain sync callable (capabilities are registered at construction time, with no async context
    available to await into) -- calling asyncio.run() from here would raise, since this function
    runs from inside code that's already executing on a running event loop (a FastAPI request
    handler). The trade-off is a blocking network call inside that handler; acceptable at this
    project's scale (a handful of capabilities, each embedded once thanks to
    cached_embedding_fn() below), not something a production system would accept unmodified."""
    client = OpenAI(api_key=api_key)

    def _embed(text: str) -> list[float]:
        response = client.embeddings.create(model=model, input=text)
        return list(response.data[0].embedding)

    return _embed


def cached_embedding_fn(
    embed_fn: EmbeddingFn, cache: dict[str, list[float]] | None = None
) -> EmbeddingFn:
    """Wraps any EmbeddingFn with a content-hash-keyed cache, so the same text is never embedded
    twice. `cache` defaults to a fresh dict, but a caller building a long-lived, shared cache
    (runtime.py does exactly this, module-level, so it survives across the many short-lived
    CapabilityRegistry instances built per request) should pass one in explicitly -- otherwise
    each wrapped function only benefits within its own lifetime, which for a registry rebuilt
    fresh on every request would provide no benefit across requests at all."""
    store = cache if cache is not None else {}

    def _cached(text: str) -> list[float]:
        key = hashlib.sha256(text.encode()).hexdigest()
        if key not in store:
            store[key] = embed_fn(text)
        return store[key]

    return _cached
