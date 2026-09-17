"""Request DTOs for the authenticated /v1 REST surface (api/v1_routes.py). Kept separate from
the route handlers themselves so the request/response contract is one clean, browsable place --
not mixed in with business logic."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from capability_platform.models import ServiceType


class DiscoverV1Request(BaseModel):
    service_type: ServiceType = Field(
        description="Authorization scope AND cross-client reuse key for this capability domain. "
        "The caller's credential must be authorized for this service_type (see "
        "require_service_type) -- it is also the first half of the exact-key match used to find "
        "an existing approved capability before falling back to discovery."
    )
    system_identifier: str = Field(
        description="Second half of the reuse key, identifying which target system/tenant this "
        "goal runs against. Must resolve via config/system_registry.json unless target_url is "
        "supplied instead."
    )
    client_inquiry_id: str = Field(
        description="Caller-generated correlation id for this inquiry, echoed back nowhere in "
        "the response body but stored against the server-generated `inquiry_id` -- use it to "
        "reconcile this call with the caller's own request log."
    )
    goal: str = Field(
        description="Natural-language description of what the capability should accomplish. "
        "Only consulted when no approved capability already exists for "
        "(service_type, system_identifier); it drives a live Claude discovery run."
    )
    environment: Literal["production", "demo"] = Field(
        default="production",
        description="Selects which discovery agent config/policy profile to run under. Use "
        "'demo' only against the bundled demo_app, never a real target system.",
    )
    example_member_id: str = Field(
        default="10001",
        description="A concrete, known-valid identifier used as a discovery example so Claude "
        "has something real to look up while learning the flow. Not used during reuse.",
    )
    is_auth_required: bool = Field(
        default=False,
        description="Whether the target system's UI requires signing in before the goal can be "
        "reached. When true, one of the example_* auth fields below (matching auth_type) is "
        "required.",
    )
    # "credentials" -> example_username + example_password; "api_key" -> example_api_key.
    # Both end up as extra_known_values dict entries for discover() -- same underlying
    # mechanism either way, just a different set of named credentials.
    auth_type: Literal["credentials", "api_key"] = Field(
        default="credentials",
        description="Which auth mode the example_* fields below represent when "
        "is_auth_required=true. 'credentials' pairs example_username + example_password; "
        "'api_key' uses example_api_key alone.",
    )
    example_username: str | None = Field(
        default=None,
        description="Example login username for discovery. Required when is_auth_required=true "
        "and auth_type='credentials'. Never persisted into the resulting artifact.",
    )
    example_password: str | None = Field(
        default=None,
        description="Example login password for discovery. Required when is_auth_required=true "
        "and auth_type='credentials'. Never persisted into the resulting artifact or logged raw "
        "-- see Redactor.",
    )
    example_api_key: str | None = Field(
        default=None,
        description="Example API key for discovery. Required when is_auth_required=true and "
        "auth_type='api_key'. Never persisted into the resulting artifact or logged raw.",
    )
    force_rediscover: bool = Field(
        default=False,
        description="Skip the existing-approved-capability lookup and always run a fresh "
        "discovery, even if one already matches (service_type, system_identifier). Costs an LLM "
        "call; use for re-recording a stale or drifted flow.",
    )
    # Discovery-time bypass of the system registry: when set, discovery targets this URL
    # directly instead of resolving system_identifier through config/system_registry.json.
    # system_identifier is still required (it remains the resolver's reuse/artifact-id key) but
    # no longer needs to be pre-registered when target_url is supplied.
    target_url: str | None = Field(
        default=None,
        description="Bypasses config/system_registry.json and points discovery directly at this "
        "URL. system_identifier is still required as the reuse/artifact-id key, but no longer "
        "needs to be pre-registered.",
    )
    # Client-generated correlation id so a UI can poll GET /runs/{id}/events for live progress
    # while this (long-running, ~30-90s) call is still in flight -- see discover() in
    # agent/discovery.py, which uses this instead of generating its own run_id when provided.
    discovery_run_id: str | None = Field(
        default=None,
        description="Optional caller-generated run id. Discovery is long-running (~30-90s); "
        "supplying this up front lets a UI poll GET /runs/{id}/events for live progress on this "
        "same run while the call is still in flight.",
    )


class ExecuteV1Request(BaseModel):
    client_inquiry_id: str = Field(
        description="Caller-generated correlation id for this execution, recorded on the "
        "server-side inquiry audit trail alongside the resulting success/failed outcome."
    )
    inputs: dict[str, Any] = Field(
        description="Named argument values for the capability's declared ParameterSpec list "
        "(see GET /v1/capabilities/{id}/review). Validated against each spec's required/pattern "
        "constraints before anything touches the target system -- a failure here comes back as "
        "ExecutionResult.error with category='validation' and recoverable=false, since resending "
        "the same invalid inputs will fail identically."
    )
