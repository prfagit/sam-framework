import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from sam.commands.health import run_health_check


class TestHealthCheck:
    """Test health check command functionality."""

    @pytest.mark.asyncio
    @patch("sam.utils.error_handling.get_error_tracker")
    @patch("sam.utils.rate_limiter.get_rate_limiter")
    @patch("sam.utils.secure_storage.get_secure_storage")
    @patch("sam.utils.error_handling.get_health_checker")
    async def test_health_check_success(
        self,
        mock_get_health_checker,
        mock_get_secure_storage,
        mock_get_rate_limiter,
        mock_get_error_tracker,
    ):
        """Test successful health check with all components healthy."""
        # Mock health checker
        mock_health_checker = MagicMock()
        mock_health_checker.register_health_check = MagicMock()
        mock_health_checker.run_health_checks = AsyncMock(return_value={
            "database": {"status": "ok", "stats": {"sessions": 5}},
            "secure_storage": {"status": "healthy", "test_results": True},
            "rate_limiter": {"status": "healthy", "active_keys": 2},
            "error_tracker": {"status": "healthy", "recent_errors": 0},
        })
        mock_get_health_checker.return_value = mock_health_checker

        # Mock secure storage
        mock_storage = MagicMock()
        mock_storage.test_keyring_access.return_value = {"status": "healthy"}
        mock_get_secure_storage.return_value = mock_storage

        # Mock rate limiter
        mock_rate_limiter = MagicMock()
        mock_rate_limiter.request_history = {}
        mock_get_rate_limiter.return_value = mock_rate_limiter

        # Mock error tracker
        mock_error_tracker = AsyncMock()
        mock_error_tracker.get_error_stats.return_value = {"total_errors": 0}
        mock_get_error_tracker.return_value = mock_error_tracker

        # Mock memory manager
        with patch("sam.core.memory.MemoryManager") as mock_memory_class:
            mock_memory = MagicMock()
            mock_memory.initialize = AsyncMock()
            mock_memory.get_session_stats = AsyncMock(return_value={"total": 10})
            mock_memory_class.return_value = mock_memory

            result = await run_health_check()

            assert result == 0  # Success
            mock_health_checker.register_health_check.assert_called()
            mock_health_checker.run_health_checks.assert_called_once()

    @pytest.mark.asyncio
    @patch("sam.utils.error_handling.get_error_tracker")
    @patch("sam.utils.rate_limiter.get_rate_limiter")
    @patch("sam.utils.secure_storage.get_secure_storage")
    @patch("sam.utils.error_handling.get_health_checker")
    async def test_health_check_with_issues(
        self,
        mock_get_health_checker,
        mock_get_secure_storage,
        mock_get_rate_limiter,
        mock_get_error_tracker,
    ):
        """Test health check with some components having issues."""
        # Mock health checker with issues
        mock_health_checker = MagicMock()
        mock_health_checker.register_health_check = MagicMock()
        mock_health_checker.run_health_checks = AsyncMock(return_value={
            "database": {"status": "error", "error": "Connection failed"},
            "secure_storage": {"status": "healthy"},
            "rate_limiter": {"status": "warning", "error": "High usage"},
            "error_tracker": {"recent_errors": 5},
        })
        mock_get_health_checker.return_value = mock_health_checker

        # Mock other components
        mock_storage = MagicMock()
        mock_storage.test_keyring_access.return_value = {"status": "healthy"}
        mock_get_secure_storage.return_value = mock_storage

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.request_history = {"key1": [], "key2": []}
        mock_get_rate_limiter.return_value = mock_rate_limiter

        mock_error_tracker = AsyncMock()
        mock_error_tracker.get_error_stats.return_value = {"total_errors": 5}
        mock_get_error_tracker.return_value = mock_error_tracker

        with patch("sam.core.memory.MemoryManager") as mock_memory_class:
            mock_memory = MagicMock()
            mock_memory.initialize = AsyncMock()
            mock_memory.get_session_stats = AsyncMock(return_value={"total": 10})
            mock_memory_class.return_value = mock_memory

            result = await run_health_check()

            assert result == 1  # Issues detected

    @pytest.mark.asyncio
    @patch("sam.utils.error_handling.get_error_tracker")
    @patch("sam.utils.rate_limiter.get_rate_limiter")
    @patch("sam.utils.secure_storage.get_secure_storage")
    @patch("sam.utils.error_handling.get_health_checker")
    async def test_health_check_with_errors(
        self,
        mock_get_health_checker,
        mock_get_secure_storage,
        mock_get_rate_limiter,
        mock_get_error_tracker,
    ):
        """Test health check when error tracker shows errors."""
        # Mock health checker
        mock_health_checker = MagicMock()
        mock_health_checker.register_health_check = MagicMock()
        mock_health_checker.run_health_checks = AsyncMock(return_value={
            "database": {"status": "ok"},
            "secure_storage": {"status": "healthy"},
            "rate_limiter": {"status": "healthy"},
            "error_tracker": {"recent_errors": 0},
        })
        mock_get_health_checker.return_value = mock_health_checker

        # Mock components
        mock_storage = MagicMock()
        mock_storage.test_keyring_access.return_value = {"status": "healthy"}
        mock_get_secure_storage.return_value = mock_storage

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.request_history = {}
        mock_get_rate_limiter.return_value = mock_rate_limiter

        # Mock error tracker with errors
        mock_error_tracker = AsyncMock()
        mock_error_tracker.get_error_stats.return_value = {
            "total_errors": 15,
            "severity_counts": {"error": 10, "warning": 5},
            "critical_errors": [
                {"timestamp": "2024-01-01", "component": "database", "error_message": "Connection lost"}
            ]
        }
        mock_get_error_tracker.return_value = mock_error_tracker

        with patch("sam.core.memory.MemoryManager") as mock_memory_class:
            mock_memory = MagicMock()
            mock_memory.initialize = AsyncMock()
            mock_memory.get_session_stats = AsyncMock(return_value={"total": 10})
            mock_memory_class.return_value = mock_memory

            result = await run_health_check()

            assert result == 1  # Errors detected

    @pytest.mark.asyncio
    @patch("sam.utils.error_handling.get_error_tracker")
    @patch("sam.utils.rate_limiter.get_rate_limiter")
    @patch("sam.utils.secure_storage.get_secure_storage")
    @patch("sam.utils.error_handling.get_health_checker")
    async def test_health_check_exception_handling(
        self,
        mock_get_health_checker,
        mock_get_secure_storage,
        mock_get_rate_limiter,
        mock_get_error_tracker,
    ):
        """Test health check exception handling."""
        # Mock health checker to raise exception
        mock_health_checker = MagicMock()
        mock_health_checker.register_health_check = MagicMock()
        mock_health_checker.run_health_checks = AsyncMock(side_effect=Exception("Test error"))
        mock_get_health_checker.return_value = mock_health_checker

        # Mock other components
        mock_storage = MagicMock()
        mock_storage.test_keyring_access.return_value = {"status": "healthy"}
        mock_get_secure_storage.return_value = mock_storage

        mock_rate_limiter = MagicMock()
        mock_rate_limiter.request_history = {}
        mock_get_rate_limiter.return_value = mock_rate_limiter

        mock_error_tracker = AsyncMock()
        mock_error_tracker.get_error_stats.return_value = {"total_errors": 0}
        mock_get_error_tracker.return_value = mock_error_tracker

        with patch("sam.core.memory.MemoryManager") as mock_memory_class:
            mock_memory = MagicMock()
            mock_memory.initialize = AsyncMock()
            mock_memory.get_session_stats = AsyncMock(return_value={"total": 10})
            mock_memory_class.return_value = mock_memory

            result = await run_health_check()

            assert result == 1  # Error occurred

    def test_health_check_imports(self):
        """Test that all required imports are available."""
        import importlib.util

        required_modules = [
            "sam.utils.error_handling",
            "sam.utils.secure_storage",
            "sam.utils.rate_limiter",
            "sam.core.memory"
        ]

        for module_name in required_modules:
            spec = importlib.util.find_spec(module_name)
            if spec is None:
                pytest.fail(f"Missing import: {module_name}")


if __name__ == "__main__":
    pytest.main([__file__])
