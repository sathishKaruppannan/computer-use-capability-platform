import argparse
import asyncio
import json
import sys

from capability_platform.access.credentials import hash_password
from capability_platform.access.models import ClientCredential
from capability_platform.agent.intent_analyzer import (
    ClarificationRequiredError,
    SensitiveInfoRequestedError,
)
from capability_platform.agent.plan_validator import PlanValidationError
from capability_platform.models import ServiceType
from capability_platform.runtime import (
    agent_orchestrator,
    credential_store,
    discovery_agent,
    replay_engine,
    store,
)
from capability_platform.settings import settings
from capability_platform.synthesis.result import GroundedSynthesizer
from capability_platform.validation import GoalTooLongError


def parse_inputs(values: list[str]) -> dict[str, str]:
    return dict(value.split("=", 1) for value in values)


def build_goal_context(args) -> dict[str, str]:
    context = parse_inputs(args.context)
    if getattr(args, "target_url", None):
        context["target_url"] = args.target_url
    return context


async def run(args) -> None:
    if args.command == "discover":
        try:
            artifact = await discovery_agent().discover(args.goal, args.target, args.member_id)
        except GoalTooLongError as exc:
            print(json.dumps({"error": "goal_too_long", "message": str(exc)}, indent=2))
            sys.exit(1)
        path = store().save(artifact)
        print(json.dumps({"artifact": artifact.qualified_id, "path": str(path)}, indent=2))
    elif args.command == "replay":
        result = await replay_engine().execute(
            store().load(args.capability), parse_inputs(args.input)
        )
        print(result.model_dump_json(indent=2))
        print(GroundedSynthesizer.synthesize(result))
    elif args.command == "list":
        print(json.dumps([item.qualified_id for item in store().list()], indent=2))
    elif args.command == "approve":
        artifact = store().load(args.capability)
        artifact.lifecycle = "approved"
        path = store().save(artifact)
        print(
            json.dumps(
                {"artifact": artifact.qualified_id, "lifecycle": artifact.lifecycle, "path": str(path)},
                indent=2,
            )
        )
    elif args.command == "plan":
        try:
            intent, plan, resolutions = await agent_orchestrator().plan_only(
                args.goal, build_goal_context(args)
            )
        except GoalTooLongError as exc:
            print(json.dumps({"error": "goal_too_long", "message": str(exc)}, indent=2))
            sys.exit(1)
        except ClarificationRequiredError as exc:
            print(json.dumps({"error": "clarification_required", "question": exc.question}, indent=2))
            sys.exit(1)
        except SensitiveInfoRequestedError as exc:
            print(json.dumps({"error": "sensitive_info_requested", "message": str(exc)}, indent=2))
            sys.exit(1)
        except PlanValidationError as exc:
            print(json.dumps({"error": "plan_validation_failed", "message": str(exc)}, indent=2))
            sys.exit(1)
        print(
            json.dumps(
                {
                    "intent": intent.model_dump(mode="json"),
                    "plan": plan.model_dump(mode="json"),
                    "resolutions": [r.model_dump(mode="json") for r in resolutions],
                },
                indent=2,
            )
        )
    elif args.command == "run":
        try:
            result = await agent_orchestrator().execute_goal(args.goal, build_goal_context(args))
        except GoalTooLongError as exc:
            print(json.dumps({"error": "goal_too_long", "message": str(exc)}, indent=2))
            sys.exit(1)
        except ClarificationRequiredError as exc:
            print(json.dumps({"error": "clarification_required", "question": exc.question}, indent=2))
            sys.exit(1)
        except SensitiveInfoRequestedError as exc:
            print(json.dumps({"error": "sensitive_info_requested", "message": str(exc)}, indent=2))
            sys.exit(1)
        except PlanValidationError as exc:
            print(json.dumps({"error": "plan_validation_failed", "message": str(exc)}, indent=2))
            sys.exit(1)
        print(result.model_dump_json(indent=2))
        print(result.synthesized_text)
    elif args.command == "register-client":
        password_hash, password_salt = hash_password(args.password)
        credential = ClientCredential(
            client_id=args.client_id,
            password_hash=password_hash,
            password_salt=password_salt,
            authorized_service_types=[ServiceType(s) for s in args.service_type],
            is_admin=args.admin,
        )
        path = credential_store().save(credential)
        print(json.dumps({"client_id": credential.client_id, "path": str(path)}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Computer-use capability platform")
    commands = parser.add_subparsers(dest="command", required=True)
    discover = commands.add_parser("discover")
    discover.add_argument("--goal", required=True)
    discover.add_argument("--target", default=settings.target_url)
    discover.add_argument("--member-id", default="10001")
    replay = commands.add_parser("replay")
    replay.add_argument("capability")
    replay.add_argument("--input", action="append", default=[])
    plan_cmd = commands.add_parser("plan")
    plan_cmd.add_argument("--goal", required=True)
    plan_cmd.add_argument("--target-url", dest="target_url", default=None)
    plan_cmd.add_argument("--context", action="append", default=[])
    run_cmd = commands.add_parser("run")
    run_cmd.add_argument("--goal", required=True)
    run_cmd.add_argument("--target-url", dest="target_url", default=None)
    run_cmd.add_argument("--context", action="append", default=[])
    commands.add_parser("list")
    approve = commands.add_parser("approve")
    approve.add_argument("capability")
    register_client = commands.add_parser("register-client")
    register_client.add_argument("--client-id", required=True)
    register_client.add_argument("--password", required=True)
    register_client.add_argument("--service-type", action="append", required=True)
    register_client.add_argument("--admin", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
