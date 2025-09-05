"""CLI helpers for better user experience and onboarding."""

import os
from typing import Dict, Any
from ..config.settings import Settings
from .secure_storage import get_secure_storage


class CLIFormatter:
    """Beautiful CLI formatting utilities."""
    
    # Colors
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    # Background colors
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    
    @classmethod
    def colorize(cls, text: str, color: str) -> str:
        """Add color to text."""
        return f"{color}{text}{cls.RESET}"
    
    @classmethod
    def success(cls, text: str) -> str:
        """Format success message."""
        return cls.colorize(f"✅ {text}", cls.GREEN)
    
    @classmethod
    def warning(cls, text: str) -> str:
        """Format warning message."""
        return cls.colorize(f"⚠️  {text}", cls.YELLOW)
    
    @classmethod
    def error(cls, text: str) -> str:
        """Format error message."""
        return cls.colorize(f"❌ {text}", cls.RED)
    
    @classmethod
    def info(cls, text: str) -> str:
        """Format info message."""
        return cls.colorize(f"ℹ️  {text}", cls.CYAN)
    
    @classmethod
    def header(cls, text: str) -> str:
        """Format header text."""
        return cls.colorize(f"\n{cls.BOLD}{text}{cls.RESET}", cls.BLUE)
    
    @classmethod
    def box(cls, title: str, content: str, width: int = 60) -> str:
        """Create a bordered box with content."""
        horizontal = "─" * (width - 2)
        top = f"┌{horizontal}┐"
        bottom = f"└{horizontal}┘"
        
        lines = content.split('\n')
        boxed_lines = []
        
        # Title
        if title:
            title_line = f"│ {cls.BOLD}{title}{cls.RESET}"
            title_line += " " * (width - len(title) - 3) + "│"
            boxed_lines.append(title_line)
            boxed_lines.append(f"│{horizontal}│")
        
        # Content lines
        for line in lines:
            # Remove ANSI codes for length calculation
            clean_line = line
            for code in [cls.RESET, cls.BOLD, cls.DIM, cls.RED, cls.GREEN, cls.YELLOW, cls.BLUE, cls.MAGENTA, cls.CYAN, cls.WHITE]:
                clean_line = clean_line.replace(code, "")
            
            content_line = f"│ {line}"
            content_line += " " * (width - len(clean_line) - 3) + "│"
            boxed_lines.append(content_line)
        
        return f"{top}\n" + "\n".join(boxed_lines) + f"\n{bottom}"


def check_setup_status() -> Dict[str, Any]:
    """Check if SAM is properly set up."""
    status = {
        "openai_api_key": bool(Settings.OPENAI_API_KEY),
        "wallet_configured": False,
        "database_path": Settings.SAM_DB_PATH,
        "rpc_url": Settings.SAM_SOLANA_RPC_URL,
        "issues": [],
        "recommendations": []
    }
    
    # Check wallet configuration
    try:
        secure_storage = get_secure_storage()
        private_key = secure_storage.get_private_key("default")
        
        # Also check environment variable fallback (same as agent setup)
        if not private_key and Settings.SAM_WALLET_PRIVATE_KEY:
            private_key = Settings.SAM_WALLET_PRIVATE_KEY
            
        if private_key:
            status["wallet_configured"] = True
        else:
            status["issues"].append("No wallet configured")
            status["recommendations"].append("Run 'sam key import' to add your private key")
    except Exception as e:
        status["issues"].append(f"Wallet check failed: {e}")
        status["recommendations"].append("Check secure storage setup")
    
    # Check API key
    if not status["openai_api_key"]:
        status["issues"].append("OpenAI API key not set")
        status["recommendations"].append("Set OPENAI_API_KEY environment variable")
    
    # Check database path
    if not os.path.exists(os.path.dirname(status["database_path"]) or "."):
        status["issues"].append("Database directory doesn't exist")
        status["recommendations"].append(f"Create directory: {os.path.dirname(status['database_path'])}")
    
    return status


def show_welcome_banner():
    """Show welcome banner with setup status."""
    banner = f"""
{CLIFormatter.colorize('🤖 SAM - Solana Agent Middleware', CLIFormatter.BOLD + CLIFormatter.CYAN)}
{CLIFormatter.colorize('Production-Ready AI Agent for Solana Trading', CLIFormatter.DIM)}

{CLIFormatter.colorize('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', CLIFormatter.BLUE)}
"""
    print(banner)


def show_setup_status(verbose: bool = False):
    """Show current setup status."""
    status = check_setup_status()
    
    print(CLIFormatter.header("Setup Status"))
    
    # Show status checks
    api_status = "✅ Connected" if status["openai_api_key"] else "❌ Missing"
    wallet_status = "✅ Configured" if status["wallet_configured"] else "❌ Not configured"
    
    print(f"OpenAI API: {api_status}")
    print(f"Wallet:     {wallet_status}")
    print(f"RPC URL:    {CLIFormatter.colorize(status['rpc_url'], CLIFormatter.DIM)}")
    
    if verbose:
        print(f"Database:   {status['database_path']}")
    
    # Show issues and recommendations
    if status["issues"]:
        print(CLIFormatter.header("Issues Found"))
        for issue in status["issues"]:
            print(CLIFormatter.error(issue))
        
        print(CLIFormatter.header("Recommendations"))
        for rec in status["recommendations"]:
            print(CLIFormatter.info(rec))
    else:
        print(CLIFormatter.success("\nAll systems ready! 🚀"))


def show_onboarding_guide():
    """Show step-by-step onboarding guide."""
    print(CLIFormatter.header("🚀 Quick Setup Guide"))
    
    status = check_setup_status()
    
    steps = []
    
    if not status["openai_api_key"]:
        steps.append({
            "title": "1️⃣  Set up OpenAI API Key",
            "commands": [
                "export OPENAI_API_KEY='your-api-key-here'",
                "# Or add to your ~/.bashrc or ~/.zshrc"
            ],
            "description": "Get your API key from: https://platform.openai.com/api-keys"
        })
    
    if not status["wallet_configured"]:
        steps.append({
            "title": "2️⃣  Configure Your Wallet",
            "commands": [
                "sam key import",
                "# Follow the secure prompts to add your private key"
            ],
            "description": "Your private key is stored securely in system keyring"
        })
    
    if not steps:
        steps.append({
            "title": "🎉 You're all set!",
            "commands": [
                "sam run",
                "# Start trading: 'buy 0.01 SOL of BONK'"
            ],
            "description": "Your SAM agent is ready for Solana trading"
        })
    
    for step in steps:
        print(f"\n{CLIFormatter.colorize(step['title'], CLIFormatter.BOLD + CLIFormatter.BLUE)}")
        print(f"{CLIFormatter.colorize(step['description'], CLIFormatter.DIM)}")
        print()
        for cmd in step['commands']:
            if cmd.startswith('#'):
                print(f"  {CLIFormatter.colorize(cmd, CLIFormatter.DIM)}")
            else:
                print(f"  {CLIFormatter.colorize(cmd, CLIFormatter.GREEN)}")


def show_quick_help():
    """Show quick help for common commands."""
    help_text = f"""
{CLIFormatter.header("Quick Commands")}

{CLIFormatter.colorize("Setup:", CLIFormatter.BOLD)}
  sam setup          - Check setup status
  sam key import     - Import private key securely
  sam health         - System health check

{CLIFormatter.colorize("Trading:", CLIFormatter.BOLD)}
  sam run            - Start interactive agent
  
{CLIFormatter.colorize("Example Conversations:", CLIFormatter.BOLD)}
  💰 "check my balance"
  🚀 "buy 0.1 SOL of BONK"
  💎 "sell 50% of my WIF"
  📊 "what's trending on pump.fun?"

{CLIFormatter.colorize("Maintenance:", CLIFormatter.BOLD)}
  sam maintenance    - Clean up old data
  sam --help         - Full command reference
"""
    print(help_text)


def format_balance_display(balance_data: Dict[str, Any]) -> str:
    """Format balance data for beautiful display."""
    if balance_data.get("error"):
        return CLIFormatter.error(f"Balance Error: {balance_data.get('title', 'Unknown error')}")
    
    output = []
    
    # Header
    address = balance_data.get("address", "Unknown")
    short_address = f"{address[:8]}...{address[-8:]}" if len(address) > 20 else address
    output.append(CLIFormatter.header(f"Wallet: {short_address}"))
    
    # SOL Balance with USD
    sol_balance = balance_data.get("sol_balance", 0)
    if "formatted_sol" in balance_data:
        sol_display = balance_data["formatted_sol"]
    else:
        sol_display = f"{sol_balance:.4f} SOL"
    
    output.append(f"{CLIFormatter.colorize('SOL:', CLIFormatter.BOLD)} {sol_display}")
    
    # Total portfolio value
    total_usd = balance_data.get("total_portfolio_usd")
    if total_usd:
        output.append(f"{CLIFormatter.colorize('Portfolio:', CLIFormatter.BOLD)} ${total_usd:.2f}")
    
    # Tokens
    tokens = balance_data.get("tokens", [])
    token_count = balance_data.get("token_count", len(tokens))
    
    if token_count > 0:
        output.append(f"\n{CLIFormatter.colorize(f'Tokens ({token_count}):', CLIFormatter.BOLD)}")
        
        for token in tokens[:10]:  # Show first 10 tokens
            mint = token.get("mint", "Unknown")
            amount = token.get("uiAmount", 0)
            
            # Short mint address
            short_mint = f"{mint[:6]}...{mint[-4:]}" if len(mint) > 12 else mint
            
            if amount > 0:
                output.append(f"  • {amount:,.4f} {short_mint}")
        
        if token_count > 10:
            output.append(f"  {CLIFormatter.colorize(f'... and {token_count - 10} more tokens', CLIFormatter.DIM)}")
    else:
        output.append(f"\n{CLIFormatter.colorize('No tokens found', CLIFormatter.DIM)}")
    
    return "\n".join(output)


def format_error_for_cli(error_data: Dict[str, Any]) -> str:
    """Format error data for CLI display."""
    if not error_data.get("error"):
        return str(error_data)
    
    title = error_data.get("title", "Error")
    message = error_data.get("message", "Something went wrong")
    solutions = error_data.get("solutions", [])
    category = error_data.get("category", "system")
    
    # Choose emoji based on category
    category_icons = {
        "wallet": "👛",
        "network": "🌐", 
        "trading": "💱",
        "validation": "⚠️",
        "authentication": "🔑",
        "system": "🔧"
    }
    
    icon = category_icons.get(category, "❌")
    
    output = [f"{icon} {CLIFormatter.colorize(title, CLIFormatter.BOLD + CLIFormatter.RED)}"]
    output.append(f"{message}")
    
    if solutions:
        output.append(f"\n{CLIFormatter.colorize('💡 How to fix:', CLIFormatter.BOLD + CLIFormatter.YELLOW)}")
        for i, solution in enumerate(solutions, 1):
            output.append(f"{i}. {solution}")
    
    return "\n".join(output)


def is_first_run() -> bool:
    """Check if this is the user's first time running SAM."""
    return not os.path.exists(Settings.SAM_DB_PATH)


def show_first_run_experience():
    """Show first-run experience with onboarding."""
    show_welcome_banner()
    
    print(CLIFormatter.info("Welcome! It looks like this is your first time using SAM."))
    print("Let's get you set up for Solana trading! 🚀\n")
    
    show_onboarding_guide()
    
    print(f"\n{CLIFormatter.colorize('Need help?', CLIFormatter.BOLD)} Run 'sam --help' for all commands")
    print(f"{CLIFormatter.colorize('Ready to trade?', CLIFormatter.BOLD)} Run 'sam run' to start the agent")


def show_startup_summary():
    """Show brief startup summary for returning users."""
    status = check_setup_status()
    
    if status["issues"]:
        print(CLIFormatter.warning("Setup issues detected:"))
        for issue in status["issues"]:
            print(f"  • {issue}")
        print(f"\nRun '{CLIFormatter.colorize('sam setup', CLIFormatter.GREEN)}' for help\n")
    else:
        print(CLIFormatter.success("SAM ready for trading! 🚀"))
        print(f"Try: {CLIFormatter.colorize('check my balance', CLIFormatter.GREEN)} or {CLIFormatter.colorize('buy 0.01 SOL of BONK', CLIFormatter.GREEN)}\n")