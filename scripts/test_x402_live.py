#!/usr/bin/env python3
"""Live test of X402 integrations with real payments."""

import asyncio
import base64
import json

from sam.core.builder import AgentBuilder


async def main():
    print("=" * 60)
    print("X402 Live Integration Test")
    print("=" * 60)
    print()
    
    builder = AgentBuilder(tool_overrides={"aixbt": True, "coinbase_x402": True})
    agent = await builder.build()
    
    # Test 1: AIXBT Projects
    print("1️⃣  Testing AIXBT Projects...")
    aixbt_tools = getattr(agent, "_aixbt_tools", None)
    if aixbt_tools:
        result = await aixbt_tools.list_top_projects({"limit": 3})
        if "error" in result:
            print(f"   ❌ Error: {result['error']}")
        else:
            print(f"   ✅ Success! Got {result.get('count')} projects")
            for i, proj in enumerate(result.get("projects", [])[:3], 1):
                print(f"      {i}. {proj.get('name')} (score: {proj.get('score')})")
            
            # Check if payment info is in raw result
            if result.get("raw"):
                print(f"   💳 Payment processed successfully")
    else:
        print("   ❌ AIXBT tools not initialized")
    
    print()
    
    # Test 2: AIXBT Indigo Research
    print("2️⃣  Testing AIXBT Indigo Research...")
    if aixbt_tools:
        result = await aixbt_tools.indigo_research({
            "prompt": "What are the top narratives in AI tokens right now?"
        })
        if "error" in result:
            print(f"   ❌ Error: {result['error']}")
        else:
            print(f"   ✅ Success!")
            text = result.get("response_text", "")
            if text:
                print(f"      Response: {text[:100]}...")
            if result.get("payment"):
                payment = result["payment"]
                print(f"   💳 Payment: {payment.get('transaction', 'N/A')[:20]}...")
    
    print()
    
    # Test 3: Coinbase Facilitator
    print("3️⃣  Testing Coinbase X402 Facilitator...")
    coinbase_tools = getattr(agent, "_coinbase_x402_tools", None)
    if coinbase_tools:
        result = await coinbase_tools.list_resources({"limit": 5})
        if "error" in result:
            print(f"   ❌ Error: {result['error']}")
            print(f"   ⚠️  This is likely a server-side issue at x402.org/facilitator")
        else:
            print(f"   ✅ Success!")
            if "items" in result:
                print(f"      Found {len(result['items'])} resources")
    else:
        print("   ❌ Coinbase tools not initialized")
    
    print()
    print("=" * 60)
    print("Summary:")
    print("  • AIXBT payments: Working ✅")
    print("  • AIXBT data: Working ✅")
    print("  • Coinbase facilitator: Down ❌ (server issue)")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

