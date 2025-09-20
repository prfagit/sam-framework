# Aster Futures Tools - Comprehensive Testing Guide

This guide explains how to test all Aster Futures tools with real API calls using small amounts for safety.

## Overview

The Aster Futures integration provides 6 tools for automated futures trading:

1. **aster_account_balance** - Get futures wallet balances
2. **aster_account_info** - Get detailed account information
3. **aster_position_check** - Check current positions and risk
4. **aster_trade_history** - Get recent trade history
5. **aster_open_long** - Open leveraged long positions
6. **aster_close_position** - Close or reduce positions

## Prerequisites

### 1. Aster API Credentials

1. Create an account at [https://www.asterdex.com/](https://www.asterdex.com/)
2. Generate API credentials with futures trading permissions
3. Add them to your `.env` file:

```bash
# Aster Futures Configuration
ENABLE_ASTER_FUTURES_TOOLS=true
ASTER_API_KEY=your_api_key_here
ASTER_API_SECRET=your_api_secret_here
ASTER_BASE_URL=https://fapi.asterdex.com
ASTER_DEFAULT_RECV_WINDOW=5000
```

### 2. Test Funds

- Ensure you have a small amount of USDT/USDC in your Aster futures wallet
- Tests use minimal amounts ($1-2 USD) for safety
- Have at least $10-20 available for comprehensive testing

## Running the Tests

### Quick Test

```bash
# Make sure you're in the sam_framework directory
cd sam_framework

# Run the test suite
./run_aster_test.sh
```

### Manual Test

```bash
# Set debug logging
export LOG_LEVEL=DEBUG

# Run the comprehensive test
uv run python test_aster_comprehensive.py
```

### Individual Tool Testing

You can also test tools individually using the SAM CLI:

```bash
# Start SAM
uv run sam

# Test account balance
check aster balance

# Test opening a small long position
open long 1 dollar with 2x leverage

# Check positions
check my aster positions

# Test trade history
show my recent aster trades
```

## Test Details

The comprehensive test script performs the following tests:

### 1. Environment Setup
- ✅ Loads `.env` configuration
- ✅ Sets up API credentials in secure storage
- ✅ Creates Aster client with proper authentication
- ✅ Verifies basic and authenticated connectivity

### 2. Account Information Tests
- ✅ **Account Balance**: Retrieves all asset balances
- ✅ **Account Info**: Gets detailed account information
- ✅ **Position Check**: Lists all current positions
- ✅ **Trade History**: Fetches recent trade history

### 3. Trading Tests (Small Amounts)
- ✅ **Open Long (USD Notional)**: Opens $1 long position with 2x leverage
- ✅ **Open Long (Quantity)**: Opens 0.001 SOL long position with 2x leverage
- ✅ **Close Position**: Partially closes position if one exists

## Safety Features

### Conservative Testing Parameters
- **Maximum leverage**: 2x (very conservative)
- **Minimum position sizes**: $1 USD or 0.001 SOL
- **Reduce-only orders**: Used for position closing
- **Position size limits**: Tests only close 1% of existing positions

### Error Handling
- ✅ Comprehensive error logging
- ✅ API response validation
- ✅ Network timeout handling
- ✅ Credential verification

### Logging and Output
- ✅ Detailed logs saved to `aster_test.log`
- ✅ Test results saved to `aster_test_results.json`
- ✅ Real-time console output with status indicators
- ✅ Summary report with success/failure rates

## Expected Results

### Successful Test Run
```
🚀 Aster Futures Tools - Comprehensive Integration Test
============================================================
🔧 Creating Aster client and tools...
  ✅ Created 6 Aster tools
🌐 Verifying API connectivity...
  ✅ Basic connectivity: OK
  ✅ Authenticated connectivity: OK

🧪 Testing All Aster Tools
============================================================
💰 Testing aster_account_balance...
  ✅ Account balance retrieved successfully
    Found 3 asset balances
📊 Testing aster_account_info...
  ✅ Account info retrieved successfully
📈 Testing aster_position_check...
  ✅ Position check retrieved successfully
📜 Testing aster_trade_history...
  ✅ Trade history retrieved successfully
📈 Testing aster_open_long with USD notional ($1)...
  ✅ Long position opened successfully with USD notional
📈 Testing aster_open_long with quantity (0.001 SOL)...
  ✅ Long position opened successfully with quantity
📉 Testing aster_close_position...
  ✅ Position partially closed successfully

📋 Test Summary
============================================================
Total tests: 7
Successful: 7
Failed: 0
Success rate: 100.0%
```

### Common Issues and Solutions

#### Authentication Errors
```
❌ Missing API credentials!
```
**Solution**: Ensure `ASTER_API_KEY` and `ASTER_API_SECRET` are set in `.env`

#### Insufficient Balance
```
❌ Account balance failed: Insufficient margin
```
**Solution**: Add USDT/USDC to your Aster futures wallet

#### Position Size Errors
```
❌ Long position failed: Order would be too small
```
**Solution**: Increase test amounts or check minimum order sizes

#### Network Issues
```
❌ Basic connectivity failed: Connection timeout
```
**Solution**: Check internet connection and Aster API status

## Integration with SAM Agent

After successful testing, the tools will be available in the SAM agent:

```bash
# Check balance
"check my aster balance"

# Open positions
"open 10 dollars long on SOL with 5x leverage"
"buy 0.1 SOL with 3x leverage on aster"

# Manage positions
"close half my SOL position"
"check my aster positions"
"show my recent aster trades"
```

## Tool Specifications

### aster_open_long Parameters
- **symbol**: Trading pair (default: "SOLUSDT")
- **quantity**: Contract size OR
- **usd_notional**: USD amount to deploy
- **leverage**: Leverage multiplier (1-125x)
- **position_side**: "LONG" for long positions
- **recv_window**: Request timeout (optional)

### aster_close_position Parameters
- **symbol**: Trading pair
- **quantity**: Amount to close
- **position_side**: Position side to close
- **reduce_only**: Always true for safety

## Troubleshooting

### Enable Debug Logging
```bash
export LOG_LEVEL=DEBUG
./run_aster_test.sh
```

### Check Tool Registration
```bash
uv run python -c "
from sam.core.builder import AgentBuilder
import asyncio

async def main():
    builder = AgentBuilder()
    agent = await builder.build()
    tools = [t.name for t in agent.tools.list_specs() if 'aster' in t.name]
    print(f'Aster tools: {tools}')

asyncio.run(main())
"
```

### Verify Environment
```bash
source .env
echo "API Key: ${ASTER_API_KEY:0:8}...${ASTER_API_KEY: -4}"
echo "Enabled: $ENABLE_ASTER_FUTURES_TOOLS"
```

## Support

If you encounter issues:

1. Check the detailed logs in `aster_test.log`
2. Review the test results in `aster_test_results.json`
3. Verify your Aster account has futures trading enabled
4. Ensure sufficient balance in your futures wallet
5. Check Aster API status and rate limits

## Security Notes

- API keys are stored securely using the system keyring
- Private keys are encrypted with Fernet encryption
- Test amounts are minimal to prevent significant losses
- All trading operations include safety checks and validations