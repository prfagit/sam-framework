#!/usr/bin/env python3
"""SAM Framework ASCII Art Loading Animation.

Cool loading animations with the SAM ASCII art from the README.
"""

import asyncio
import sys
import os
import random
from typing import List, Optional


class Style:
    """ANSI color codes for styling."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Colors
    FG_CYAN = "\033[36m"
    FG_GREEN = "\033[32m"
    FG_YELLOW = "\033[33m"
    FG_BLUE = "\033[34m"
    FG_MAGENTA = "\033[35m"
    FG_WHITE = "\033[37m"
    FG_GRAY = "\033[90m"

    # Bright colors
    FG_BRIGHT_CYAN = "\033[96m"
    FG_BRIGHT_GREEN = "\033[92m"
    FG_BRIGHT_YELLOW = "\033[93m"
    FG_BRIGHT_BLUE = "\033[94m"
    FG_BRIGHT_MAGENTA = "\033[95m"


def supports_ansi() -> bool:
    """Check if terminal supports ANSI escape sequences."""
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def colorize(text: str, *styles: str) -> str:
    """Apply ANSI color styles to text."""
    if not supports_ansi() or not styles:
        return text
    return f"{''.join(styles)}{text}{Style.RESET}"


# The awesome SAM ASCII art from the README
SAM_ASCII_ART = [
    "⠀⠀⠀⢘⠀⡂⢠⠆⠀⡰⠀⡀⢀⣠⣶⣦⣶⣶⣶⣶⣾⣿⣿⡿⢀⠈⢐⠈⠀⠀",
    "⠀⠀⠀⡁⢄⡀⣞⡇⢰⠃⣼⣇⠀⣿⣿⣿⣿⣿⣿⣿⣿⣿⠛⣰⣻⡀⢸⠀⠀⠀",
    "⠀⠀⠀⣠⠁⣛⣽⣇⠘⢸⣿⣿⣷⣾⣿⣿⣿⣿⣿⣿⣿⠟⢡⣾⣿⢿⡇⠀⡃⠀",
    "⠀⠀⢀⠐⠀⢳⣿⡯⡞⣾⣿⣿⣿⣿⣿⣿⢿⣿⠟⢁⣴⣿⣿⣿⡜⢷⠀⢘⠄⠀",
    "⠀⠀⠀⡊⢸⡆⠙⠛⡵⣿⣿⣿⣿⣿⡿⠤⠛⣠⣴⣿⣿⠿⣟⣟⠟⢿⡆⢳⠀⠀",
    "⠀⠀⠘⡁⢸⡾⠁⠀⠀⠀⠀⠉⠉⠉⠈⣠⡌⢁⠄⡛⠡⠉⠍⠙⢳⢾⠁⢸⠀⠀",
    "⠀⠀⠀⠂⢨⠌⠀⠀⠀⠀⠀⠀⠀⠀⢀⣤⣷⡎⠙⢬⣳⣪⡯⢜⣷⢸⠂⡈⠄⠀",
    "⠀⠀⠀⠆⣰⢣⠀⠀⠀⠀⠀⠀⠀⣴⣿⣾⣷⢿⢻⣅⣌⡯⢛⣿⣿⡞⠠⡁⠂⠀",
    "⠀⠀⠀⠄⢲⢉⡀⠀⠀⢀⡠⠤⠼⣇⣳⣿⣿⣟⡜⣿⣿⣿⣿⣿⣿⡇⠸⠡⠀⠀",
    "⠀⠀⡀⠁⠹⠃⢀⡀⣿⡹⠗⢀⠛⠥⣺⣿⣿⡝⢹⣸⣿⣿⣿⣿⡏⠠⠰⠈⠐⠀",
    "⠠⠈⠀⠄⣀⠀⠀⠸⠻⠦⠀⠀⠀⠀⠀⠉⠐⠀⠘⠻⢹⣿⡿⠃⠀⡀⠕⣈⠡⡄",
    "⠀⠀⣴⡀⣬⠁⠀⠀⡁⠂⠀⣀⣀⠔⠌⠤⣀⡀⠀⠀⡈⢸⠪⠀⠀⡌⠤⠈⡀⣠",
    "⠀⠀⣿⣿⣾⡇⠀⠀⠀⣴⢫⣾⠃⠠⢰⣶⣴⠶⣿⣦⠀⠀⠀⢄⣂⠀⠀⠰⠀⠙",
    "⠀⠀⠉⠛⠛⠀⢀⣴⣿⢗⡟⠡⣄⣀⡀⠀⢀⣤⠞⡅⠀⠁⠀⡾⠀⠀⠠⡗⠀⢀",
    "⠀⠀⠀⠀⠀⣴⡿⢋⠔⠃⠀⠀⠍⠙⠉⠈⠑⠁⠂⠀⠀⠀⡡⡁⣠⡼⣸⠅⠀⠘",
    "⠀⠀⠀⣼⠛⢡⠔⠁⠐⣆⠀⠀⠀⠀⠀⠀⠀⠀⠁⢀⡔⡞⢛⣿⡿⠃⠏⠀⠀⢠",
    "⠀⠀⠀⠈⠗⠀⠀⠀⠀⠘⣷⣀⢀⣀⣀⠀⡀⢀⣌⡧⠂⠀⡞⠛⡟⠀⠀⠀⡠⠜",
    "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⠓⠈⠙⠙⠋⠉⠁⠀⠀⠀⠀⠀⠀⠀⡂⠠⠤⢶",
]


class ASCIILoader:
    """Animated ASCII art loader for SAM."""

    def __init__(self, title: str = "SAM Framework", subtitle: str = "Solana Agent Middleware"):
        self.title = title
        self.subtitle = subtitle
        self.running = False
        self.task: Optional[asyncio.Task] = None

        # Animation frames for different effects
        self.glow_frames = ["⡀", "⠄", "⠂", "⠁", "⠈", "⠐", "⠠", "⢀"]
        self.spark_chars = ["✦", "✧", "⭐", "✨", "💫", "⚡", "🌟"]

        # Color schemes for cycling
        self.color_schemes = [
            [Style.FG_CYAN, Style.FG_BRIGHT_CYAN],
            [Style.FG_GREEN, Style.FG_BRIGHT_GREEN],
            [Style.FG_MAGENTA, Style.FG_BRIGHT_MAGENTA],
            [Style.FG_BLUE, Style.FG_BRIGHT_BLUE],
        ]

    def clear_screen(self):
        """Clear the terminal screen."""
        if supports_ansi():
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()

    def hide_cursor(self):
        """Hide terminal cursor."""
        if supports_ansi():
            sys.stdout.write("\033[?25l")
            sys.stdout.flush()

    def show_cursor(self):
        """Show terminal cursor."""
        if supports_ansi():
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()

    def center_text(self, text: str, width: int = 80) -> str:
        """Center text within given width."""
        # Remove ANSI codes for length calculation
        import re

        clean_text = re.sub(r"\033\[[0-9;]*m", "", text)
        text_length = len(clean_text)
        if text_length >= width:
            return text
        
        left_padding = (width - text_length) // 2
        right_padding = width - text_length - left_padding
        
        # Return with padding but preserve exact width by recalculating with ANSI codes
        result = " " * left_padding + text + " " * right_padding
        result_clean = re.sub(r"\033\[[0-9;]*m", "", result)
        
        # Adjust padding if ANSI codes affected the total length
        if len(result_clean) != width:
            actual_padding_needed = width - text_length
            left_padding = actual_padding_needed // 2
            right_padding = actual_padding_needed - left_padding
            result = " " * left_padding + text + " " * right_padding
        
        return result

    def get_terminal_width(self) -> int:
        """Get terminal width or default to 80."""
        try:
            import shutil

            return shutil.get_terminal_size().columns
        except (OSError, ValueError):
            return 80

    async def show_static_art(self, duration: float = 2.0):
        """Display static ASCII art with title."""
        self.clear_screen()
        self.hide_cursor()

        width = self.get_terminal_width()

        try:
            # Title
            title_text = colorize(self.title, Style.BOLD, Style.FG_BRIGHT_CYAN)
            subtitle_text = colorize(self.subtitle, Style.DIM, Style.FG_GRAY)

            print()
            print(self.center_text(title_text, width))
            print(self.center_text(subtitle_text, width))
            print()

            # ASCII Art
            for line in SAM_ASCII_ART:
                colored_line = colorize(line, Style.FG_CYAN)
                print(self.center_text(colored_line, width))

            await asyncio.sleep(duration)

        finally:
            self.show_cursor()

    async def show_animated_loading(self, messages: List[str], duration_per_message: float = 1.5):
        """Show animated loading with changing messages."""
        if not supports_ansi():
            # Fallback for non-ANSI terminals
            for msg in messages:
                print(f"Loading: {msg}...")
                await asyncio.sleep(duration_per_message)
            return

        self.hide_cursor()
        width = self.get_terminal_width()

        try:
            for i, message in enumerate(messages):
                # Clear and redraw
                self.clear_screen()

                # Cycle through color schemes
                colors = self.color_schemes[i % len(self.color_schemes)]
                primary_color, bright_color = colors

                # Title with subtle animation
                title_text = colorize(self.title, Style.BOLD, bright_color)
                subtitle_text = colorize(self.subtitle, Style.DIM, Style.FG_GRAY)

                print()
                print(self.center_text(title_text, width))
                print(self.center_text(subtitle_text, width))
                print()

                # Animate ASCII art lines appearing
                lines_to_show = min(
                    len(SAM_ASCII_ART), int((i + 1) / len(messages) * len(SAM_ASCII_ART)) + 3
                )

                for j, line in enumerate(SAM_ASCII_ART):
                    if j < lines_to_show:
                        # Add some sparkle effects
                        if random.random() < 0.1:  # 10% chance
                            spark = random.choice(self.spark_chars)
                            line_with_spark = line + f" {colorize(spark, bright_color)}"
                        else:
                            line_with_spark = line

                        colored_line = colorize(line_with_spark, primary_color)
                        print(self.center_text(colored_line, width))
                    else:
                        print(
                            self.center_text(
                                colorize("⠀" * len(SAM_ASCII_ART[0]), Style.DIM), width
                            )
                        )

                # Loading message with spinner
                print()
                spinner = self.glow_frames[i % len(self.glow_frames)]
                loading_text = f"{colorize(spinner, bright_color)} {colorize(message, Style.DIM)}"
                print(self.center_text(loading_text, width))

                await asyncio.sleep(duration_per_message)

        finally:
            self.show_cursor()

    async def show_wave_effect(self, duration: float = 3.0):
        """Show ASCII art with a wave color effect."""
        if not supports_ansi():
            await self.show_static_art(duration)
            return

        self.hide_cursor()
        width = self.get_terminal_width()

        try:
            frames = int(duration * 10)  # 10 FPS

            for frame in range(frames):
                self.clear_screen()

                # Title
                title_text = colorize(self.title, Style.BOLD, Style.FG_BRIGHT_CYAN)
                subtitle_text = colorize(self.subtitle, Style.DIM, Style.FG_GRAY)

                print()
                print(self.center_text(title_text, width))
                print(self.center_text(subtitle_text, width))
                print()

                # Wave effect through the ASCII art
                for i, line in enumerate(SAM_ASCII_ART):
                    # Calculate wave position
                    wave_pos = (frame * 0.5 + i * 0.3) % (len(self.color_schemes) * 2)
                    color_index = int(wave_pos) % len(self.color_schemes)

                    # Select color based on wave
                    colors = self.color_schemes[color_index]
                    color = colors[1] if wave_pos % 2 < 1 else colors[0]

                    # Add occasional sparkles
                    sparkle = ""
                    if random.random() < 0.05:  # 5% chance
                        sparkle = (
                            f" {colorize(random.choice(self.spark_chars), Style.FG_BRIGHT_YELLOW)}"
                        )

                    colored_line = colorize(line, color) + sparkle
                    print(self.center_text(colored_line, width))

                await asyncio.sleep(0.1)

        finally:
            self.show_cursor()

    async def show_glitch_intro(self, duration: float = 1.8):
        """Fast glitchy ASCII intro - no fluff, just cool."""
        if not supports_ansi():
            await self.show_static_art(0.5)
            return

        self.hide_cursor()
        width = self.get_terminal_width()

        glitch_chars = "▓▒░█⣿⢸⡇⠀⢀01"

        try:
            frames = int(duration * 30)  # 30 FPS for smooth glitch

            for frame in range(frames):
                self.clear_screen()

                # Glitchy title
                if frame % 8 < 6:  # Show most of the time
                    title = colorize("SAM", Style.BOLD, Style.FG_BRIGHT_CYAN)
                else:  # Glitch occasionally
                    title = colorize("S▓M", Style.BOLD, Style.FG_BRIGHT_GREEN)

                print()
                print(self.center_text(title, width))
                print()

                # Glitchy ASCII reveal
                progress = frame / frames
                lines_revealed = int(progress * len(SAM_ASCII_ART))

                for i, line in enumerate(SAM_ASCII_ART):
                    if i < lines_revealed:
                        # Revealed line with occasional glitch
                        if random.random() < 0.08:  # 8% glitch chance
                            glitched = "".join(
                                random.choice(glitch_chars) if random.random() < 0.3 else c
                                for c in line
                            )
                            colored_line = colorize(glitched, Style.FG_GREEN)
                        else:
                            colored_line = colorize(line, Style.FG_BRIGHT_CYAN)
                    elif i == lines_revealed and progress < 0.95:  # Current line being decoded
                        chars_shown = int((frame % 8) / 8 * len(line))
                        partial = line[:chars_shown]
                        noise = "".join(
                            random.choice(glitch_chars) for _ in range(len(line) - chars_shown)
                        )
                        colored_line = colorize(partial, Style.FG_BRIGHT_CYAN) + colorize(
                            noise, Style.FG_GREEN
                        )
                    else:
                        # Not revealed yet
                        colored_line = ""

                    if colored_line:
                        print(self.center_text(colored_line, width))

                await asyncio.sleep(1 / 30)  # 30 FPS

            # Quick final flash
            self.clear_screen()
            print()
            print(self.center_text(colorize("SAM", Style.BOLD, Style.FG_BRIGHT_CYAN), width))
            print()

            for line in SAM_ASCII_ART:
                print(self.center_text(colorize(line, Style.FG_CYAN), width))

            await asyncio.sleep(0.3)

        finally:
            self.show_cursor()

    async def start(self):
        """Start the loading animation."""
        if not supports_ansi():
            # Simple fallback for non-ANSI terminals
            print(f"{self.title} - {self.subtitle}")
            print("Loading...")
            return

        self.running = True

        # Show the wave effect
        await self.show_wave_effect(3.0)

        self.running = False

    async def stop(self):
        """Stop the animation."""
        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.show_cursor()


# Convenience functions for easy use
async def show_sam_loading():
    """Show the SAM loading animation."""
    loader = ASCIILoader()
    await loader.start()


async def show_sam_intro(style: str = "glitch"):
    """Show SAM intro with different animation styles.

    Args:
        style: Animation style - 'glitch', 'static', 'wave'
    """
    loader = ASCIILoader()

    if style == "glitch":
        await loader.show_glitch_intro(1.8)
    elif style == "wave":
        await loader.show_wave_effect(2.0)
    else:  # static
        await loader.show_static_art(0.8)
