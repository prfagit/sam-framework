# SAM Framework - Solana Agent Middleware

An advanced AI agent framework specialized for Solana blockchain operations and memecoin trading. Built with modern Python async patterns and production-ready architecture.

## Features

- **Async-first architecture** with uvloop for maximum performance
- **Secure private key storage** with Fernet encryption
- **Persistent memory** with session context and user preferences
- **Modular tool system** supporting Solana, Pump.fun, and DexScreener
- **OpenAI-compatible LLM** provider with custom endpoint support
- **Comprehensive testing** with pytest and async support
- **Type-safe** with pydantic models and mypy validation

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd sam_framework

# Install dependencies with UV
uv sync

# Copy environment template
cp .env.example .env
```

### 2. Configuration

Edit `.env` with your settings:

```bash
# Required: OpenAI API key
OPENAI_API_KEY=your_openai_api_key

# Required: Generate encryption key for private key storage
SAM_FERNET_KEY=your_fernet_key

# Optional: Custom LLM endpoint
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini

# Solana configuration
SAM_SOLANA_RPC_URL=https://api.devnet.solana.com
SAM_DB_PATH=.sam/sam_memory.db
```

### 3. Generate Encryption Key

```bash
# Generate a new Fernet key for secure storage
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 4. Import Private Key (Secure)

```bash
# Securely import your Solana private key
uv run sam key import
```

### 5. Run the Agent

```bash
# Start interactive session
uv run sam run

# Or with custom session ID
uv run sam run --session trading_bot
```

## Available Commands

### Agent Operations
```bash
sam run [--session SESSION_ID]     # Start interactive agent
sam health                         # Check system health
sam maintenance                    # Clean up old data
```

### Key Management
```bash
sam key import                     # Import private key securely
sam generate-key                   # Generate new encryption key
```

## Supported Tools

### Solana Blockchain
- `get_balance` - Check SOL balance for addresses
- `transfer_sol` - Send SOL between addresses
- `get_token_data` - Fetch token metadata

### Pump.fun Integration
- `pump_fun_buy` - Buy meme coins
- `pump_fun_sell` - Sell token holdings
- `get_token_trades` - View trading activity

### Jupiter Aggregator
- `get_swap_quote` - Get best swap prices
- `jupiter_swap` - Execute token swaps
- `get_jupiter_tokens` - List available tokens

### DexScreener Analytics
- `search_pairs` - Find trading pairs
- `get_token_pairs` - Get pairs for specific tokens
- `get_solana_pair` - Detailed pair information
- `get_trending_pairs` - Top performing pairs

### Brave Search
- `search_web` - Search the internet for current information
- `search_news` - Search for recent news and current events

## Development

### Testing

```bash
# Run all tests
uv run pytest tests/ -v

# Run specific test categories
uv run pytest tests/test_memory.py -v
uv run pytest tests/test_integration.py -v
```

### Code Quality

```bash
# Format code
uv run ruff format sam/

# Lint code
uv run ruff check sam/ --fix

# Type checking
uv run mypy sam/
```

## Architecture

### Core Components

- **Agent** (`sam/core/agent.py`) - Main orchestration loop with LLM interaction
- **LLM Provider** (`sam/core/llm_provider.py`) - OpenAI-compatible API client with retry logic
- **Tools** (`sam/core/tools.py`) - Modular tool system with validation
- **Memory** (`sam/core/memory.py`) - Persistent async SQLite storage

### Security Features

- **Keyring Storage** - OS-level secure private key storage
- **Fernet Encryption** - AES 128 encryption for sensitive data
- **Rate Limiting** - Redis-based token bucket rate limiting
- **Input Validation** - Pydantic schema validation for all inputs

### Monitoring & Recovery

- **Error Tracking** - Comprehensive error logging with severity levels
- **Health Checks** - System component health monitoring
- **Circuit Breakers** - Automatic failure recovery
- **Maintenance Tools** - Automated cleanup and optimization

## Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `OPENAI_API_KEY` | OpenAI API key | None | Yes |
| `SAM_FERNET_KEY` | Encryption key for secure storage | None | Yes |
| `SAM_SOLANA_RPC_URL` | Solana RPC endpoint | devnet | No |
| `OPENAI_BASE_URL` | Custom LLM endpoint | OpenAI API | No |
| `OPENAI_MODEL` | LLM model name | gpt-4o-mini | No |
| `SAM_DB_PATH` | Database file path | .sam/sam_memory.db | No |
| `REDIS_URL` | Redis connection for rate limiting | localhost:6379 | No |
| `RATE_LIMITING_ENABLED` | Enable/disable rate limiting | true | No |
| `BRAVE_API_KEY` | Brave Search API key for web search | None | No |
` | Logging verbosity | INFO | No |

## Safety Features

- **Transaction Limits** - Configurable SOL amount limits
- **Slippage Protection** - 1-50% slippage tolerance on trades
- **Address Validation** - Solana address format verification
- **Rate Limiting** - Per-tool rate limits to prevent abuse
- **Devnet Default** - Safe testing environment by default

## Troubleshooting

### Common Issues

1. **Private Key Errors**
   ```bash
   sam generate-key  # Generate new encryption key
   sam key import    # Re-import private key
   ```

2. **Database Issues**
   ```bash
   sam maintenance   # Clean up corrupted data
   ```

3. **Rate Limiting**
   ```bash
   # Check Redis connection or disable rate limiting
   export RATE_LIMITING_ENABLED=false
   ```

### Health Diagnostics

```bash
# Comprehensive system check
sam health

# View recent errors
tail -f ~/.sam/logs/sam.log
```

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## Support

For issues, questions, or contributions, please use the GitHub repository.