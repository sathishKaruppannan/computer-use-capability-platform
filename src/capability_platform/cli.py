import argparse
import asyncio
import json

from capability_platform.runtime import discovery_agent, replay_engine, store
from capability_platform.settings import settings
from capability_platform.synthesis.result import GroundedSynthesizer


def parse_inputs(values: list[str]) -> dict[str, str]:
    return dict(value.split("=", 1) for value in values)


async def run(args) -> None:
    if args.command == "discover":
        artifact = await discovery_agent().discover(args.goal, args.target, args.member_id)
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
    commands.add_parser("list")
    approve = commands.add_parser("approve")
    approve.add_argument("capability")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
