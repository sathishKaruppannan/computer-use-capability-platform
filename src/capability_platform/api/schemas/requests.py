"""Request DTOs for the authenticated /v1 REST surface (api/v1_routes.py). Kept separate from
the route handlers themselves so the request/response contract is one clean, browsable place --
not mixed in with business logic."""

from typing import Any, Literal

from pydantic import BaseModel

from capability_platform.models import ServiceType


class DiscoverV1Request(BaseModel):
    service_type: ServiceType
    system_identifier: str
    client_inquiry_id: str
    goal: str
    environment: Literal["production", "demo"] = "production"
    example_member_id: str = "10001"
    is_auth_required: bool = False
    # "credentials" -> example_username + example_password; "api_key" -> example_api_key.
    # Both end up as extra_known_values dict entries for discover() -- same underlying
    # mechanism either way, just a different set of named credentials.
    auth_type: Literal["credentials", "api_key"] = "credentials"
    example_username: str | None = None
    example_password: str | None = None
    example_api_key: str | None = None
    force_rediscover: bool = False
    # Discovery-time bypass of the system registry: when set, discovery targets this URL
    # directly instead of resolving system_identifier through config/system_registry.json.
    # system_identifier is still required (it remains the resolver's reuse/artifact-id key) but
    # no longer needs to be pre-registered when target_url is supplied.
    target_url: str | None = None
    # Client-generated correlation id so a UI can poll GET /runs/{id}/events for live progress
    # while this (long-running, ~30-90s) call is still in flight -- see discover() in
    # agent/discovery.py, which uses this instead of generating its own run_id when provided.
    discovery_run_id: str | None = None


class ExecuteV1Request(BaseModel):
    client_inquiry_id: str
    inputs: dict[str, Any]
