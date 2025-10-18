# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SAM (Solana Agent Middleware) is an AI-powered framework for Solana blockchain operations. This is a Python-based agent system that provides 15 production-ready tools for automated trading, portfolio management, market data retrieval, and web search functionality.

## Commands

### Development Commands
```bash
# Install dependencies and setup environment
uv sync

# Start the SAM agent interactively
uv run sam

# Interactive onboarding wizard
uv run sam onboard

# System health check
uv run sam health

# Database maintenance
uv run sam maintenance
```

### Testing
```bash
# Run full test suite
uv run pytest tests/ -v

# Run specific test files
uv run pytest tests/test_tools.py -v
uv run pytest tests/test_integration.py -v
uv run pytest tests/test_comprehensive.py -v

# Run with coverage
uv run pytest tests/ --cov=sam --cov-report=html

# Watch mode for development
uv run pytest-watch tests/

# Run single test method
uv run pytest tests/test_tools.py::test_specific_function -v
```

### Code Quality
```bash
# Format and lint code
uv run ruff format
uv run ruff check --fix

# Type checking
uv run mypy sam/

# All quality checks
uv run ruff format && uv run ruff check --fix && uv run mypy sam/ && uv run pytest tests/ -v
```

## Architecture Overview

### Core Components
- **SAMAgent** (`sam/core/agent.py`): Main orchestrator that manages LLM interactions, tool execution, and session state
- **LLMProvider** (`sam/core/llm_provider.py`): Multi-provider LLM support (OpenAI, Anthropic, xAI, local OpenAI-compatible)
- **ToolRegistry** (`sam/core/tools.py`): Tool management, validation, and execution framework
- **MemoryManager** (`sam/core/memory.py`): SQLite-based persistent conversation and trade history storage

### Integration Layers
- **Solana** (`sam/integrations/solana/`): Native Solana RPC operations (balance, transfers, token data)
- **Pump.fun** (`sam/integrations/pump_fun.py`): Trading operations on pump.fun platform
- **Uranus.ag** (`sam/integrations/uranus.py`): Perpetuals trading and market data for Uranus.ag
- **Jupiter** (`sam/integrations/jupiter.py`): Token swaps via Jupiter aggregator
- **DexScreener** (`sam/integrations/dexscreener.py`): Market data and trading pair information
- **Search** (`sam/integrations/search.py`): Web search via Brave API

### Security & Utilities
- **Crypto** (`sam/utils/crypto.py`): Fernet encryption for private key storage
- **SecureStorage** (`sam/utils/secure_storage.py`): OS keyring integration
- **Validators** (`sam/utils/validators.py`): Input validation for all operations
- **RateLimiter** (`sam/utils/rate_limiter.py`): API rate limiting and abuse protection

## Configuration

Environment variables are defined in `.env` (copy from `.env.example`):
- **LLM_PROVIDER**: `openai` (default), `anthropic`, `xai`, `openai_compat`, or `local`
- **SAM_FERNET_KEY**: Required encryption key for secure wallet storage
- **SAM_SOLANA_RPC_URL**: Solana RPC endpoint (mainnet-beta by default)
- **RATE_LIMITING_ENABLED**: Safety protection toggle
- **MAX_TRANSACTION_SOL**: Transaction limit safety check
- **BRAVE_API_KEY**: Optional for web search functionality

## Tool Development

### Adding New Tools
1. Create implementation in appropriate integration module
2. Define `ToolSpec` with JSON schema
3. Register in `sam/core/tools.py`
4. Add display name to `TOOL_DISPLAY_NAMES` in `sam/cli.py`
5. Write tests in `tests/test_tools.py`

### Tool Categories
- **Wallet & Balance** (3 tools): `get_balance`, `transfer_sol`, `get_token_data`
- **Pump.fun Trading** (4 tools): `pump_fun_buy`, `pump_fun_sell`, `get_token_trades`, `get_pump_token_info`
- **Uranus Perps** (5 tools): `uranus_open_position`, `uranus_close_position`, `uranus_get_positions`, `uranus_market_liquidity`, `uranus_get_price`
- **Jupiter Swaps** (2 tools): `get_swap_quote`, `jupiter_swap`
- **Market Data** (4 tools): `search_pairs`, `get_token_pairs`, `get_solana_pair`, `get_trending_pairs`
- **Web Search** (2 tools): `search_web`, `search_news`

## Important Patterns

### Error Handling
- All tools use `@handle_error_gracefully` decorator
- Comprehensive error messages via `sam/utils/error_messages.py`
- Async-safe error propagation throughout the stack

### Safety Features
- Transaction validation before execution
- Slippage protection (1-50% configurable)
- Address format validation
- Rate limiting on all API calls
- Encrypted private key storage

### Testing Strategy
- Unit tests for individual components
- Integration tests for tool interactions
- Comprehensive end-to-end scenarios
- Mock external APIs for reliable testing
- Minimum 80% coverage requirement

## CLI Architecture

The CLI (`sam/cli.py`) provides:
- Interactive agent sessions with custom session IDs
- Real-time tool execution feedback
- Health checks and system diagnostics
- Secure key management commands
- Onboarding wizard for first-time setup

## Database Schema

SQLite database (`.sam/sam_memory.db`) stores:
- Conversation history and context
- Trade execution records
- Session-based memory management
- Tool usage statistics

## Development Notes

- **Python 3.11+** required
- **Async-first** architecture using `asyncio` and `uvloop`
- **Type safety** enforced with mypy and Pydantic models
- **Conventional commits** format required
- **100-character line length** for Python code
- **Google-style docstrings** for all functions

### Debug Information
- Use `uv run sam debug` to show plugins and middleware configuration
- Session data stored in `.sam/sam_memory.db` SQLite database
- Logs are controlled by `LOG_LEVEL` environment variable (INFO, DEBUG, WARNING, ERROR)
- Event system debugging: Events are published to `EventBus` for tool execution and agent state changes
