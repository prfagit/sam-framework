import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock, call
from sam.utils.ascii_loader import (
    ASCIILoader,
    supports_ansi,
    colorize,
    SAM_ASCII_ART,
    show_sam_loading,
    show_sam_intro
)


class TestASCIILoader:
    """Test ASCII loader functionality."""

    def test_supports_ansi_tty_true(self):
        """Test ANSI support detection with TTY."""
        with patch("sys.stdout.isatty", return_value=True), \
             patch.dict("os.environ", {}, clear=True):
            assert supports_ansi() is True

    def test_supports_ansi_tty_false(self):
        """Test ANSI support detection without TTY."""
        with patch("sys.stdout.isatty", return_value=False), \
             patch.dict("os.environ", {}, clear=True):
            assert supports_ansi() is False

    def test_supports_ansi_no_color_env(self):
        """Test ANSI support with NO_COLOR environment variable."""
        with patch("sys.stdout.isatty", return_value=True), \
             patch.dict("os.environ", {"NO_COLOR": "1"}):
            assert supports_ansi() is False

    def test_colorize_with_ansi(self):
        """Test colorize function with ANSI support."""
        with patch("sam.utils.ascii_loader.supports_ansi", return_value=True):
            result = colorize("test", "\033[31m")
            assert result == "\033[31mtest\033[0m"

    def test_colorize_without_ansi(self):
        """Test colorize function without ANSI support."""
        with patch("sam.utils.ascii_loader.supports_ansi", return_value=False):
            result = colorize("test", "\033[31m")
            assert result == "test"

    def test_colorize_multiple_styles(self):
        """Test colorize function with multiple styles."""
        with patch("sam.utils.ascii_loader.supports_ansi", return_value=True):
            result = colorize("test", "\033[31m", "\033[1m")
            assert result == "\033[31m\033[1mtest\033[0m"

    def test_colorize_no_styles(self):
        """Test colorize function with no styles."""
        result = colorize("test")
        assert result == "test"

    def test_sam_ascii_art_exists(self):
        """Test that SAM_ASCII_ART is defined and has content."""
        assert SAM_ASCII_ART is not None
        assert isinstance(SAM_ASCII_ART, list)
        assert len(SAM_ASCII_ART) > 0
        assert all(isinstance(line, str) for line in SAM_ASCII_ART)

    def test_sam_ascii_art_structure(self):
        """Test that SAM_ASCII_ART has consistent line lengths."""
        if SAM_ASCII_ART:
            first_line_length = len(SAM_ASCII_ART[0])
            assert all(len(line) == first_line_length for line in SAM_ASCII_ART)

    @patch("sam.utils.ascii_loader.supports_ansi")
    @patch("builtins.print")
    def test_show_static_art(self, mock_print, mock_supports_ansi):
        """Test static ASCII art display."""
        mock_supports_ansi.return_value = True

        loader = ASCIILoader("Test Title", "Test Subtitle")

        with patch("asyncio.sleep") as mock_sleep, \
             patch.object(loader, "get_terminal_width", return_value=80):

            asyncio.run(loader.show_static_art(duration=0.1))

            mock_print.assert_called()
            mock_sleep.assert_called_once_with(0.1)

    @patch("sam.utils.ascii_loader.supports_ansi")
    @patch("builtins.print")
    def test_show_static_art_no_ansi(self, mock_print, mock_supports_ansi):
        """Test static ASCII art display without ANSI support."""
        mock_supports_ansi.return_value = False

        loader = ASCIILoader("Test Title", "Test Subtitle")

        with patch("asyncio.sleep") as mock_sleep, \
             patch.object(loader, "get_terminal_width", return_value=80):

            asyncio.run(loader.show_static_art(duration=0.1))

            mock_print.assert_called()
            mock_sleep.assert_called_once_with(0.1)

    @patch("sam.utils.ascii_loader.supports_ansi")
    @patch("builtins.print")
    def test_show_animated_loading(self, mock_print, mock_supports_ansi):
        """Test animated loading with messages."""
        mock_supports_ansi.return_value = True

        loader = ASCIILoader("Test Title", "Test Subtitle")
        messages = ["Loading...", "Processing...", "Complete!"]

        with patch("asyncio.sleep") as mock_sleep, \
             patch.object(loader, "get_terminal_width", return_value=80), \
             patch("random.random", return_value=0.5):  # No sparkles

            asyncio.run(loader.show_animated_loading(messages, duration_per_message=0.1))

            mock_print.assert_called()
            assert mock_sleep.call_count == len(messages)

    @patch("sam.utils.ascii_loader.supports_ansi")
    @patch("builtins.print")
    def test_show_animated_loading_no_ansi(self, mock_print, mock_supports_ansi):
        """Test animated loading without ANSI support."""
        mock_supports_ansi.return_value = False

        loader = ASCIILoader("Test Title", "Test Subtitle")
        messages = ["Loading...", "Processing..."]

        with patch("asyncio.sleep") as mock_sleep:
            asyncio.run(loader.show_animated_loading(messages, duration_per_message=0.1))

            # Should print fallback messages
            mock_print.assert_called()
            assert mock_sleep.call_count == len(messages)

    @patch("sam.utils.ascii_loader.supports_ansi")
    @patch("builtins.print")
    @patch("sys.stdout.write")
    def test_show_wave_effect(self, mock_stdout_write, mock_print, mock_supports_ansi):
        """Test wave effect animation."""
        mock_supports_ansi.return_value = True

        loader = ASCIILoader("Test Title", "Test Subtitle")

        with patch("asyncio.sleep") as mock_sleep, \
             patch.object(loader, "get_terminal_width", return_value=80), \
             patch("random.random", return_value=0.5):  # No sparkles

            asyncio.run(loader.show_wave_effect(duration=0.2))

            mock_stdout_write.assert_called()
            mock_print.assert_called()
            mock_sleep.assert_called()

    @patch("sam.utils.ascii_loader.supports_ansi")
    @patch("builtins.print")
    @patch("sys.stdout.write")
    def test_show_wave_effect_no_ansi(self, mock_stdout_write, mock_print, mock_supports_ansi):
        """Test wave effect fallback without ANSI."""
        mock_supports_ansi.return_value = False

        loader = ASCIILoader("Test Title", "Test Subtitle")

        with patch("asyncio.sleep") as mock_sleep:
            asyncio.run(loader.show_wave_effect(duration=0.1))

            # Should call show_static_art as fallback
            mock_print.assert_called()

    @patch("sam.utils.ascii_loader.supports_ansi")
    @patch("builtins.print")
    @patch("sys.stdout.write")
    def test_show_glitch_intro(self, mock_stdout_write, mock_print, mock_supports_ansi):
        """Test glitch intro animation."""
        mock_supports_ansi.return_value = True

        loader = ASCIILoader("Test Title", "Test Subtitle")

        with patch("asyncio.sleep") as mock_sleep, \
             patch.object(loader, "get_terminal_width", return_value=80), \
             patch("random.random", return_value=0.5), \
             patch("random.choice", return_value="▓"):

            asyncio.run(loader.show_glitch_intro(duration=0.2))

            mock_stdout_write.assert_called()
            mock_print.assert_called()
            mock_sleep.assert_called()

    @patch("sam.utils.ascii_loader.supports_ansi")
    def test_show_glitch_intro_no_ansi(self, mock_supports_ansi):
        """Test glitch intro fallback without ANSI."""
        mock_supports_ansi.return_value = False

        loader = ASCIILoader("Test Title", "Test Subtitle")

        with patch("asyncio.sleep") as mock_sleep:
            asyncio.run(loader.show_glitch_intro(duration=0.1))

            # Should call show_static_art as fallback

    def test_center_text(self):
        """Test text centering functionality."""
        loader = ASCIILoader()

        # Test basic centering
        result = loader.center_text("test", width=10)
        assert len(result) == 10
        assert "test" in result

        # Test with ANSI codes (should be ignored for length calculation)
        with patch("sam.utils.ascii_loader.supports_ansi", return_value=True):
            colored_text = colorize("test", "\033[31m")
            result = loader.center_text(colored_text, width=10)
            # Remove ANSI codes to check visible length
            import re
            visible_result = re.sub(r"\033\[[0-9;]*m", "", result)
            assert len(visible_result) == 10
            assert "test" in result

    def test_get_terminal_width_shutil_success(self):
        """Test terminal width detection with shutil."""
        loader = ASCIILoader()

        mock_size = MagicMock()
        mock_size.columns = 120

        with patch("shutil.get_terminal_size", return_value=mock_size):
            result = loader.get_terminal_width()
            assert result == 120

    def test_get_terminal_width_shutil_failure(self):
        """Test terminal width detection fallback."""
        loader = ASCIILoader()

        with patch("shutil.get_terminal_size", side_effect=OSError):
            result = loader.get_terminal_width()
            assert result == 80  # Default fallback

    def test_clear_screen(self):
        """Test screen clearing functionality."""
        loader = ASCIILoader()

        with patch("sam.utils.ascii_loader.supports_ansi", return_value=True), \
             patch("sys.stdout.write") as mock_write, \
             patch("sys.stdout.flush") as mock_flush:

            loader.clear_screen()

            mock_write.assert_called_once_with("\033[2J\033[H")
            mock_flush.assert_called_once()

    def test_clear_screen_no_ansi(self):
        """Test screen clearing without ANSI support."""
        loader = ASCIILoader()

        with patch("sam.utils.ascii_loader.supports_ansi", return_value=False), \
             patch("sys.stdout.write") as mock_write:

            loader.clear_screen()

            mock_write.assert_not_called()

    def test_hide_cursor(self):
        """Test cursor hiding functionality."""
        loader = ASCIILoader()

        with patch("sam.utils.ascii_loader.supports_ansi", return_value=True), \
             patch("sys.stdout.write") as mock_write, \
             patch("sys.stdout.flush") as mock_flush:

            loader.hide_cursor()

            mock_write.assert_called_once_with("\033[?25l")
            mock_flush.assert_called_once()

    def test_show_cursor(self):
        """Test cursor showing functionality."""
        loader = ASCIILoader()

        with patch("sam.utils.ascii_loader.supports_ansi", return_value=False), \
             patch("sys.stdout.write") as mock_write:

            loader.show_cursor()

            mock_write.assert_not_called()

    @patch("sam.utils.ascii_loader.ASCIILoader")
    async def test_show_sam_loading(self, mock_loader_class):
        """Test show_sam_loading convenience function."""
        mock_loader = MagicMock()
        mock_loader.start = AsyncMock()
        mock_loader_class.return_value = mock_loader

        await show_sam_loading()

        mock_loader_class.assert_called_once()
        mock_loader.start.assert_called_once()

    @patch("sam.utils.ascii_loader.ASCIILoader")
    async def test_show_sam_intro_glitch(self, mock_loader_class):
        """Test show_sam_intro with glitch style."""
        mock_loader = MagicMock()
        mock_loader.show_glitch_intro = AsyncMock()
        mock_loader_class.return_value = mock_loader

        await show_sam_intro("glitch")

        mock_loader_class.assert_called_once()
        mock_loader.show_glitch_intro.assert_called_once()

    @patch("sam.utils.ascii_loader.ASCIILoader")
    async def test_show_sam_intro_wave(self, mock_loader_class):
        """Test show_sam_intro with wave style."""
        mock_loader = MagicMock()
        mock_loader.show_wave_effect = AsyncMock()
        mock_loader_class.return_value = mock_loader

        await show_sam_intro("wave")

        mock_loader.show_wave_effect.assert_called_once()

    @patch("sam.utils.ascii_loader.ASCIILoader")
    async def test_show_sam_intro_static(self, mock_loader_class):
        """Test show_sam_intro with static style (default)."""
        mock_loader = MagicMock()
        mock_loader.show_static_art = AsyncMock()
        mock_loader_class.return_value = mock_loader

        await show_sam_intro("static")

        mock_loader.show_static_art.assert_called_once()

    @patch("sam.utils.ascii_loader.ASCIILoader")
    async def test_show_sam_intro_default(self, mock_loader_class):
        """Test show_sam_intro with default style."""
        mock_loader = MagicMock()
        mock_loader.show_glitch_intro = AsyncMock()
        mock_loader_class.return_value = mock_loader

        await show_sam_intro()  # No style specified

        mock_loader.show_glitch_intro.assert_called_once()

    async def test_loader_start_stop(self):
        """Test loader start and stop functionality."""
        loader = ASCIILoader()

        with patch("sam.utils.ascii_loader.supports_ansi", return_value=True), \
             patch.object(loader, "show_wave_effect") as mock_wave, \
             patch.object(loader, "show_cursor") as mock_show_cursor:

            # Test start
            await loader.start()
            mock_wave.assert_called_once()

            # Test stop
            await loader.stop()
            mock_show_cursor.assert_called_once()

    async def test_loader_stop_without_task(self):
        """Test loader stop when no task is running."""
        loader = ASCIILoader()

        with patch.object(loader, "show_cursor") as mock_show_cursor:
            await loader.stop()
            mock_show_cursor.assert_called_once()

    async def test_loader_stop_with_cancelled_task(self):
        """Test loader stop with already cancelled task."""
        loader = ASCIILoader()

        mock_task = MagicMock()
        mock_task.done.return_value = True
        loader.task = mock_task

        with patch.object(loader, "show_cursor") as mock_show_cursor:
            await loader.stop()
            mock_show_cursor.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__])
