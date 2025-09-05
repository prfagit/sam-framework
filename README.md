# SAM Framework

```
⠀⠀⠀⢘⠀⡂⢠⠆⠀⡰⠀⡀⢀⣠⣶⣦⣶⣶⣶⣶⣾⣿⣿⡿⢀⠈⢐⠈⠀⠀
⠀⠀⠀⡁⢄⡀⣞⡇⢰⠃⣼⣇⠀⣿⣿⣿⣿⣿⣿⣿⣿⣿⠛⣰⣻⡀⢸⠀⠀⠀
⠀⠀⠀⣠⠁⣛⣽⣇⠘⢸⣿⣿⣷⣾⣿⣿⣿⣿⣿⣿⠟⢡⣾⣿⢿⡇⠀⡃⠀⠀
⠀⠀⢀⠐⠀⢳⣿⡯⡞⣾⣿⣿⣿⣿⣿⣿⢿⣿⠟⢁⣴⣿⣿⣿⡜⢷⠀⢘⠄⠀
⠀⠀⠀⡊⢸⡆⠙⠛⡵⣿⣿⣿⣿⣿⡿⠤⠛⣠⣴⣿⣿⠿⣟⣟⠟⢿⡆⢳⠀⠀
⠀⠀⠘⡁⢸⡾⠁⠀⠀⠀⠀⠉⠉⠉⠈⣠⡌⢁⠄⡛⠡⠉⠍⠙⢳⢾⠁⢸⠀⠀
⠀⠀⠀⠂⢨⠌⠀⠀⠀⠀⠀⠀⠀⠀⢀⣤⣷⡎⠙⢬⣳⣪⡯⢜⣷⢸⠂⡈⠄⠀
⠀⠀⠀⠆⣰⢣⠀⠀⠀⠀⠀⠀⠀⣴⣿⣾⣷⢿⢻⣅⣌⡯⢛⣿⣿⡞⠠⡁⠂⠀
⠀⠀⠀⠄⢲⢉⡀⠀⠀⢀⡠⠤⠼⣇⣳⣿⣿⣟⡜⣿⣿⣿⣿⣿⣿⡇⠸⠡⠀⠀
⠀⠀⡀⠁⠹⠃⢀⡀⣿⡹⠗⢀⠛⠥⣺⣿⣿⡝⢹⣸⣿⣿⣿⣿⡏⠠⠰⠈⠐⠀
⠠⠈⠀⠄⣀⠀⠀⠸⠻⠦⠀⠀⠀⠀⠀⠉⠐⠀⠘⠻⢹⣿⡿⠃⠀⡀⠕⣈⠡⡄
⠀⠀⣴⡀⣬⠁⠀⠀⡁⠂⠀⣀⣀⠔⠌⠤⣀⡀⠀⠀⡈⢸⠪⠀⠀⡌⠤⠈⡀⣠
⠀⠀⣿⣿⣾⡇⠀⠀⠀⣴⢫⣾⠃⠠⢰⣶⣴⠶⣿⣦⠀⠀⠀⢄⣂⠀⠀⠰⠀⠙
⠀⠀⠉⠛⠛⠀⢀⣴⣿⢗⡟⠡⣄⣀⡀⠀⢀⣤⠞⡅⠀⠁⠀⡾⠀⠀⠠⡗⠀⢀
⠀⠀⠀⠀⠀⣴⡿⢋⠔⠃⠀⠀⠍⠙⠉⠈⠑⠁⠂⠀⠀⠀⡡⡁⣠⡼⣸⠅⠀⠘
⠀⠀⠀⣼⠛⢡⠔⠁⠐⣆⠀⠀⠀⠀⠀⠀⠀⠀⠁⢀⡔⡞⢛⣿⡿⠃⠏⠀⠀⢠
⠀⠀⠀⠈⠗⠀⠀⠀⠀⠘⣷⣀⢀⣀⣀⠀⡀⢀⣌⡧⠂⠀⡞⠛⡟⠀⠀⠀⡠⠜
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⠓⠈⠙⠙⠋⠉⠁⠀⠀⠀⠀⠀⠀⠀⡂⠠⠤⢶
```

**Solana Agent Middleware** - AI-powered framework for Solana blockchain operations.

Created by [@prfa](https://twitter.com/prfa) • [@prfagit](https://github.com/prfagit) • [prfa.me](https://prfa.me)

## What is SAM?

SAM is an AI agent framework for Solana blockchain operations. It provides 15 production-ready tools for:

- **Automated Trading**: Execute trades on Pump.fun and Jupiter
- **Portfolio Management**: Track balances and transaction history
- **Market Data**: Real-time data from DexScreener
- **Web Search**: Query information using Brave Search API
- **Risk Management**: Transaction validation and safety limits

## Key Features

- **15 Production-Ready Tools** for Solana ecosystem operations
- **Secure Key Management** with Fernet encryption and OS keyring
- **Async Architecture** optimized for high-performance trading
- **Persistent Memory** with conversation context and trade history
- **Rate Limiting & Safety** configurable protection against abuse
- **Clean CLI Interface** with comprehensive command suite
- **Real Blockchain Integration** - live operations only

## Quick Start

### Installation

```bash
git clone https://github.com/prfagit/sam-framework
cd sam-framework
uv sync
```

### Configuration

Create `.env` file with required variables:

```bash
# Required
OPENAI_API_KEY=your_openai_api_key
SAM_FERNET_KEY=your_generated_key

# Optional
BRAVE_API_KEY=your_brave_api_key  # For web search functionality
```

### First Run

```bash
# Interactive setup (recommended)
uv run sam onboard

# Or manual start
uv run sam
```

On first run, configure:
1. **OpenAI API Key** from [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. **Solana Private Key** for wallet operations

### Start Trading

```bash
# Start interactive agent
uv run sam

# Custom session
uv run sam --session trading_session
```

## Usage Examples

### Trading Operations
```
"Buy 0.01 SOL worth of BONK on pump.fun"
"Sell 50% of my DOGE position"
"Get swap quote for 1 SOL to USDC on Jupiter"
```

### Portfolio Management
```
"Check my wallet balance"
"Show my SOL balance"
"Get token data for EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
```

### Market Data
```
"Show trending pairs on DexScreener"
"Search for BONK trading pairs"
"Get detailed info for pair address"
```

### Web Search
```
"Search for Solana ecosystem news"
"Find information about new DEX launches"
```

## Available Tools

### Wallet & Balance (3 tools)
- `get_balance` - Complete wallet overview (SOL + all tokens)
- `transfer_sol` - Send SOL between addresses
- `get_token_data` - Token metadata and supply info

### Pump.fun Trading (4 tools)
- `pump_fun_buy` - Buy tokens on pump.fun
- `pump_fun_sell` - Sell tokens on pump.fun
- `get_token_trades` - View trading activity
- `get_pump_token_info` - Token information

### Jupiter Swaps (2 tools)
- `get_swap_quote` - Get swap quotes
- `jupiter_swap` - Execute token swaps

### Market Data (4 tools)
- `search_pairs` - Find trading pairs by query
- `get_token_pairs` - Get pairs for specific token
- `get_solana_pair` - Detailed pair information
- `get_trending_pairs` - Trending pairs by chain

### Web Search (2 tools)
- `search_web` - Search internet content
- `search_news` - Search news articles

## Architecture

```
sam/
├── cli.py             # Command-line interface
├── core/              # Agent orchestration and LLM integration
│   ├── agent.py       # Main SAMAgent class
│   ├── llm_provider.py # OpenAI API integration
│   ├── memory.py      # Conversation persistence
│   └── tools.py       # Tool registry and execution
├── config/            # Configuration and prompts
│   ├── prompts.py     # System prompts
│   └── settings.py    # Environment configuration
├── integrations/      # Blockchain and DeFi connectors
│   ├── solana/        # Native Solana operations
│   ├── pump_fun.py    # Pump.fun trading
│   ├── jupiter.py     # Jupiter aggregator
│   ├── dexscreener.py # Market data
│   └── search.py      # Web search (Brave API)
└── utils/             # Security and utilities
    ├── crypto.py      # Key encryption
    ├── secure_storage.py # OS keyring integration
    ├── validators.py  # Input validation
    └── rate_limiter.py # Request throttling
```

## Security & Safety

- **Encrypted Key Storage**: Private keys secured with Fernet encryption
- **OS Keyring Integration**: System-level credential storage
- **Transaction Validation**: Pre-execution safety checks and limits
- **Rate Limiting**: Built-in protection against API abuse
- **Slippage Protection**: Configurable slippage tolerance (1-50%)
- **Address Validation**: Solana address format verification

## CLI Commands

```bash
# Agent Operations
sam run [--session ID]        # Start interactive agent
sam onboard                   # Interactive setup wizard
sam health                    # System health diagnostics
sam maintenance              # Database cleanup and optimization

# Security & Configuration
sam key import               # Import private key securely
sam key generate             # Generate encryption key
sam setup                    # Check setup status

# Development & Testing
sam tools                    # List available tools
```

## Configuration Options

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | Required |
| `OPENAI_MODEL` | OpenAI model to use | gpt-5-nano |
| `SAM_FERNET_KEY` | Fernet encryption key | Required |
| `SAM_SOLANA_RPC_URL` | Solana RPC endpoint | https://api.mainnet-beta.solana.com |
| `SAM_DB_PATH` | Database file path | .sam/sam_memory.db |
| `BRAVE_API_KEY` | Brave Search API key | Optional |
| `RATE_LIMITING_ENABLED` | Enable rate limiting | false |
| `MAX_TRANSACTION_SOL` | Maximum transaction size | 1000.0 |
| `DEFAULT_SLIPPAGE` | Default slippage tolerance | 1 |
| `LOG_LEVEL` | Logging level | INFO |

## Examples

### Trading
```bash
"Buy 0.01 SOL worth of BONK on pump.fun"
"Sell 50% of my DOGE position"
"Get swap quote for 1 SOL to USDC"
```

### Balance & Portfolio
```bash
"Check my wallet balance"
"Show my SOL balance"
"Get token data for EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
```

### Market Data
```bash
"Show trending pairs on DexScreener"
"Search for BONK trading pairs"
"Get detailed info for pair address"
```

### Web Search
```bash
"Search for Solana ecosystem news"
"Find information about DEX launches"
```

## Development

### Testing
```bash
# Run test suite
uv run pytest tests/ -v

# Run specific tests
uv run pytest tests/test_tools.py
uv run pytest tests/test_integration.py
```

### Code Quality
```bash
# Format code
uv run ruff format
uv run ruff check --fix

# Type checking
uv run mypy sam/
```

## Contributing

### Development Setup

```bash
# Fork and clone
git clone https://github.com/your-username/sam-framework
cd sam-framework

# Install dependencies
uv sync

# Install pre-commit hooks
uv run pre-commit install

# Create feature branch
git checkout -b feature/your-feature-name
```

### Code Style

- **Python**: Follow PEP 8 with 100 character line length
- **Imports**: Group by standard library, third-party, local
- **Docstrings**: Use Google style for functions
- **Types**: Full type hints required
- **Naming**: snake_case for functions/variables, PascalCase for classes

### Commit Guidelines

```bash
# Format: type(scope): description
git commit -m "feat(trading): add pump.fun buy functionality"
git commit -m "fix(memory): resolve session cleanup bug"
git commit -m "docs(readme): update installation instructions"
git commit -m "test(tools): add integration tests for jupiter"
```

**Types:**
- `feat`: New features
- `fix`: Bug fixes
- `docs`: Documentation
- `style`: Code style changes
- `refactor`: Code refactoring
- `test`: Testing
- `chore`: Maintenance

### Testing Requirements

```bash
# Run all tests
uv run pytest tests/ -v

# Run with coverage
uv run pytest tests/ --cov=sam --cov-report=html

# Run specific test file
uv run pytest tests/test_tools.py -v

# Run tests in watch mode
uv run pytest-watch tests/
```

**Coverage Requirements:**
- Minimum 80% coverage
- All new features must have tests
- Integration tests for API changes

### Pull Request Process

1. **Fork** the repository
2. **Create** a feature branch from `master`
3. **Make** your changes with tests
4. **Run** the full test suite
5. **Update** documentation if needed
6. **Commit** with conventional format
7. **Push** to your fork
8. **Create** a Pull Request

**PR Template:**
```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Manual testing completed

## Checklist
- [ ] Code follows style guidelines
- [ ] Tests pass locally
- [ ] Documentation updated
- [ ] No breaking changes
```

### Adding New Tools

```python
# 1. Create tool implementation
async def handle_new_tool(args: Dict[str, Any]) -> Dict[str, Any]:
    # Implementation here
    pass

# 2. Add tool spec
ToolSpec(
    name="new_tool",
    description="What the tool does",
    input_schema={
        "name": "new_tool",
        "description": "Tool description",
        "parameters": {
            "type": "object",
            "properties": {
                "param": {"type": "string", "description": "Parameter description"}
            },
            "required": ["param"]
        }
    }
)

# 3. Register in appropriate tool file (e.g., integrations/solana/solana_tools.py)
# 4. Add to CLI tool display names in cli.py
# 5. Add tests in tests/test_tools.py or tests/test_integration.py
# 6. Update README.md Available Tools section
```

### Project Structure

```
sam-framework/
├── sam/                    # Main package
│   ├── cli.py             # Command-line interface
│   ├── core/              # Core functionality
│   ├── integrations/      # External service integrations
│   └── utils/             # Utilities and helpers
├── tests/                 # Test suite
├── docs/                  # Documentation (future)
├── pyproject.toml         # Project configuration
└── uv.lock               # Dependency lock file
```

### Release Process

1. **Version bump** in `pyproject.toml`
2. **Update** changelog
3. **Run** full test suite
4. **Create** release branch
5. **Merge** to main with release commit
6. **Create** GitHub release
7. **Publish** to PyPI

## Production Deployment

### Environment Variables
```bash
# Production settings
SAM_SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
RATE_LIMITING_ENABLED=true
LOG_LEVEL=WARNING
MAX_TRANSACTION_SOL=10.0
```

### System Management
```bash
# Health check
sam health

# Database maintenance
sam maintenance

# Check configuration
sam setup
```

## Requirements

- Python 3.11+
- OpenAI API key
- Solana private key
- Internet connection
- Optional: Brave API key for web search

## License

MIT License

## Support

- **Issues**: [GitHub Issues](https://github.com/prfagit/sam-framework/issues)
- **Discussions**: [GitHub Discussions](https://github.com/prfagit/sam-framework/discussions)
- **Twitter**: [@prfa](https://twitter.com/prfa)

---

SAM Framework - AI-powered Solana blockchain operations.

Created by [@prfa](https://twitter.com/prfa) • [@prfagit](https://github.com/prfagit) • [prfa.me](https://prfa.me)
