#!/usr/bin/env bash
# SAM Framework Development Environment Setup
# Sets up pre-commit hooks and other development tools

set -euo pipefail

echo "🚀 Setting up SAM Framework development environment..."

# Check if we're in the project root
if [ ! -f "pyproject.toml" ]; then
    echo "❌ Error: This script must be run from the project root directory"
    exit 1
fi

# Install pre-commit if not already installed
if ! command -v pre-commit &> /dev/null; then
    echo "📦 Installing pre-commit..."
    uv add --dev pre-commit || pip install pre-commit
fi

# Install pre-commit hooks
echo "🔧 Installing pre-commit hooks..."
pre-commit install

# Run hooks on all files to ensure everything is clean
echo "🧹 Running pre-commit hooks on all files..."
pre-commit run --all-files || {
    echo "⚠️  Some pre-commit hooks failed. This is normal for first-time setup."
    echo "   Files have been automatically formatted. Please review and commit."
}

# Create local development .env if it doesn't exist
if [ ! -f ".env" ]; then
    echo "📝 Creating sample .env file..."
    cat > .env << 'EOF'
# SAM Framework Development Environment
# Copy this file and fill in your values

# LLM Provider (openai, anthropic, xai, local)
LLM_PROVIDER=openai

# API Keys (set your keys here)
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
# XAI_API_KEY=xai-...

# Solana Configuration
# SAM_SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
# SAM_WALLET_PRIVATE_KEY=...

# Security
# SAM_FERNET_KEY=...

# Development Settings
SAM_TEST_MODE=1
LOG_LEVEL=DEBUG
SAM_DEBUG_TIMING=0
SAM_DETAILED_MEMORY_STATS=0

# Performance Tuning
SAM_MAX_AGENT_ITERATIONS=5
SAM_HTTP_MAX_CONNECTIONS=100
SAM_HTTP_TIMEOUT=60

# Optional Services
# BRAVE_API_KEY=...
EOF
    echo "✅ Created .env file - please fill in your API keys"
fi

# Check if uv is being used
if command -v uv &> /dev/null; then
    echo "✅ Using uv for package management"
    echo "   Run: uv sync"
else
    echo "💡 Tip: Consider using 'uv' for faster dependency management"
    echo "   Install: pip install uv"
fi

echo ""
echo "✅ Development environment setup complete!"
echo ""
echo "Next steps:"
echo "  1. Fill in your .env file with API keys"
echo "  2. Run: uv sync (or pip install -e '.[dev]')"
echo "  3. Run: uv run sam onboard (for interactive setup)"
echo "  4. Start coding! Pre-commit hooks will run automatically."
echo ""
echo "Useful commands:"
echo "  • uv run pytest tests/        # Run tests"
echo "  • uv run ruff check --fix     # Lint code"
echo "  • uv run mypy sam/           # Type check"
echo "  • pre-commit run --all-files # Run all hooks"
echo ""


