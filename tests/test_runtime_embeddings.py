"""Coverage for runtime.py's opt-in real-embedding wiring (capability_embed_fn/
capability_registry) -- no live OpenAI call: the OpenAI client is monkeypatched at the same seam
test_capability_embeddings.py uses."""

from capability_platform import runtime as runtime_module
from capability_platform.settings import settings as global_settings


class _FakeEmbeddingData:
    def __init__(self, embedding: list[float]) -> None:
        self.embedding = embedding


class _FakeEmbeddingResponse:
    def __init__(self, embedding: list[float]) -> None:
        self.data = [_FakeEmbeddingData(embedding)]


class _FakeEmbeddingsResource:
    def __init__(self) -> None:
        self.call_count = 0

    def create(self, model: str, input: str) -> _FakeEmbeddingResponse:
        self.call_count += 1
        return _FakeEmbeddingResponse([1.0, 0.0])


class _FakeOpenAIClient:
    def __init__(self, api_key: str) -> None:
        self.embeddings = _FakeEmbeddingsResource()


def test_capability_embed_fn_is_none_without_an_openai_key(monkeypatch):
    monkeypatch.setattr(global_settings, "openai_api_key", None)
    assert runtime_module.capability_embed_fn() is None


def test_capability_embed_fn_is_wired_when_an_openai_key_is_configured(monkeypatch):
    monkeypatch.setattr(global_settings, "openai_api_key", "fake-key")
    monkeypatch.setattr(
        "capability_platform.capabilities.embeddings.OpenAI",
        lambda api_key: _FakeOpenAIClient(api_key),
    )
    monkeypatch.setattr(runtime_module, "_capability_embedding_cache", {})

    embed_fn = runtime_module.capability_embed_fn()
    assert embed_fn is not None
    assert embed_fn("some capability text") == [1.0, 0.0]


def test_capability_embed_fn_shares_the_module_level_cache_across_calls(monkeypatch):
    """The actual point of wiring the cache in at module level: two separate calls to
    capability_embed_fn() (as happens on two separate requests, since capability_registry() has
    no registry-level caching of its own) must still share embeddings for unchanged text."""
    monkeypatch.setattr(global_settings, "openai_api_key", "fake-key")
    fake_client = _FakeOpenAIClient("fake-key")
    monkeypatch.setattr(
        "capability_platform.capabilities.embeddings.OpenAI", lambda api_key: fake_client
    )
    monkeypatch.setattr(runtime_module, "_capability_embedding_cache", {})

    runtime_module.capability_embed_fn()("Lookup member savings balance")
    runtime_module.capability_embed_fn()("Lookup member savings balance")

    assert fake_client.embeddings.call_count == 1
