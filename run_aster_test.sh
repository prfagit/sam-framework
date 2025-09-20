#!/bin/bash

echo "🚀 Aster Futures Tools - Comprehensive Test Runner"
echo "================================================="

# Check if .env file exists
if [ ! -f .env ]; then
    echo "❌ No .env file found!"
    echo "Please create a .env file with your Aster API credentials:"
    echo ""
    echo "# Aster Futures Configuration"
    echo "ENABLE_ASTER_FUTURES_TOOLS=true"
    echo "ASTER_API_KEY=your_api_key_here"
    echo "ASTER_API_SECRET=your_api_secret_here"
    echo "ASTER_BASE_URL=https://fapi.asterdex.com"
    echo "ASTER_DEFAULT_RECV_WINDOW=5000"
    echo ""
    exit 1
fi

# Check for required environment variables
source .env

if [ -z "$ASTER_API_KEY" ] || [ -z "$ASTER_API_SECRET" ]; then
    echo "❌ Missing required environment variables!"
    echo "Please set ASTER_API_KEY and ASTER_API_SECRET in your .env file"
    exit 1
fi

echo "✅ Environment configuration found"
echo "🔑 API Key: ${ASTER_API_KEY:0:8}...${ASTER_API_KEY: -4}"
echo "🔒 API Secret: ${ASTER_API_SECRET:0:8}...${ASTER_API_SECRET: -4}"
echo ""

# Run the comprehensive test
echo "🧪 Starting comprehensive Aster tools test..."
echo "This will test all tools with small amounts and real API calls."
echo ""

# Set log level to DEBUG for maximum verbosity
export LOG_LEVEL=DEBUG

# Run the test
uv run python test_aster_comprehensive.py --auto

# Check the results
if [ $? -eq 0 ]; then
    echo ""
    echo "🎉 Test completed successfully!"
    echo "📋 Check aster_test.log for detailed logs"
    echo "📊 Check aster_test_results.json for full results"
else
    echo ""
    echo "❌ Test failed!"
    echo "📋 Check aster_test.log for error details"
    exit 1
fi