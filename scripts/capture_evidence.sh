#!/usr/bin/env bash
set -euo pipefail

uv run capability-platform discover \
  --goal "Find member 10001 and return the current savings balance" \
  --member-id 10001

uv run capability-platform replay lookup-member-savings-balance.v1 --input memberId=10002
uv run capability-platform replay lookup-member-savings-balance.v1 --input memberId=99999

