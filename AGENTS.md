# Repository Guidelines

## Project Structure & Module Organization
- `sam/`: core package
  - `cli.py`: CLI entrypoint (`uv run sam`)
  - `core/`: agent orchestration, LLM, memory, tools registry
  - `integrations/`: Solana, Pump.fun, Jupiter, DexScreener, Polymarket, web search
  - `utils/`: crypto, secure storage, validators, rate limiting
  - `config/`: prompts and settings
- `tests/`: unit/integration tests mirroring `sam/`
- `.sam/`: local DB and runtime artifacts
- `.env`: local configuration (never commit)

## Build, Test, and Development Commands
- Install deps: `uv sync`
- Run agent (interactive): `uv run sam`
- Onboarding flow: `uv run sam onboard`
- Tests: `uv run pytest tests/ -v`
- Lint/format: `uv run ruff format && uv run ruff check --fix`
- Type check: `uv run mypy sam/`
- Health/maintenance: `uv run sam health` and `uv run sam maintenance`

## Coding Style & Naming Conventions
- Python ≥ 3.11, PEP 8, line length 100 (ruff configured).
- Typing required for public APIs; prefer explicit `TypedDict`/`pydantic` models for tool I/O.
- Naming: `snake_case` (functions/vars), `PascalCase` (classes), `SCREAMING_SNAKE_CASE` (consts).
- Imports grouped: stdlib → third‑party → local. Keep CLI UX consistent; extend `sam/cli.py` for new commands.

## Testing Guidelines
- Frameworks: `pytest` + `pytest-asyncio`.
- Place tests under `tests/` mirroring package paths (e.g., `tests/test_tools.py`).
- Write async tests for async APIs; use fixtures for RPC/IO boundaries.
- Run locally: `uv run pytest -q`; coverage: `uv run pytest --cov=sam --cov-report=term`.

## Commit & Pull Request Guidelines
- Conventional commits: `type(scope): concise description` (types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`).
- Example: `feat(trading): add pump.fun buy`.
- PRs must include: clear description, linked issues, and rationale; passing CI; `ruff` + `mypy` clean; tests updated; screenshots/CLI output when UX changes apply.

## Security & Configuration
- Never commit secrets. Use OS keyring and `.env` locally.
- Required env: `SAM_FERNET_KEY`, LLM provider keys, `SAM_SOLANA_RPC_URL`.
- Storage paths: DB at `.sam/sam_memory.db`. Validate addresses and set slippage carefully (`DEFAULT_SLIPPAGE`).

## Adding a Tool (Quick Path)
1) Implement handler in `sam/integrations/...`  2) add spec to tools registry  3) expose in `cli.py`  4) add tests  5) update docs.
