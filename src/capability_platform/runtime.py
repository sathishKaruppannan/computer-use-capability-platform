from collections.abc import Callable

from capability_platform.access.credentials import JSONCredentialStore
from capability_platform.access.system_registry import JSONSystemRegistry
from capability_platform.access.tenant_credentials import JSONTenantCredentialStore
from capability_platform.access.tracking import JSONInquiryTracker
from capability_platform.agent.discovery import ClaudeDiscoveryAgent
from capability_platform.agent.intent_analyzer import IntentAnalyzer
from capability_platform.agent.models import CapabilityResolution
from capability_platform.agent.orchestrator import AgentOrchestrator
from capability_platform.agent.plan_validator import PlanValidator
from capability_platform.agent.planner import Planner
from capability_platform.capabilities.executor import CapabilityExecutor
from capability_platform.capabilities.registry import CapabilityRegistry, build_registry
from capability_platform.capabilities.resolver import CapabilityResolver
from capability_platform.capabilities.store import ArtifactStore
from capability_platform.computer_use.replay import ReplayEngine
from capability_platform.llm.anthropic_provider import AnthropicProvider
from capability_platform.llm.openai_provider import OpenAIProvider
from capability_platform.llm.provider import LLMProvider
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


def tenant_credential_store() -> JSONTenantCredentialStore:
    return JSONTenantCredentialStore(settings.tenant_credential_dir)


def system_registry() -> JSONSystemRegistry:
    return JSONSystemRegistry(settings.system_registry_path)


def inquiry_tracker() -> JSONInquiryTracker:
    return JSONInquiryTracker(settings.tracking_dir)


def intent_llm_provider() -> LLMProvider:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for intent analysis")
    return AnthropicProvider(settings.anthropic_api_key, settings.claude_model)


def intent_llm_fallback_provider() -> LLMProvider | None:
    if not settings.openai_api_key:
        return None
    return OpenAIProvider(settings.openai_api_key, settings.openai_model)


def capability_registry() -> CapabilityRegistry:
    return build_registry(store())


def capability_resolver() -> CapabilityResolver:
    return CapabilityResolver(capability_registry(), store(), PolicyEngine(default_policy()))


def capability_executor() -> CapabilityExecutor:
    return CapabilityExecutor(store(), replay_engine, tenant_credential_store())


def agent_orchestrator(
    environment: str = "production",
    resolution_authorizer: Callable[[CapabilityResolution], None] | None = None,
) -> AgentOrchestrator:
    return AgentOrchestrator(
        intent_analyzer=IntentAnalyzer(intent_llm_provider(), intent_llm_fallback_provider()),
        planner=Planner(),
        plan_validator=PlanValidator(PolicyEngine(default_policy())),
        resolver=capability_resolver(),
        executor=capability_executor(),
        artifact_store=store(),
        discovery_agent_factory=lambda: discovery_agent(environment=environment),
        evidence_root=settings.evidence_dir,
        resolution_authorizer=resolution_authorizer,
    )
