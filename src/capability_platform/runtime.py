from capability_platform.agent.discovery import ClaudeDiscoveryAgent
from capability_platform.capabilities.store import ArtifactStore
from capability_platform.computer_use.replay import ReplayEngine
from capability_platform.policy.engine import PolicyEngine, default_policy
from capability_platform.settings import settings


def store() -> ArtifactStore:
    return ArtifactStore(settings.artifact_dir)


def replay_engine() -> ReplayEngine:
    return ReplayEngine(PolicyEngine(default_policy()), settings.evidence_dir, settings.headless)


def discovery_agent() -> ClaudeDiscoveryAgent:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for a genuine discovery run")
    return ClaudeDiscoveryAgent(
        settings.anthropic_api_key,
        settings.claude_model,
        PolicyEngine(default_policy()),
        settings.evidence_dir,
        settings.max_discovery_steps,
        settings.headless,
    )
