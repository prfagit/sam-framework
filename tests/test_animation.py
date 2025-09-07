#!/usr/bin/env python3
"""Test script for the SAM ASCII animation system."""

import asyncio
import sys
import os

# Add the sam module to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "sam"))

from sam.utils.ascii_loader import show_sam_intro


async def demo_all_animations():
    """Demo all the cool animation styles."""

    print("🎬 SAM Animation Demo")
    print("Press Ctrl+C to skip any animation\n")

    try:
        print("1️⃣ Static Art (2.5s)")
        await show_sam_intro("static")

        input("\nPress Enter to continue to Wave animation...")
        print("2️⃣ Wave Effect (4s)")
        await show_sam_intro("wave")

        input("\nPress Enter to continue to Loading animation...")
        print("3️⃣ Loading Messages (5s)")
        await show_sam_intro("loading")

        print("\n4️⃣ Glitch Intro (2s)")
        await show_sam_intro("glitch")

        print("\n🎉 Demo complete! This is what users will see when they run 'uv run sam'")

    except KeyboardInterrupt:
        print("\n👋 Demo interrupted")


if __name__ == "__main__":
    asyncio.run(demo_all_animations())
