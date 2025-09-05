# SAM Framework

**Solana Agent Middleware** - An AI-powered framework for automated trading and DeFi operations on Solana blockchain.

Created by [@prfa](https://twitter.com/prfa) • [@prfagit](https://github.com/prfagit) • [prfa.me](https://prfa.me)

## What is SAM?

SAM is an intelligent agent framework that enables AI-driven trading and portfolio management on the Solana blockchain. It provides a comprehensive toolkit for:

- **Automated Trading**: Execute trades across Pump.fun, Jupiter aggregator, and DEXs
- **Portfolio Management**: Track balances, positions, and transaction history
- **Market Analysis**: Real-time data from DexScreener and blockchain sources
- **Risk Management**: Built-in safety limits, slippage protection, and validation
- **Secure Operations**: Encrypted key storage with system keyring integration

## Key Features

- **14 Production-Ready Tools** for Solana ecosystem operations
- **Secure Key Management** with Fernet encryption and OS keyring
- **Async Architecture** optimized for high-performance trading
- **Persistent Memory** with conversation context and trade history
- **Rate Limiting & Safety** built-in protection against abuse
- **Clean CLI Interface** with comprehensive command suite
- **Real Blockchain Integration** - no mock data, live operations

## Quick Start

### Installation & Setup

```bash
# 1. Clone and install
git clone https://github.com/prfagit/sam-framework
cd sam-framework
uv sync

# 2. Run SAM (automatic setup on first run)
uv run sam
```

**That's it!** 🎉

On first run, SAM will automatically guide you through a **2-step setup**:

1. **OpenAI API Key** - Get yours from [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. **Solana Private Key** - Your wallet's private key for trading

Everything else (encryption, configuration, security) is handled automatically.

### Start Trading

```bash
# Launch SAM agent
uv run sam

# Or run with custom session
sam run --session trading_session
```

## What You Can Build

### Auto Trading Bot
```python
# Agent automatically executes trades based on AI analysis
"Buy 0.1 SOL of trending meme coins on pump.fun"
"Sell 50% of my DOGE position if price drops 10%"
"Monitor BONK/USDC pair and alert on large volume spikes"
```

### Smart Portfolio Management
```python
# AI-driven portfolio rebalancing and position management
"Check my current SOL and token balances"
"Show my trading history for the past week"
"Rebalance portfolio: 40% SOL, 30% stablecoins, 30% altcoins"
```

### DeFi Operations
```python
# Automated DEX interactions and arbitrage
"Swap 1 SOL for USDC at best available price on Jupiter"
"Find the best rate for BONK to SOL conversion"
"Execute arbitrage between pump.fun and Raydium pairs"
```

### Market Analysis & Research
```python
# Real-time market data and analysis
"Show trending pairs on DexScreener"
"Get detailed information about BONK token"
"Search for new meme coins with high volume"
```

## Available Tools

### Trading & Transactions
- **Pump.fun**: Buy/sell meme coins with automated execution
- **Jupiter**: Best-price token swaps across DEX aggregators
- **Solana Native**: Direct SOL transfers and balance management

### Market Data & Analytics
- **DexScreener**: Real-time pair data, trending tokens, volume analysis
- **Token Information**: Metadata, trading history, holder analysis
- **Price Feeds**: Live price data from multiple sources

### Portfolio & Risk Management
- **Balance Tracking**: SOL and token holdings across wallets
- **Transaction History**: Complete trade history and performance
- **Safety Limits**: Configurable transaction limits and slippage protection

## Architecture

```
sam/
├── core/              # Agent orchestration and LLM integration
├── integrations/      # Blockchain and DeFi protocol connectors
│   ├── solana/        # Native Solana RPC operations
│   ├── pump_fun.py    # Pump.fun trading integration
│   ├── jupiter.py     # Jupiter aggregator swaps
│   └── dexscreener.py # Market data and analytics
├── config/            # System prompts and configuration
├── utils/             # Security, validation, and utilities
└── cli.py            # Command-line interface
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
sam run [--session ID]        # Start interactive trading agent
sam health                    # System health diagnostics
sam maintenance              # Database cleanup and optimization

# Security & Configuration
sam key import               # Secure private key import
sam generate-key             # Generate encryption keys
sam setup                    # Interactive configuration setup

# Development & Testing
sam tools                    # List available tools
sam test                     # Run test suite
```

## Configuration Options

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key for AI agent | Required |
| `SAM_FERNET_KEY` | Encryption key for secure storage | Required |
| `SAM_SOLANA_RPC_URL` | Solana RPC endpoint | mainnet-beta |
| `RATE_LIMITING_ENABLED` | Enable rate limiting | true |
| `MAX_TRANSACTION_SOL` | Maximum transaction size | 1000 SOL |
| `DEFAULT_SLIPPAGE` | Default slippage tolerance | 1% |

## Examples

### Basic Trading
```
User: "Buy 0.01 SOL worth of BONK on pump.fun"
Agent: Executes transaction with 5% slippage protection

User: "Check my balance"
Agent: Returns complete portfolio overview

User: "Show trending pairs on DexScreener"
Agent: Displays top performing trading pairs
```

### Advanced Automation
```
User: "Monitor DOGE price and sell if it drops 15%"
Agent: Sets up automated monitoring and execution

User: "Swap my entire SOL position to USDC"
Agent: Executes optimal swap via Jupiter aggregator

User: "Analyze my trading performance this month"
Agent: Provides detailed performance metrics
```

### Risk Management
```
User: "Set maximum transaction size to 0.1 SOL"
Agent: Updates safety limits

User: "Enable high slippage protection for volatile tokens"
Agent: Adjusts slippage to 10% for pump.fun trades
```

## Development

### Testing
```bash
# Run complete test suite
uv run pytest tests/ -v

# Run specific test categories
uv run pytest tests/test_integration.py
uv run pytest tests/test_security.py
```

### Code Quality
```bash
# Format and lint code
uv run ruff check --fix
uv run black .

# Type checking
uv run mypy sam/
```

## Production Deployment

### Environment Setup
```bash
# Production configuration
SAM_SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
RATE_LIMITING_ENABLED=true
LOG_LEVEL=WARNING
MAX_TRANSACTION_SOL=10.0
```

### Monitoring
```bash
# Health checks
sam health

# Maintenance
sam maintenance

# View logs
tail -f .sam/logs/sam.log
```

## Requirements

- Python 3.11+
- OpenAI API key
- Solana wallet with private key
- Internet connection for blockchain/RPC access

## License

MIT License

## Support

- **Documentation**: See `/docs` directory
- **Issues**: GitHub Issues
- **Discussions**: GitHub Discussions
- **Twitter**: [@prfa](https://twitter.com/prfa)

---

**Built for serious traders and DeFi enthusiasts who demand reliability, security, and automation.**

Created by [@prfa](https://twitter.com/prfa) • [@prfagit](https://github.com/prfagit) • [prfa.me](https://prfa.me)