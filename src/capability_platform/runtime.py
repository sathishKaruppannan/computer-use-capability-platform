from capability_platform.access.credentials import JSONCredentialStore
from capability_platform.access.system_registry import JSONSystemRegistry
from capability_platform.access.tracking import JSONInquiryTracker
from capability_platform.agent.discovery import ClaudeDiscoveryAgent
from capability_platform.capabilities.store import ArtifactStore
from capability_platform.computer_use.replay import ReplayEngine
from capability_platform.policy.engine import PolicyEngine, default_policy
from capability_platform.settings import settings


def store() -> ArtifactStore:
    return ArtifactStore(settings.artifact_dir)


def replay_engine() -> ReplayEngine:
    return ReplayEngine(PolicyEngine(default_policy()), settings.evidence_dir, settings.headless)


def discovery_agent(environment: str = "production") -> ClaudeDiscoveryAgent:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for a genuine discovery run")
    return ClaudeDiscoveryAgent(
        settings.anthropic_api_key,
        settings.claude_model,
        PolicyEngine(default_policy()),
        settings.evidence_dir,
        settings.max_discovery_steps,
        settings.headless,
        openai_api_key=settings.openai_api_key,
        openai_model=settings.openai_model,
        prompt_variant=environment,
    )


def credential_store() -> JSONCredentialStore:
    return JSONCredentialStore(settings.credential_dir)


def system_registry() -> JSONSystemRegistry:
    return JSONSystemRegistry(settings.system_registry_path)


def inquiry_tracker() -> JSONInquiryTracker:
    return JSONInquiryTracker(settings.tracking_dir)
