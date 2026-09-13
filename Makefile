.PHONY: install test test-e2e lint demo platform discover replay mcp

install:
	uv sync --extra dev
	uv run playwright install chromium

test:
	uv run pytest -q -m "not e2e"

test-e2e:
	uv run pytest -q -m e2e

lint:
	uv run ruff check .

demo:
	uv run uvicorn demo_app.app:app --port 8001

platform:
	uv run uvicorn capability_platform.api.app:app --port 8000

discover:
	uv run capability-platform discover --goal "Find member 10001 and return savings balance"

replay:
	uv run capability-platform replay lookup-member-savings-balance.v1 --input memberId=10002

mcp:
	uv run python -m capability_platform.mcp.server

