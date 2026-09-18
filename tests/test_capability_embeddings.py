"""Unit coverage for the optional real-embedding upgrade (capabilities/embeddings.py). No live
OpenAI call: openai_embedding_fn is tested against a fake client shaped like the real SDK's sync
response, and cached_embedding_fn is tested against a plain counting fake -- neither needs a real
API key or network access."""

from capability_platform.capabilities.embeddings import cached_embedding_fn, openai_embedding_fn


class _FakeEmbeddingData:
    def __init__(self, embedding: list[float]) -> None:
        self.embedding = embedding


class _FakeEmbeddingResponse:
    def __init__(self, embedding: list[float]) -> None:
        self.data = [_FakeEmbeddingData(embedding)]


class _FakeEmbeddingsResource:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, model: str, input: str) -> _FakeEmbeddingResponse:
        self.calls.append({"model": model, "input": input})
        return _FakeEmbeddingResponse([float(len(input)), 0.5, -0.5])


class _FakeOpenAIClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.embeddings = _FakeEmbeddingsResource()


def test_openai_embedding_fn_calls_the_client_and_returns_its_vector(monkeypatch):
    fake_client = _FakeOpenAIClient(api_key="fake-key")
    monkeypatch.setattr(
        "capability_platform.capabilities.embeddings.OpenAI", lambda api_key: fake_client
    )

    embed = openai_embedding_fn("fake-key", model="text-embedding-3-small")
    vector = embed("savings balance")

    assert vector == [15.0, 0.5, -0.5]
    assert fake_client.embeddings.calls == [
        {"model": "text-embedding-3-small", "input": "savings balance"}
    ]


def test_openai_embedding_fn_uses_the_configured_model(monkeypatch):
    fake_client = _FakeOpenAIClient(api_key="fake-key")
    monkeypatch.setattr(
        "capability_platform.capabilities.embeddings.OpenAI", lambda api_key: fake_client
    )

    embed = openai_embedding_fn("fake-key", model="a-different-model")
    embed("some text")

    assert fake_client.embeddings.calls[0]["model"] == "a-different-model"


def test_cached_embedding_fn_only_calls_the_underlying_provider_once_per_distinct_text():
    calls: list[str] = []

    def _underlying(text: str) -> list[float]:
        calls.append(text)
        return [float(len(text))]

    cached = cached_embedding_fn(_underlying)

    assert cached("savings balance") == [15.0]
    assert cached("savings balance") == [15.0]
    assert cached("open account preferences") == [24.0]

    assert calls == ["savings balance", "open account preferences"]


def test_cached_embedding_fn_shares_an_external_cache_across_wrapped_instances():
    """This is the shape runtime.py actually relies on: one module-level cache dict threaded
    through every call to capability_embed_fn(), so a cache built for one request benefits the
    next one too -- a cache built fresh inside each wrapper would not."""
    calls: list[str] = []

    def _underlying(text: str) -> list[float]:
        calls.append(text)
        return [1.0]

    shared_cache: dict[str, list[float]] = {}
    first = cached_embedding_fn(_underlying, cache=shared_cache)
    second = cached_embedding_fn(_underlying, cache=shared_cache)

    first("savings balance")
    second("savings balance")

    assert calls == ["savings balance"]


def test_cached_embedding_fn_without_a_shared_cache_does_not_benefit_across_instances():
    """The failure mode this guards against: constructing a fresh cache inside a per-request
    factory would silently provide zero caching benefit across requests."""
    calls: list[str] = []

    def _underlying(text: str) -> list[float]:
        calls.append(text)
        return [1.0]

    cached_embedding_fn(_underlying)("savings balance")
    cached_embedding_fn(_underlying)("savings balance")

    assert calls == ["savings balance", "savings balance"]
