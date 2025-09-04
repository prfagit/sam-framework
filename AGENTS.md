# Repository Guidelines

## Project Structure & Module Organization
- Source: `sam_framework/sam/` (core agent, tools, integrations, config, utils)
- CLI entrypoint: `sam_framework/sam/cli.py` (installed as `sam` via `pyproject.toml`)
- Tests: `sam_framework/tests/` (pytest, async tests)
- Config: `.env` (see `sam_framework/.env.example`), settings in `sam_framework/sam/config/settings.py`

## Build, Test, and Development Commands
- Install deps: `uv sync`
- Run agent: `uv run sam run --session demo`
- Generate key: `uv run sam generate-key`
- Import wallet key: `uv run sam key import`
- Tests (all): `uv run pytest`
- Tests (file): `uv run pytest sam_framework/tests/test_memory.py`
- Lint: `uv run ruff check`
- Format: `uv run black .`
- Type check: `uv run mypy .`

## Coding Style & Naming Conventions
- Python 3.11+, 4‑space indentation, max line length 100 (see `tool.ruff`).
- Use type hints; keep public APIs typed.
- Naming: modules/packages `lower_snake_case`, classes `CapWords`, functions/vars `lower_snake_case`.
- Keep tools modular under `sam_framework/sam/core` and `sam_framework/sam/integrations/*`.
- Run `ruff`, `black`, and `mypy` before submitting.

## Testing Guidelines
- Framework: `pytest` with `pytest-asyncio` (use `@pytest.mark.asyncio` for async tests).
- Location: `sam_framework/tests/`; name tests `test_*.py` and functions `test_*`.
- Coverage (optional): `uv run pytest --cov=sam --cov-report=term-missing`.
- Prefer fast, isolated unit tests; mock external APIs and Solana RPC.

## Commit & Pull Request Guidelines
- History is minimal; follow Conventional Commits (e.g., `feat: add jupiter swap tool`).
- Commits: small, focused; include tests/updates when affecting behavior.
- PRs must include: description, rationale, screenshots or CLI logs if relevant, and linked issues.
- Ensure: `uv run pytest`, `ruff`, `black`, `mypy` all pass.

## Security & Configuration Tips
- Never commit secrets. Use `.env` based on `sam_framework/.env.example`.
- Required: `OPENAI_API_KEY`, `SAM_FERNET_KEY`. Generate with `uv run sam generate-key`.
- Prefer secure key storage via `uv run sam key import` (uses system keyring); env fallback is legacy.
- Default Solana RPC is devnet; validate amounts and slippage limits before mainnet usage.

