#!/usr/bin/env python3
"""
Comprehensive Aster Futures Integration Test Script

This script tests all Aster futures tools exactly as they would be used by the AI agent,
with full .env configuration, verbose logging, and real API calls (with small amounts).
"""

import asyncio
import json
import logging
import sys
from typing import Dict, Any, List
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from sam.config.settings import Settings
from sam.integrations.aster_futures import AsterFuturesClient, create_aster_futures_tools
from sam.utils.secure_storage import get_secure_storage

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("aster_test.log", mode="w")],
)

logger = logging.getLogger(__name__)


class AsterToolTester:
    """Comprehensive tester for all Aster futures tools."""

    def __init__(self):
        self.client: AsterFuturesClient = None
        self.tools: List = []
        self.test_results: Dict[str, Any] = {}

    async def setup(self):
        """Set up the testing environment with real credentials from .env"""
        logger.info("🚀 Starting Aster Futures Tool Comprehensive Test")
        logger.info("=" * 60)

        # Load environment variables
        self._load_env_config()

        # Set up secure storage and credentials
        await self._setup_credentials()

        # Create client and tools
        await self._setup_client_and_tools()

        # Verify connectivity
        await self._verify_connectivity()

    def _load_env_config(self):
        """Load and display environment configuration"""
        logger.info("📋 Environment Configuration:")
        logger.info(f"  ENABLE_ASTER_FUTURES_TOOLS: {Settings.ENABLE_ASTER_FUTURES_TOOLS}")
        logger.info(f"  ASTER_BASE_URL: {Settings.ASTER_BASE_URL}")
        logger.info(f"  ASTER_DEFAULT_RECV_WINDOW: {Settings.ASTER_DEFAULT_RECV_WINDOW}")
        logger.info(f"  ASTER_API_KEY exists: {bool(Settings.ASTER_API_KEY)}")
        logger.info(f"  ASTER_API_SECRET exists: {bool(Settings.ASTER_API_SECRET)}")

        if not Settings.ENABLE_ASTER_FUTURES_TOOLS:
            logger.warning("⚠️  ENABLE_ASTER_FUTURES_TOOLS is False - tools may not be loaded")

    async def _setup_credentials(self):
        """Set up API credentials from secure storage or environment"""
        logger.info("🔑 Setting up API credentials...")

        secure_storage = get_secure_storage()

        # Get API key
        api_key = secure_storage.get_api_key("aster_api")
        if not api_key and Settings.ASTER_API_KEY:
            logger.info("  Migrating API key from environment to secure storage")
            if secure_storage.store_api_key("aster_api", Settings.ASTER_API_KEY):
                api_key = Settings.ASTER_API_KEY
                logger.info("  ✅ API key migrated successfully")
            else:
                api_key = Settings.ASTER_API_KEY
                logger.warning("  ⚠️  API key migration failed, using direct value")

        # Get API secret
        api_secret = secure_storage.get_private_key("aster_api_secret")
        if not api_secret and Settings.ASTER_API_SECRET:
            logger.info("  Migrating API secret from environment to secure storage")
            if secure_storage.store_private_key("aster_api_secret", Settings.ASTER_API_SECRET):
                api_secret = Settings.ASTER_API_SECRET
                logger.info("  ✅ API secret migrated successfully")
            else:
                api_secret = Settings.ASTER_API_SECRET
                logger.warning("  ⚠️  API secret migration failed, using direct value")

        if not api_key or not api_secret:
            logger.error("❌ Missing API credentials!")
            logger.error("   Please set ASTER_API_KEY and ASTER_API_SECRET in .env file")
            raise ValueError("Missing Aster API credentials")

        logger.info(
            f"  ✅ API key: {api_key[:8]}...{api_key[-4:] if len(api_key) > 12 else 'short'}"
        )
        logger.info(
            f"  ✅ API secret: {api_secret[:8]}...{api_secret[-4:] if len(api_secret) > 12 else 'short'}"
        )

        # Store for client creation
        self.api_key = api_key
        self.api_secret = api_secret

    async def _setup_client_and_tools(self):
        """Create Aster client and tools exactly as the agent does"""
        logger.info("🔧 Creating Aster client and tools...")

        # Create client with same parameters as AgentBuilder
        self.client = AsterFuturesClient(
            base_url=Settings.ASTER_BASE_URL,
            api_key=self.api_key,
            api_secret=self.api_secret,
            default_recv_window=Settings.ASTER_DEFAULT_RECV_WINDOW,
        )

        # Create tools exactly as in AgentBuilder
        self.tools = create_aster_futures_tools(self.client)

        logger.info(f"  ✅ Created {len(self.tools)} Aster tools:")
        for tool in self.tools:
            logger.info(f"    - {tool.spec.name}: {tool.spec.description}")

    async def _verify_connectivity(self):
        """Verify basic connectivity to Aster API"""
        logger.info("🌐 Verifying API connectivity...")

        try:
            # Test basic endpoint connectivity (this should work without auth)
            result = await self.client._public_get("/fapi/v1/ping", {})  # pylint: disable=protected-access
            if result.get("status") == 200:
                logger.info("  ✅ Basic connectivity: OK")
            else:
                logger.warning(f"  ⚠️  Basic connectivity returned: {result}")
        except Exception as e:
            logger.error(f"  ❌ Basic connectivity failed: {e}")

        # Test authenticated endpoint
        try:
            balance_tool = next(
                tool for tool in self.tools if tool.spec.name == "aster_account_balance"
            )
            result = await balance_tool.handler({})
            if "error" not in result:
                logger.info("  ✅ Authenticated connectivity: OK")
            else:
                logger.warning(f"  ⚠️  Authenticated connectivity error: {result.get('error')}")
        except Exception as e:
            logger.error(f"  ❌ Authenticated connectivity failed: {e}")

    async def test_all_tools(self):
        """Test all Aster tools with realistic scenarios"""
        logger.info("🧪 Testing All Aster Tools")
        logger.info("=" * 60)

        # Test each tool in logical order
        await self._test_account_balance()
        await self._test_account_info()
        await self._test_position_check()
        await self._test_trade_history()
        await self._test_open_long_with_usd_notional()
        await self._test_open_long_with_quantity()
        await self._test_close_position()

        # Print summary
        self._print_test_summary()

    async def _test_account_balance(self):
        """Test aster_account_balance tool"""
        logger.info("💰 Testing aster_account_balance...")

        try:
            balance_tool = next(
                tool for tool in self.tools if tool.spec.name == "aster_account_balance"
            )

            # Test with default parameters
            result = await balance_tool.handler({})

            self.test_results["account_balance"] = {
                "success": "error" not in result,
                "result": result,
                "notes": "Basic balance check",
            }

            if "error" not in result:
                logger.info("  ✅ Account balance retrieved successfully")
                if "balances" in result and "response" in result["balances"]:
                    balances = result["balances"]["response"]
                    if isinstance(balances, list):
                        logger.info(f"    Found {len(balances)} asset balances")
                        for balance in balances[:3]:  # Show first 3
                            asset = balance.get("asset", "Unknown")
                            available = balance.get("availableBalance", "0")
                            logger.info(f"    - {asset}: {available}")
                    else:
                        logger.info(f"    Raw response: {balances}")
            else:
                logger.error(f"  ❌ Account balance failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"  ❌ Account balance test failed: {e}")
            self.test_results["account_balance"] = {"success": False, "error": str(e)}

    async def _test_account_info(self):
        """Test aster_account_info tool"""
        logger.info("📊 Testing aster_account_info...")

        try:
            info_tool = next(tool for tool in self.tools if tool.spec.name == "aster_account_info")

            result = await info_tool.handler({})

            self.test_results["account_info"] = {
                "success": "error" not in result,
                "result": result,
                "notes": "Full account information",
            }

            if "error" not in result:
                logger.info("  ✅ Account info retrieved successfully")
                if "account" in result and "response" in result["account"]:
                    account = result["account"]["response"]
                    logger.info(f"    Can trade: {account.get('canTrade', 'Unknown')}")
                    logger.info(
                        f"    Total wallet balance: {account.get('totalWalletBalance', 'Unknown')}"
                    )
                    logger.info(
                        f"    Available balance: {account.get('availableBalance', 'Unknown')}"
                    )
            else:
                logger.error(f"  ❌ Account info failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"  ❌ Account info test failed: {e}")
            self.test_results["account_info"] = {"success": False, "error": str(e)}

    async def _test_position_check(self):
        """Test aster_position_check tool"""
        logger.info("📈 Testing aster_position_check...")

        try:
            position_tool = next(
                tool for tool in self.tools if tool.spec.name == "aster_position_check"
            )

            # Test without symbol filter (all positions)
            result = await position_tool.handler({})

            self.test_results["position_check_all"] = {
                "success": "error" not in result,
                "result": result,
                "notes": "All positions check",
            }

            if "error" not in result:
                logger.info("  ✅ Position check retrieved successfully")
                if "positions" in result and "response" in result["positions"]:
                    positions = result["positions"]["response"]
                    if isinstance(positions, list):
                        logger.info(f"    Found {len(positions)} positions")
                        for pos in positions[:3]:  # Show first 3
                            symbol = pos.get("symbol", "Unknown")
                            size = pos.get("positionAmt", "0")
                            side = pos.get("positionSide", "Unknown")
                            logger.info(f"    - {symbol} {side}: {size}")
                    else:
                        logger.info(f"    Raw response: {positions}")
            else:
                logger.error(f"  ❌ Position check failed: {result.get('error')}")

            # Test with SOLUSDT filter
            result_sol = await position_tool.handler({"symbol": "SOLUSDT"})

            self.test_results["position_check_solusdt"] = {
                "success": "error" not in result_sol,
                "result": result_sol,
                "notes": "SOLUSDT position check",
            }

            if "error" not in result_sol:
                logger.info("  ✅ SOLUSDT position check successful")
            else:
                logger.error(f"  ❌ SOLUSDT position check failed: {result_sol.get('error')}")

        except Exception as e:
            logger.error(f"  ❌ Position check test failed: {e}")
            self.test_results["position_check"] = {"success": False, "error": str(e)}

    async def _test_trade_history(self):
        """Test aster_trade_history tool"""
        logger.info("📜 Testing aster_trade_history...")

        try:
            history_tool = next(
                tool for tool in self.tools if tool.spec.name == "aster_trade_history"
            )

            # Test with SOLUSDT and small limit
            result = await history_tool.handler({"symbol": "SOLUSDT", "limit": 5})

            self.test_results["trade_history"] = {
                "success": "error" not in result,
                "result": result,
                "notes": "Recent SOLUSDT trades",
            }

            if "error" not in result:
                logger.info("  ✅ Trade history retrieved successfully")
                if "trades" in result and "response" in result["trades"]:
                    trades = result["trades"]["response"]
                    if isinstance(trades, list):
                        logger.info(f"    Found {len(trades)} recent trades")
                        for trade in trades[:3]:  # Show first 3
                            side = trade.get("side", "Unknown")
                            qty = trade.get("qty", "0")
                            price = trade.get("price", "0")
                            logger.info(f"    - {side} {qty} @ {price}")
                    else:
                        logger.info(f"    Raw response: {trades}")
            else:
                logger.error(f"  ❌ Trade history failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"  ❌ Trade history test failed: {e}")
            self.test_results["trade_history"] = {"success": False, "error": str(e)}

    async def _test_open_long_with_usd_notional(self):
        """Test aster_open_long tool with USD notional (small amount)"""
        logger.info("📈 Testing aster_open_long with USD notional ($10)...")

        try:
            open_tool = next(tool for tool in self.tools if tool.spec.name == "aster_open_long")

            # Test with $10 USD notional at 2x leverage (well above minimum)
            test_params = {
                "symbol": "SOLUSDT",
                "usd_notional": 10.0,  # $10 (well above $5 minimum)
                "leverage": 2,  # 2x leverage (conservative)
            }

            logger.info(f"  Test parameters: {test_params}")

            result = await open_tool.handler(test_params)

            self.test_results["open_long_usd_notional"] = {
                "success": "error" not in result,
                "result": result,
                "notes": "Small USD notional long position",
                "params": test_params,
            }

            if "error" not in result:
                logger.info("  ✅ Long position opened successfully with USD notional")
                if "order_response" in result:
                    order = result["order_response"].get("response", {})
                    logger.info(f"    Order ID: {order.get('orderId', 'Unknown')}")
                    logger.info(f"    Status: {order.get('status', 'Unknown')}")
                    logger.info(f"    Quantity: {order.get('origQty', 'Unknown')}")
            else:
                logger.error(f"  ❌ Long position (USD notional) failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"  ❌ Open long (USD notional) test failed: {e}")
            self.test_results["open_long_usd_notional"] = {"success": False, "error": str(e)}

    async def _test_open_long_with_quantity(self):
        """Test aster_open_long tool with direct quantity (small amount)"""
        logger.info("📈 Testing aster_open_long with quantity (0.03 SOL)...")

        try:
            open_tool = next(tool for tool in self.tools if tool.spec.name == "aster_open_long")

            # Test with quantity that meets $5 minimum notional
            test_params = {
                "symbol": "SOLUSDT",
                "quantity": 0.03,  # 0.03 SOL (~$7+ notional)
                "leverage": 2,  # 2x leverage (conservative)
            }

            logger.info(f"  Test parameters: {test_params}")

            result = await open_tool.handler(test_params)

            self.test_results["open_long_quantity"] = {
                "success": "error" not in result,
                "result": result,
                "notes": "Small quantity long position",
                "params": test_params,
            }

            if "error" not in result:
                logger.info("  ✅ Long position opened successfully with quantity")
                if "order_response" in result:
                    order = result["order_response"].get("response", {})
                    logger.info(f"    Order ID: {order.get('orderId', 'Unknown')}")
                    logger.info(f"    Status: {order.get('status', 'Unknown')}")
                    logger.info(f"    Filled Quantity: {order.get('executedQty', 'Unknown')}")
            else:
                logger.error(f"  ❌ Long position (quantity) failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"  ❌ Open long (quantity) test failed: {e}")
            self.test_results["open_long_quantity"] = {"success": False, "error": str(e)}

    async def _test_close_position(self):
        """Test aster_close_position tool (if we have positions)"""
        logger.info("📉 Testing aster_close_position...")

        try:
            # First check if we have any positions to close
            position_tool = next(
                tool for tool in self.tools if tool.spec.name == "aster_position_check"
            )
            positions_result = await position_tool.handler({"symbol": "SOLUSDT"})

            if "error" in positions_result:
                logger.warning("  ⚠️  Cannot check positions for close test")
                self.test_results["close_position"] = {
                    "success": False,
                    "error": "Cannot check positions",
                    "notes": "Skipped due to position check failure",
                }
                return

            # Look for SOLUSDT positions
            positions = positions_result.get("positions", {}).get("response", [])
            if not isinstance(positions, list):
                positions = []

            solusdt_positions = [
                p
                for p in positions
                if p.get("symbol") == "SOLUSDT" and float(p.get("positionAmt", 0)) != 0
            ]

            if not solusdt_positions:
                logger.info("  ℹ️  No SOLUSDT positions to close - test will be simulation only")

                # Test with minimal parameters (will likely fail due to no position)
                close_tool = next(
                    tool for tool in self.tools if tool.spec.name == "aster_close_position"
                )

                test_params = {
                    "symbol": "SOLUSDT",
                    "quantity": 0.01,  # Minimum quantity that respects lot size
                    "reduce_only": True,
                }

                result = await close_tool.handler(test_params)

                self.test_results["close_position"] = {
                    "success": "error" not in result,
                    "result": result,
                    "notes": "Simulation test - no position to close",
                    "params": test_params,
                }

                if "error" in result:
                    logger.info(
                        f"  ✅ Close position correctly failed (no position): {result.get('error')}"
                    )
                else:
                    logger.warning(f"  ⚠️  Close position unexpectedly succeeded: {result}")

            else:
                # We have actual positions - test closing a small portion
                position = solusdt_positions[0]
                position_size = abs(float(position.get("positionAmt", 0)))
                position_side = position.get("positionSide", "LONG")

                # Close a small portion (10% or minimum 0.01 to respect lot size)
                close_quantity = max(0.01, position_size * 0.1)

                logger.info(f"    Found position: {position_size} {position_side}")
                logger.info(f"    Will close: {close_quantity}")

                close_tool = next(
                    tool for tool in self.tools if tool.spec.name == "aster_close_position"
                )

                test_params = {"symbol": "SOLUSDT", "quantity": close_quantity, "reduce_only": True}

                result = await close_tool.handler(test_params)

                self.test_results["close_position"] = {
                    "success": "error" not in result,
                    "result": result,
                    "notes": f"Partial close of {position_side} position",
                    "params": test_params,
                }

                if "error" not in result:
                    logger.info("  ✅ Position partially closed successfully")
                    if "order_response" in result:
                        order = result["order_response"].get("response", {})
                        logger.info(f"    Order ID: {order.get('orderId', 'Unknown')}")
                        logger.info(f"    Status: {order.get('status', 'Unknown')}")
                else:
                    logger.error(f"  ❌ Position close failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"  ❌ Close position test failed: {e}")
            self.test_results["close_position"] = {"success": False, "error": str(e)}

    def _print_test_summary(self):
        """Print a comprehensive test summary"""
        logger.info("📋 Test Summary")
        logger.info("=" * 60)

        total_tests = len(self.test_results)
        successful_tests = sum(
            1 for result in self.test_results.values() if result.get("success", False)
        )

        logger.info(f"Total tests: {total_tests}")
        logger.info(f"Successful: {successful_tests}")
        logger.info(f"Failed: {total_tests - successful_tests}")
        logger.info(f"Success rate: {(successful_tests / total_tests * 100):.1f}%")

        logger.info("\nDetailed Results:")
        for test_name, result in self.test_results.items():
            status = "✅ PASS" if result.get("success", False) else "❌ FAIL"
            notes = result.get("notes", "")
            logger.info(f"  {status} {test_name}: {notes}")

            if not result.get("success", False) and "error" in result:
                logger.info(f"      Error: {result['error']}")

        # Save detailed results to file
        with open("aster_test_results.json", "w") as f:
            json.dump(self.test_results, f, indent=2, default=str)
        logger.info("\nDetailed results saved to: aster_test_results.json")
        logger.info("Log file saved to: aster_test.log")


async def main():
    """Main test runner"""
    print("🚀 Aster Futures Tools - Comprehensive Integration Test")
    print("=" * 60)
    print("This script will test all Aster futures tools with real API calls")
    print("using your .env configuration and small amounts for safety.")
    print()

    # Check if user wants to proceed
    if len(sys.argv) > 1 and sys.argv[1] == "--auto":
        proceed = True
    else:
        proceed = input("Do you want to proceed? (y/N): ").lower().startswith("y")

    if not proceed:
        print("Test cancelled by user.")
        return

    try:
        tester = AsterToolTester()
        await tester.setup()
        await tester.test_all_tools()

        logger.info("🎉 Comprehensive test completed!")

    except Exception as e:
        logger.error(f"❌ Test suite failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
