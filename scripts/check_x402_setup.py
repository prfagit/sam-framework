#!/usr/bin/env python3
"""Diagnostic script to verify X402/AIXBT integration setup."""

import asyncio
import sys
from typing import Optional

from sam.config.settings import Settings
from sam.utils.secure_storage import get_secure_storage


def format_status(condition: bool) -> str:
    """Format status with emoji."""
    return "✅" if condition else "❌"


async def check_x402_setup() -> int:
    """Check X402 and AIXBT configuration and return exit code."""
    Settings.refresh_from_env()
    storage = get_secure_storage()
    
    errors = []
    warnings = []
    
    print("=" * 60)
    print("SAM X402/AIXBT Integration Diagnostic")
    print("=" * 60)
    print()
    
    # Check tool enablement
    print("📋 Tool Enablement:")
    aixbt_enabled = Settings.ENABLE_AIXBT_TOOLS
    print(f"  {format_status(aixbt_enabled)} AIXBT tools: {aixbt_enabled}")
    if not aixbt_enabled:
        warnings.append("AIXBT tools disabled. Set ENABLE_AIXBT_TOOLS=true in .env")
    
    coinbase_enabled = Settings.ENABLE_COINBASE_X402_TOOLS
    print(f"  {format_status(coinbase_enabled)} Coinbase X402 tools: {coinbase_enabled}")
    if not coinbase_enabled:
        warnings.append("Coinbase X402 tools disabled. Set ENABLE_COINBASE_X402_TOOLS=true in .env")
    
    print()
    
    # Check dependencies
    print("📦 Dependencies:")
    try:
        from x402.facilitator import FacilitatorClient  # type: ignore
        from x402.clients.httpx import x402HttpxClient  # type: ignore
        print(f"  {format_status(True)} x402 package installed")
    except ImportError:
        print(f"  {format_status(False)} x402 package NOT installed")
        errors.append("x402 package missing. Install with: uv add x402")
    
    try:
        from eth_account import Account  # type: ignore
        print(f"  {format_status(True)} eth-account package installed")
    except ImportError:
        print(f"  {format_status(False)} eth-account package NOT installed")
        errors.append("eth-account package missing. Install with: uv add eth-account")
    
    print()
    
    # Check API endpoints
    print("🌐 API Configuration:")
    print(f"  AIXBT API: {Settings.AIXBT_API_BASE_URL}")
    print(f"  Coinbase facilitator: {Settings.COINBASE_X402_FACILITATOR_URL}")
    
    api_key = Settings.COINBASE_X402_API_KEY
    print(f"  {format_status(bool(api_key))} Coinbase API key: {'configured' if api_key else 'not set (optional)'}")
    print()
    
    # Check EVM wallet/keys
    print("🔑 EVM Wallet Configuration:")
    
    aixbt_key_env: Optional[str] = Settings.AIXBT_PRIVATE_KEY
    print(f"  {format_status(bool(aixbt_key_env))} AIXBT_PRIVATE_KEY env: {bool(aixbt_key_env)}")
    
    try:
        hyper_key: Optional[str] = storage.get_private_key("hyperliquid_private_key")
    except Exception:
        hyper_key = None
    print(f"  {format_status(bool(hyper_key))} Hyperliquid key (storage): {bool(hyper_key)}")
    
    try:
        aixbt_key_storage: Optional[str] = storage.get_private_key("aixbt_private_key")
    except Exception:
        aixbt_key_storage = None
    print(f"  {format_status(bool(aixbt_key_storage))} AIXBT key (storage): {bool(aixbt_key_storage)}")
    
    # Determine effective key
    effective_key = aixbt_key_env or aixbt_key_storage or hyper_key
    has_wallet = bool(effective_key)
    print(f"\n  {format_status(has_wallet)} Effective EVM wallet: {has_wallet}")
    
    if has_wallet and effective_key:
        # Show key format
        if effective_key.startswith("0x"):
            print(f"      Format: {effective_key[:6]}...{effective_key[-4:]}")
        else:
            print(f"      Format: {effective_key[:4]}...{effective_key[-4:]}")
        
        # Try to derive address
        try:
            from eth_account import Account
            account = Account.from_key(effective_key)
            print(f"      Address: {account.address}")
        except Exception as exc:
            print(f"      ⚠️  Could not derive address: {exc}")
            warnings.append("EVM key present but may be invalid")
    else:
        errors.append(
            "No EVM private key configured. AIXBT tools require an EVM wallet for X402 payments. "
            "Set AIXBT_PRIVATE_KEY or use your Hyperliquid key."
        )
    
    # EVM account address check
    evm_address = Settings.EVM_WALLET_ADDRESS or Settings.HYPERLIQUID_ACCOUNT_ADDRESS
    if evm_address:
        print(f"  {format_status(True)} EVM account address: {evm_address}")
    
    print()
    
    # Check agent configuration
    print("🤖 Agent Configuration:")
    try:
        import tomli
        with open("agents/coinbase-intelligence.agent.toml", "rb") as f:
            config = tomli.load(f)
        
        tools = config.get("tools", [])
        required_tools = {"aixbt", "coinbase_x402"}
        configured_tools = {t.get("name") for t in tools if t.get("enabled", False)}
        
        for tool in required_tools:
            enabled = tool in configured_tools
            print(f"  {format_status(enabled)} {tool}: {enabled}")
            
        print(f"\n  Agent uses: {len(configured_tools)} tool bundle(s)")
    except FileNotFoundError:
        print("  ⚠️  coinbase-intelligence.agent.toml not found")
    except Exception as exc:
        print(f"  ⚠️  Could not parse agent config: {exc}")
    
    print()
    print("=" * 60)
    
    # Summary
    if errors:
        print("\n❌ ERRORS (must fix):")
        for i, error in enumerate(errors, 1):
            print(f"  {i}. {error}")
    
    if warnings:
        print("\n⚠️  WARNINGS (recommended fixes):")
        for i, warning in enumerate(warnings, 1):
            print(f"  {i}. {warning}")
    
    if not errors and not warnings:
        print("\n✅ All checks passed! X402/AIXBT integration is ready.")
        print("\n🚀 Try running: uv run sam agents run coinbase-intelligence")
        return 0
    elif errors:
        print("\n❌ Setup incomplete. Please fix the errors above.")
        return 1
    else:
        print("\n✅ Setup functional but has warnings. You can proceed.")
        return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(check_x402_setup())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(130)
    except Exception as exc:
        print(f"\n❌ Unexpected error: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

