# SAM Framework

Solana Agent Middleware.

SAM is a Python framework for building AI agents that can hold context, call tools, and operate around Solana workflows without turning every demo into a pile of one-off scripts.

It is built for the part of crypto agents that actually gets annoying: provider switching, wallet handling, memory, event streams, tool policy, retries, and enough guardrails that an agent can touch real infrastructure without pretending the risk is gone.

## What it is

SAM gives you a working agent runtime with:

- Multi-provider LLM support across OpenAI, Anthropic, xAI, and local-compatible endpoints
- Tool calling with structured errors, retries, loop control, and middleware
- Persistent sessions backed by SQLite
- Encrypted wallet and key storage using Fernet and OS keyring
- Solana and DeFi integrations for market data, trading, balances, and validation
- A plugin system for adding tools without rewriting the core loop
- CLI, API, and Streamlit surfaces for different ways to run agents

It is not a toy chatbot with a wallet glued on. It is the boring middle layer you need before the interesting parts can run.

## Why it exists

Most agent demos die at the same place.

They can write a tweet, summarize a chart, maybe call one API. Then you ask them to keep memory, switch models, handle secrets, stream state to a frontend, validate a transaction, retry a flaky request, and not blow up after five tool calls.

SAM is the layer under that.

## Install

```bash
git clone https://github.com/prfagit/sam-framework
cd sam-framework
uv sync
```

Run the guided setup:

```bash
uv run sam onboard
```

Start an interactive agent:

```bash
uv run sam run
```

Or use a named session:

```bash
uv run sam run --session trading_session
```

## Run the API

SAM can expose agents over HTTP for frontend or service integrations.

```bash
uv run sam api --host 0.0.0.0 --port 8000
```

Useful environment variables:

```bash
SAM_API_AGENT_ROOT=.sam/users
SAM_API_CORS_ORIGINS=http://localhost:3000
SAM_API_TOKEN_SECRET=change-me
```

Create a user:

```bash
uv run sam api create-user alice --admin
```

Login and stream an agent response:

```bash
curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "hunter2"}'

curl -N -X POST http://localhost:8000/v1/agents/sam/stream \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Watch SOL/USDC"}'
```

## Configuration

The onboarding flow will write the local config for you. For manual setup, create a `.env` file:

```bash
LLM_PROVIDER=openai

OPENAI_API_KEY=sk-your-key
ANTHROPIC_API_KEY=sk-ant-your-key
XAI_API_KEY=xai-your-key

SAM_FERNET_KEY=your-generated-key
BRAVE_API_KEY=your-brave-search-key
```

Provider commands:

```bash
uv run sam provider list
uv run sam provider switch anthropic
uv run sam provider test
```

## Tool surface

SAM ships with production-oriented tools across:

- Solana wallets, balances, and transaction validation
- Jupiter, Pump.fun, DexScreener, and market data workflows
- Hyperliquid, Aster, Kalshi, and Polymarket research/trading flows
- Web search, URL fetching, and news intelligence
- Memory, session, and configuration management
- Plugin-loaded custom tools

Tool access is policy-driven. The point is not to make agents reckless. The point is to make useful actions explicit, inspectable, and easier to contain.

## Architecture

```text
sam/
  cli.py                 # CLI entrypoint
  agent.py               # Core agent loop
  tools/                 # Built-in tools and registry
  memory/                # Session and long-term context
  api/                   # HTTP API surface
  plugins/               # Plugin discovery and loading
  security/              # Key handling and validation
```

Core pieces:

- Agent runtime: model calls, tool calls, streaming, and recovery
- Event bus: async pub/sub for UI and service integration
- Memory: SQLite-backed sessions with context compaction
- Security layer: encrypted secrets and pre-action validation
- Plugin SDK: custom tools through entry point discovery

## Streamlit interface

```bash
uv run streamlit run examples/streamlit_app/app.py
```

Then open `http://localhost:8501`.

The Streamlit surface is useful for watching tool calls, live events, wallet state, settings, and session history without building a frontend first.

## Development

```bash
uv sync --group dev
uv run pytest
uv run ruff check .
uv run mypy sam
```

Run the CLI locally:

```bash
uv run sam --help
```

## Safety note

Agents that touch wallets, markets, and transactions need boring controls. SAM includes encrypted storage, validation, rate limiting, and policy hooks, but it does not make automated trading safe by magic.

Use small scopes. Inspect tool calls. Treat every key like it matters.

## Links

- Site: [prfa.me](https://prfa.me)
- Repository: [github.com/prfagit/sam-framework](https://github.com/prfagit/sam-framework)
- Issues: [github.com/prfagit/sam-framework/issues](https://github.com/prfagit/sam-framework/issues)

## License

MIT
